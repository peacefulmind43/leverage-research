"""The repository's own leverage recommendation, and what it rests on.

Every other module in this package computes something. This one takes a
position, which is a different kind of claim and is kept separate for that
reason: the machinery elsewhere is reusable under any assumptions, whereas
what follows is only as good as four numbers, three of which are stated here
rather than measured.

The recommendation is the CRRA/Merton optimum,

    L* = (mu_arith - c) / (gamma * sigma^2)

evaluated at :data:`HOUSE_VIEW`, then clipped to the exposure a long-only
QQQ/QLD portfolio can actually reach. Its inputs, in descending order of how
well they are known:

``sigma2`` -- measured, and the most trustworthy input. Taken from the
reconstructed 1985-2026 history rather than QLD's live window, because a
variance estimate that excludes 2000-2002 understates the term that penalises
leverage. This single choice moves the answer by about 0.7x.

``financing_cost`` -- measured, from the funds' own returns (see
:mod:`qqq_qld.costs`), plus a current benchmark rate. Knowable today, but it
is a *spot* rate: a multi-decade holder pays the average future short rate,
not this one.

``mu_geometric`` -- assumed, and by far the weakest input. The trailing figure
is 15.4% geometric over forty years, which is the realised return of the
best-performing major index selected in hindsight, not a forecast. The default
below is well under that and still above broad-market capital-market
assumptions, on the view that the Nasdaq-100's growth tilt earns something but
not the full historical premium from today's valuations.

``risk_aversion`` -- a preference, not a fact, and the default is 1.

One is log utility, i.e. full Kelly, and it is the right default for the
question "what maximises money", because Kelly's claim is not a preference: a
log-wealth maximiser's terminal wealth almost surely exceeds that of any
essentially different strategy as the horizon grows, and Kelly also maximises
median terminal wealth. Note that true risk *neutrality* is ``gamma = 0``,
which prescribes unbounded leverage and certain ruin -- so "only cares about
money" cannot mean maximising expected wealth. It has to mean maximising the
growth rate of wealth, and that is exactly ``gamma = 1``.

Values above 1 encode an unwillingness to hold the path, which is a real
consideration but a separate one: at ``gamma = 2`` this data selects an
unconstrained exposure well below 1x, so the recommendation becomes a boundary
rather than an interior solution. :func:`optimal_leverage` reports ``binding``
so the two cases are never confused.

Estimation error in ``mu`` is sometimes offered as a reason to raise gamma.
It is not a good one: expected log growth is *linear* in mu, so uncertainty
about mu leaves the optimum at ``E[mu]`` and does not by itself justify a
haircut. What does move the answer is being wrong about ``E[mu]`` itself,
which is why :func:`required_return` exists.

:func:`required_return` inverts the formula, which is the more useful direction
in practice: rather than arguing about the recommendation, it states what you
would have to believe about forward returns for any given leverage to be
optimal, and lets the reader check whether they believe it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Assumptions behind the recommendation. Every one is meant to be overridden
#: by a reader with a different view; the point of the module is that changing
#: them changes the number in a traceable way.
HOUSE_VIEW: dict[str, float] = {
    "mu_geometric": 0.09,
    "risk_aversion": 1.0,
}

#: A long-only QQQ/QLD portfolio can only reach exposures in this range.
MIN_LEVERAGE = 1.0
MAX_LEVERAGE = 2.0


def optimal_leverage(
    sigma2: float,
    financing_cost: float,
    mu_geometric: float = HOUSE_VIEW["mu_geometric"],
    risk_aversion: float = HOUSE_VIEW["risk_aversion"],
    min_leverage: float = MIN_LEVERAGE,
    max_leverage: float = MAX_LEVERAGE,
) -> dict[str, float]:
    """Growth-optimal leverage under CRRA utility, before and after clipping.

    ``mu_geometric`` is an annualised (compound) return, the convention
    capital-market assumptions publish; it is converted to the arithmetic mean
    the formula requires by adding ``0.5*sigma^2``.

    Both the unclipped and clipped figures are returned. When the unclipped
    optimum falls below ``min_leverage`` the recommendation is a *boundary*
    solution, which means something specific: the model is not saying "hold 1x",
    it is saying the constraint is binding and an unconstrained investor would
    hold less of this asset than their whole portfolio. ``binding`` records that,
    because a boundary answer and an interior answer of the same value warrant
    different conclusions.
    """
    if sigma2 <= 0:
        raise ValueError("sigma2 must be positive")
    if risk_aversion <= 0:
        raise ValueError("risk_aversion must be positive")
    mu_arithmetic = mu_geometric + 0.5 * sigma2
    unconstrained = (mu_arithmetic - financing_cost) / (risk_aversion * sigma2)
    clipped = float(np.clip(unconstrained, min_leverage, max_leverage))
    return {
        "mu_geometric": mu_geometric,
        "mu_arithmetic": mu_arithmetic,
        "financing_cost": financing_cost,
        "excess_over_financing": mu_arithmetic - financing_cost,
        "sigma2": sigma2,
        "volatility": float(np.sqrt(sigma2)),
        "risk_aversion": risk_aversion,
        "unconstrained_leverage": unconstrained,
        "recommended_leverage": clipped,
        "recommended_qld_weight": clipped - 1.0,
        "binding": bool(unconstrained < min_leverage or unconstrained > max_leverage),
    }


def required_return(
    leverage: float,
    sigma2: float,
    financing_cost: float,
    risk_aversion: float = HOUSE_VIEW["risk_aversion"],
) -> float:
    """The geometric forward return that would make ``leverage`` optimal.

    The inverse of :func:`optimal_leverage`, and the honest way to present a
    recommendation whose dominant input cannot be estimated: instead of
    asserting a forward return, state the one each leverage level implies and
    let the reader decide whether it is credible.
    """
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    return risk_aversion * leverage * sigma2 + financing_cost - 0.5 * sigma2


def breakeven_table(
    sigma2: float,
    financing_cost: float,
    leverages: tuple[float, ...] = (1.00, 1.15, 1.30, 1.50, 2.00),
    risk_aversions: tuple[float, ...] = (1.0, 1.5, 2.0),
) -> pd.DataFrame:
    """Required forward return for each leverage level, across risk aversions.

    Read a row as a conditional claim: this leverage is optimal *if* forward
    geometric returns are at least this, and the columns show how much that
    threshold moves with a preference rather than with any fact about markets.
    """
    rows = []
    for leverage in leverages:
        row: dict[str, float] = {"leverage": leverage, "qld_weight": leverage - 1.0}
        for gamma in risk_aversions:
            row[f"required_mu_gamma_{gamma:g}"] = required_return(
                leverage, sigma2, financing_cost, gamma
            )
        rows.append(row)
    return pd.DataFrame(rows).set_index("leverage")


def empirical_optimal_leverage(
    returns: pd.Series,
    financing_cost: float,
    mu_geometric: float | None = None,
    grid: np.ndarray | None = None,
) -> dict[str, float]:
    """Growth-optimal leverage measured on the realised path, not approximated.

    The closed form in :func:`optimal_leverage` assumes lognormal returns. Real
    daily returns are strongly leptokurtic -- excess kurtosis around 8 on this
    sample -- and the Gaussian approximation therefore *understates* how much a
    levered position loses to variance. This function instead compounds a
    daily-rebalanced ``L``x position through the actual return sequence, so fat
    tails, volatility clustering and path dependence are handled exactly rather
    than assumed away.

    ``mu_geometric`` rescales the series so its annualised compound return
    equals the supplied forward assumption while leaving every higher moment
    intact. This separates the two things a backtest conflates: the realised
    *shape* of returns, which is informative about risk, from the realised
    *level*, which is a hindsight-selected sample mean and is not a forecast.

    The correction is modest at low leverage and grows with it, which is the
    expected sign: tails matter more the more they are multiplied.
    """
    clean = returns.dropna()
    log_returns = np.log1p(clean.to_numpy())
    if mu_geometric is not None:
        log_returns = log_returns - log_returns.mean() + np.log1p(mu_geometric) / 252
    daily_cost = financing_cost / 252
    simple = np.expm1(log_returns)
    if grid is None:
        grid = np.arange(0.0, 2.51, 0.01)
    growth = np.full(len(grid), -np.inf)
    for position, leverage in enumerate(grid):
        levered = leverage * simple - (leverage - 1.0) * daily_cost
        if (levered > -1.0).all():
            growth[position] = float(np.log1p(levered).mean() * 252)
    best = int(np.argmax(growth))
    return {
        "empirical_leverage": float(grid[best]),
        "log_growth": float(growth[best]),
        "mu_geometric": float(np.expm1(log_returns.mean() * 252)),
        "excess_kurtosis": float(pd.Series(simple).kurt()),
    }


def horizon_optimal_leverage(
    returns: pd.Series,
    financing_cost: float,
    mu_geometric: float | None = None,
    years: int = 30,
    samples: int = 2000,
    block_days: int = 63,
    seed: int = 42,
    grid: np.ndarray | None = None,
) -> pd.DataFrame:
    """Leverage that maximises *median* terminal wealth over a finite horizon.

    Kelly's dominance is asymptotic, and no one holds an asset forever. This
    block-bootstraps horizons of ``years`` from the realised series -- blocks
    rather than independent draws, so volatility clustering survives resampling
    -- and reports the wealth distribution at each leverage.

    Median, not mean: mean terminal wealth is maximised by ever more leverage
    because a thin right tail carries it, which is exactly the statistic that
    makes leverage look better than it is. The median is what a single investor
    living one path should care about, and it is the statistic Kelly maximises.
    """
    clean = returns.dropna().to_numpy()
    log_returns = np.log1p(clean)
    if mu_geometric is not None:
        log_returns = log_returns - log_returns.mean() + np.log1p(mu_geometric) / 252
    simple = np.expm1(log_returns)

    rng = np.random.default_rng(seed)
    horizon = years * 252
    blocks = horizon // block_days + 1
    starts = rng.integers(0, len(simple) - block_days, size=(samples, blocks))
    index = (starts[:, :, None] + np.arange(block_days)).reshape(samples, -1)[:, :horizon]
    paths = simple[index]

    daily_cost = financing_cost / 252
    if grid is None:
        grid = np.arange(0.8, 2.01, 0.05)
    # Rounded so the returned index holds exact values like 1.0 rather than
    # 0.9999999999, which makes .loc lookups on it fail.
    grid = np.round(grid, 6)

    # Same resampled paths for every leverage, so differences across rows are
    # the leverage and not the draw.
    baseline = np.exp(np.log1p(paths).sum(axis=1))
    rows = []
    for leverage in grid:
        levered = leverage * paths - (leverage - 1.0) * daily_cost
        wealth = np.exp(np.log1p(np.maximum(levered, -0.999)).sum(axis=1))
        rows.append(
            {
                "leverage": float(leverage),
                "median_multiple": float(np.median(wealth)),
                "mean_multiple": float(wealth.mean()),
                "p5_multiple": float(np.percentile(wealth, 5)),
                "p95_multiple": float(np.percentile(wealth, 95)),
                # Per-path comparison against holding 1x on the *same* draw. A
                # leverage can raise median wealth while still losing to 1x on
                # most individual paths, and that is worth seeing.
                "prob_beats_unlevered": float((wealth > baseline).mean()),
            }
        )
    return pd.DataFrame(rows).set_index("leverage")
