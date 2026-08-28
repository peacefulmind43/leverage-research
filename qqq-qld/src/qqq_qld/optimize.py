"""Grid optimization, walk-forward selection, and bootstrap stability."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .backtest import portfolio_returns
from .metrics import TRADING_DAYS, crra_certainty_equivalent, performance_metrics

#: Objectives that are scale-invariant (or monotone) in leverage and therefore
#: cannot select it. See :func:`qqq_qld.metrics.log_growth` for why: levering a
#: single asset scales excess mean and standard deviation together, so these
#: ratios are flat in the frictionless case and strictly falling once costs are
#: paid. Their argmax over a leverage grid is the lowest-leverage point by
#: construction, and reporting that as evidence against leverage is circular.
SCALE_INVARIANT_OBJECTIVES = frozenset({"sharpe", "sortino", "calmar"})


def evaluate_grid(
    returns: pd.DataFrame,
    step: float = 0.01,
    rebalance: str = "ME",
    transaction_cost_bps: float = 0.0,
    annual_risk_free_rate: float = 0.0,
    risk_aversion: float = 1.0,
) -> pd.DataFrame:
    weights = np.round(np.arange(0.0, 1.0 + step / 2.0, step), 10)
    rows: list[dict[str, float]] = []
    for weight in weights:
        result = portfolio_returns(
            returns,
            weight_qld=float(weight),
            rebalance=rebalance,
            transaction_cost_bps=transaction_cost_bps,
        )
        metrics = performance_metrics(result, annual_risk_free_rate)
        rows.append(
            {
                "weight_qld": float(weight),
                "weight_qqq": 1.0 - float(weight),
                **metrics,
                "certainty_equivalent": crra_certainty_equivalent(result, risk_aversion),
            }
        )
    return pd.DataFrame(rows).set_index("weight_qld")


def select_optima(
    grid: pd.DataFrame,
    target_volatility: float,
    max_drawdown_limit: float,
) -> dict[str, pd.Series]:
    """Select optima under several non-equivalent definitions.

    ``max_sharpe`` and ``max_calmar`` are retained for continuity with earlier
    versions of this report, but they are *not* leverage-selection results: both
    are in :data:`SCALE_INVARIANT_OBJECTIVES` and will pin to 0% QLD regardless
    of the data. ``max_log_growth`` and ``max_certainty_equivalent`` are the
    objectives that actually trade drift against variance.
    """
    feasible = grid[grid["max_drawdown"] >= max_drawdown_limit]
    selections = {
        "max_cagr": grid.loc[grid["cagr"].idxmax()],
        "max_log_growth": grid.loc[grid["log_growth"].idxmax()],
        "max_certainty_equivalent": grid.loc[grid["certainty_equivalent"].idxmax()],
        "max_sharpe": grid.loc[grid["sharpe"].idxmax()],
        "max_calmar": grid.loc[grid["calmar"].idxmax()],
        "target_volatility": grid.loc[(grid["volatility"] - target_volatility).abs().idxmin()],
    }
    selections["max_cagr_with_drawdown_limit"] = (
        feasible.loc[feasible["cagr"].idxmax()] if not feasible.empty else pd.Series(dtype=float)
    )
    return selections


def kelly_optimal_leverage(
    returns: pd.DataFrame,
    asset: str = "QQQ",
    annual_risk_free_rate: float = 0.0,
    financing_cost: float | None = None,
    risk_aversion: float = 1.0,
) -> dict[str, float]:
    """Estimate growth-optimal leverage on a single unleveraged asset.

    Maximises the continuous-time growth approximation for a constant-leverage
    position that pays ``financing_cost`` on the borrowed fraction,

        g(L) = L*mu - (L-1)*c - 0.5*gamma*L^2*sigma^2

    giving ``L* = (mu - c) / (gamma * sigma^2)``, where ``mu`` is the asset's
    annualised arithmetic mean and ``sigma^2`` its annualised variance.

    **The financing cost belongs in the numerator and omitting it is not
    conservative.** Leverage buys ``mu`` but pays ``c`` for it, so the quantity
    being levered is the spread ``mu - c``, not ``mu``. Dropping ``c`` prices the
    borrowing at zero and inflates ``L*`` by ``c / sigma^2`` -- with this
    repository's sample that is more than a full turn of leverage. ``c`` should
    be the rate actually payable on the chosen instrument: for a QQQ/QLD blend,
    :func:`qqq_qld.costs.effective_borrow_rate` derives it from the funds' own
    histories; for margin, the broker's quoted rate.

    ``risk_aversion`` (CRRA gamma) scales the variance penalty. ``gamma=1`` is
    log utility and recovers full Kelly. Larger values shrink ``L*``
    proportionally, which is how fractional Kelly arises as an optimum under a
    stated preference rather than as an unexplained haircut -- ``half_kelly``
    below is exactly ``gamma=2``.

    Both are point estimates from one sample, and ``mu`` in particular is not a
    forecast; see :func:`kelly_sensitivity` and docs/methodology.md section 6.2.
    """
    if asset not in returns.columns:
        raise ValueError(f"{asset!r} not found in returns columns")
    if risk_aversion <= 0:
        raise ValueError("risk_aversion must be positive")
    daily = returns[asset].dropna()
    if daily.empty:
        raise ValueError("returns cannot be empty")
    cost = annual_risk_free_rate if financing_cost is None else financing_cost
    mu = float(daily.mean() * TRADING_DAYS)
    sigma2 = float(daily.var(ddof=1) * TRADING_DAYS)
    full_kelly = (mu - cost) / (risk_aversion * sigma2) if sigma2 else float("nan")
    return {
        "mu": mu,
        "sigma2": sigma2,
        "financing_cost": cost,
        "risk_aversion": risk_aversion,
        "excess_mu": mu - cost,
        "full_kelly": full_kelly,
        "half_kelly": full_kelly / 2.0,
    }


def kelly_implied_qld_weight(
    kelly: dict[str, float],
    min_weight: float = 0.0,
    max_weight: float = 1.0,
) -> float:
    """Map a Kelly leverage estimate onto the achievable QQQ/QLD weight range.

    A QQQ/QLD blend can only reach exposures in ``[1 + min_weight, 1 + max_weight]``,
    so this clips ``full_kelly - 1`` into that range. This mapping is exact only
    under daily rebalancing of the blend; see :func:`qqq_qld.leverage.rebalance_drag`
    for the empirical gap at other rebalancing frequencies.
    """
    return float(np.clip(kelly["full_kelly"] - 1.0, min_weight, max_weight))


def kelly_sensitivity(
    sigma2: float,
    mu_scenarios: dict[str, float],
    financing_cost: float = 0.0,
    min_weight: float = 0.0,
    max_weight: float = 1.0,
    geometric_input: bool = True,
    risk_aversion: float = 1.0,
) -> pd.DataFrame:
    """Recompute Kelly-implied leverage/weight across assumed forward mu values.

    ``mu_scenarios`` values are **total** expected returns, not excess returns;
    ``financing_cost`` is subtracted here. Passing excess returns and leaving
    the cost at zero double-counts nothing but silently changes what the table
    means, so keep the convention explicit in the config file.

    With ``geometric_input`` (the default) the scenarios are read as annualised
    *geometric* returns -- the convention published capital-market assumptions
    use -- and converted to the arithmetic mean Kelly is defined on by adding
    ``0.5*sigma^2``. Skipping that conversion understates mu by over three
    points at this sample's volatility, which is a large error in a formula
    whose numerator is a difference of two similar-sized numbers. Set the flag
    to ``False`` only when the inputs are already arithmetic means.

    sigma2 is held fixed across scenarios because it is far better estimated than mu
    over any realistic sample length (see docs/methodology.md section 6.2), while mu
    varies per scenario. This shows how sensitive the Kelly recommendation is to a
    parameter that cannot be reliably forecast from trailing sample returns alone.
    Note the leverage is driven by the *spread* ``mu - c``: when ``mu`` is close to
    financing cost, small changes in the assumed ``mu`` move the recommendation a
    long way, which is precisely the regime the conservative scenarios sit in.
    """
    rows: list[dict[str, float | str]] = []
    for label, mu in mu_scenarios.items():
        arithmetic = mu + 0.5 * sigma2 if geometric_input else mu
        full = (arithmetic - financing_cost) / sigma2 if sigma2 else float("nan")
        adjusted = full / risk_aversion
        rows.append(
            {
                "scenario": label,
                "assumed_mu": mu,
                "arithmetic_mu": arithmetic,
                "excess_over_financing": arithmetic - financing_cost,
                "full_kelly_leverage": full,
                "risk_adjusted_leverage": adjusted,
                "full_kelly_qld_weight": kelly_implied_qld_weight(
                    {"full_kelly": full}, min_weight, max_weight
                ),
                "risk_adjusted_qld_weight": kelly_implied_qld_weight(
                    {"full_kelly": adjusted}, min_weight, max_weight
                ),
            }
        )
    return pd.DataFrame(rows).set_index("scenario")


def walk_forward(
    returns: pd.DataFrame,
    min_train_years: int = 5,
    test_years: int = 1,
    objective: str = "log_growth",
    step: float = 0.01,
    rebalance: str = "ME",
    transaction_cost_bps: float = 0.0,
    annual_risk_free_rate: float = 0.0,
    risk_aversion: float = 1.0,
) -> tuple[pd.DataFrame, pd.Series]:
    """Expanding-window selection with non-overlapping out-of-sample tests.

    ``objective`` defaults to ``log_growth``. A scale-invariant objective here
    produces a walk-forward that selects the same minimum-leverage weight every
    year for algebraic reasons, which looks like a strong and stable
    out-of-sample finding but is an artefact; see
    :data:`SCALE_INVARIANT_OBJECTIVES`.
    """
    if objective in SCALE_INVARIANT_OBJECTIVES:
        warnings.warn(
            f"objective={objective!r} cannot select leverage: it is scale-invariant in "
            "leverage, so its argmax is the lowest-leverage grid point regardless of the "
            "data. Use 'log_growth' or 'certainty_equivalent'.",
            RuntimeWarning,
            stacklevel=2,
        )
    first_test_year = returns.index.min().year + min_train_years
    last_year = returns.index.max().year
    rows: list[dict[str, float | int | str]] = []
    oos_parts: list[pd.Series] = []

    for test_start_year in range(first_test_year, last_year + 1, test_years):
        train_end = pd.Timestamp(f"{test_start_year - 1}-12-31")
        test_end = pd.Timestamp(f"{test_start_year + test_years - 1}-12-31")
        train = returns.loc[:train_end]
        test = returns.loc[pd.Timestamp(f"{test_start_year}-01-01") : test_end]
        if len(train) < min_train_years * 200 or len(test) < 20:
            continue
        grid = evaluate_grid(
            train,
            step=step,
            rebalance=rebalance,
            transaction_cost_bps=transaction_cost_bps,
            annual_risk_free_rate=annual_risk_free_rate,
            risk_aversion=risk_aversion,
        )
        weight = float(grid[objective].idxmax())
        oos = portfolio_returns(
            test,
            weight_qld=weight,
            rebalance=rebalance,
            transaction_cost_bps=transaction_cost_bps,
        )
        oos_parts.append(oos)
        oos_metrics = performance_metrics(oos, annual_risk_free_rate)
        rows.append(
            {
                "test_start": str(test.index.min().date()),
                "test_end": str(test.index.max().date()),
                "selected_weight_qld": weight,
                **oos_metrics,
            }
        )
    if not oos_parts:
        raise ValueError("Not enough data for walk-forward analysis")
    return pd.DataFrame(rows), pd.concat(oos_parts).sort_index()


def stationary_block_bootstrap_weights(
    returns: pd.DataFrame,
    samples: int = 1000,
    block_days: int = 21,
    objective: str = "log_growth",
    step: float = 0.01,
    seed: int = 42,
    risk_aversion: float = 1.0,
    **grid_kwargs,
) -> pd.Series:
    """Estimate optimal-weight stability with a moving-block bootstrap.

    For speed, bootstrap selection uses the daily-rebalanced QQQ/QLD mixture.
    This is an intentionally disclosed approximation to the monthly-rebalanced
    full backtest; it answers whether the estimated exposure itself is stable.

    Under a scale-invariant ``objective`` every resample returns the same
    minimum-leverage weight, and the resulting zero-width percentile band
    reads as certainty when it is only algebra; see
    :data:`SCALE_INVARIANT_OBJECTIVES`.
    """
    if objective not in {"sharpe", "log_growth", "certainty_equivalent"}:
        raise ValueError(
            "objective must be 'log_growth', 'certainty_equivalent', or 'sharpe'"
        )
    if objective in SCALE_INVARIANT_OBJECTIVES:
        warnings.warn(
            f"objective={objective!r} cannot select leverage; see SCALE_INVARIANT_OBJECTIVES",
            RuntimeWarning,
            stacklevel=2,
        )
    rng = np.random.default_rng(seed)
    n = len(returns)
    chosen = np.empty(samples)
    weights = np.round(np.arange(0.0, 1.0 + step / 2.0, step), 10)
    annual_rf = float(grid_kwargs.get("annual_risk_free_rate", 0.0))
    daily_rf = (1.0 + annual_rf) ** (1.0 / 252.0) - 1.0
    for sample in range(samples):
        indices: list[int] = []
        while len(indices) < n:
            start = int(rng.integers(0, max(1, n - block_days + 1)))
            indices.extend(range(start, min(start + block_days, n)))
        boot = returns.iloc[indices[:n]][["QQQ", "QLD"]].to_numpy(dtype=float)
        means = boot.mean(axis=0)
        covariance = np.cov(boot, rowvar=False, ddof=1)
        qqq_weights = 1.0 - weights
        portfolio_means = qqq_weights * means[0] + weights * means[1]
        variances = (
            qqq_weights**2 * covariance[0, 0]
            + weights**2 * covariance[1, 1]
            + 2.0 * qqq_weights * weights * covariance[0, 1]
        )
        if objective == "sharpe":
            score = (portfolio_means - daily_rf) / np.sqrt(variances) * np.sqrt(252.0)
        else:
            # Lognormal approximation to annualised growth, consistent with
            # metrics.log_growth / crra_certainty_equivalent but computed from
            # the resample's moments so the inner loop stays vectorised.
            gamma = 1.0 if objective == "log_growth" else risk_aversion
            score = (portfolio_means - 0.5 * gamma * variances) * 252.0
        chosen[sample] = float(weights[int(np.nanargmax(score))])
    return pd.Series(chosen, name=f"bootstrap_optimal_{objective}")
