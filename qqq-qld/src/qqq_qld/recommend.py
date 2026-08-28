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

``sigma2`` -- measured, but the choice of *window* is a judgement. The full
reconstructed 1985-2026 sample gives 25.67%, and that figure is carried almost
entirely by 1995-2002, which realised 38.9%; every other era in the sample sits
between 18.8% and 22.6%, and the post-2003 index has run 22.3% through the GFC,
COVID and 2022. Using 25.67% as a forward constant assumes a bubble-era regime
recurs at the same frequency in a structurally different, mega-cap-dominated
index. The default splits the difference. Excluding 2000-2002 entirely remains
the larger error in the other direction.

``financing_cost`` -- measured, from the funds' own returns (see
:mod:`qqq_qld.costs`), plus a benchmark rate. Note this should be the *average
future* short rate over the holding period, not today's spot: the 41-year mean
of the 3-month bill is 3.22% against 3.70% spot, and using spot for a
multi-decade decision quietly costs about 0.07x of leverage.

**A warning about how these are chosen.** Each input above has a defensible
conservative value and a defensible central one. Taking the conservative end of
all of them at once does not produce a conservative answer -- it produces an
answer at the corner of the plausible region, and misrepresents it as the
centre. An earlier version of this module did exactly that, stacking
full-sample volatility, a spot financing rate and a low return assumption, and
reported 1.00x when the defensible range ran from 1.04x to 1.92x.
:func:`sensitivity_box` exists so the corner is always visible next to the
point estimate.

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
    "mu_geometric": 0.095,
    "risk_aversion": 1.0,
    "volatility": 0.235,
    "benchmark_rate": 0.033,
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


def _rescaled_log_returns(
    returns: pd.Series,
    mu_geometric: float | None,
    volatility: float | None,
) -> np.ndarray:
    """Log returns retargeted to a forward mean and/or volatility.

    Separates the realised *shape* of returns -- skew, kurtosis, volatility
    clustering, which is what the sample is genuinely informative about -- from
    its realised *level and scale*, which are a hindsight-selected sample
    statistic and a regime-dependent one respectively. Standardising and
    rescaling preserves every standardised higher moment, so the fat tails
    survive the substitution.
    """
    log_returns = np.log1p(returns.dropna().to_numpy())
    if volatility is not None:
        centred = log_returns - log_returns.mean()
        log_returns = centred / centred.std(ddof=1) * (volatility / np.sqrt(252))
    if mu_geometric is not None:
        log_returns = log_returns - log_returns.mean() + np.log1p(mu_geometric) / 252
    return log_returns


def empirical_optimal_leverage(
    returns: pd.Series,
    financing_cost: float,
    mu_geometric: float | None = None,
    volatility: float | None = None,
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
    log_returns = _rescaled_log_returns(returns, mu_geometric, volatility)
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
    volatility: float | None = None,
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
    simple = np.expm1(_rescaled_log_returns(returns, mu_geometric, volatility))

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
    table = pd.DataFrame(rows).set_index("leverage")
    table.attrs["years"] = years
    return table


def sensitivity_box(
    mu_geometric: tuple[float, ...] = (0.08, 0.09, 0.095, 0.10, 0.12),
    volatility: tuple[float, ...] = (0.223, 0.235, 0.2567),
    financing_cost: tuple[float, ...] = (0.0493, 0.0501, 0.0541),
    risk_aversion: float = 1.0,
) -> pd.DataFrame:
    """Growth-optimal leverage across the whole plausible input region.

    Published next to the point estimate on purpose. A single number invites
    the reader to argue about it; this shows that the recommendation moves from
    roughly 1x to roughly 2x inside a set of assumptions that are all
    defensible, which locates the real disagreement in the inputs rather than
    in the method.

    It is also the guard against stacking conservatism: the minimum cell is a
    corner, not a cautious central estimate, and reporting a corner as if it
    were the centre is a specific error this module has made before.
    """
    rows = []
    for sigma in volatility:
        sigma2 = sigma**2
        for cost in financing_cost:
            for mu in mu_geometric:
                rows.append(
                    {
                        "volatility": sigma,
                        "financing_cost": cost,
                        "mu_geometric": mu,
                        "leverage": (mu + 0.5 * sigma2 - cost) / (risk_aversion * sigma2),
                    }
                )
    return pd.DataFrame(rows)


def flatness(horizon_table: pd.DataFrame, baseline: float = 1.0) -> pd.DataFrame:
    """What leverage actually buys, in annualised median terms, against 1x.

    The most decision-relevant fact about a Kelly curve is that it is flat near
    its maximum, and a leverage figure quoted on its own hides that. Moving from
    1x to the optimum can raise median terminal wealth by an amount that
    annualises to almost nothing while materially thinning the left tail -- in
    which case the point estimate is technically right and practically
    uninteresting.

    ``median_cagr_gain`` is the annualised difference in median terminal wealth
    against ``baseline``; ``p5_ratio`` is what happens to the 5th percentile
    over the same comparison.
    """
    if baseline not in horizon_table.index:
        raise ValueError(f"baseline {baseline} not in the horizon table index")
    years = horizon_table.attrs.get("years")
    if years is None:
        raise ValueError("horizon_table must carry an attrs['years'] annualisation basis")
    base = horizon_table.loc[baseline]
    out = pd.DataFrame(index=horizon_table.index)
    out["median_multiple"] = horizon_table["median_multiple"]
    out["median_cagr_gain"] = (
        horizon_table["median_multiple"] / base["median_multiple"]
    ) ** (1.0 / years) - 1.0
    out["p5_multiple"] = horizon_table["p5_multiple"]
    out["p5_ratio"] = horizon_table["p5_multiple"] / base["p5_multiple"]
    return out


def horizon_stability(
    returns: pd.Series,
    financing_cost: float,
    mu_geometric: float | None = None,
    volatility: float | None = None,
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4, 5),
    **kwargs,
) -> dict[str, float]:
    """Sampling noise in the bootstrap's optimal leverage, across seeds.

    The bootstrap is the most realistic of the three estimators and the least
    precise, and those facts are easy to confuse. Its argmax moves by a few
    hundredths from one resampling seed to the next, so it cannot support a
    two-decimal headline no matter how many decimals it prints. This measures
    that spread explicitly, so the figure is quoted as the interval it is.

    The deterministic full-path estimator, :func:`empirical_optimal_leverage`,
    is the one that can carry a point estimate: it uses the entire realised
    sequence rather than resampling from it.
    """
    picks = []
    for seed in seeds:
        table = horizon_optimal_leverage(
            returns,
            financing_cost,
            mu_geometric=mu_geometric,
            volatility=volatility,
            seed=seed,
            **kwargs,
        )
        picks.append(float(table["median_multiple"].idxmax()))
    values = np.asarray(picks)
    return {
        "median": float(np.median(values)),
        "minimum": float(values.min()),
        "maximum": float(values.max()),
        "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        "seeds": len(values),
    }


def credible_range(
    box: pd.DataFrame | None = None,
    point_estimate: float | None = None,
) -> dict[str, float]:
    """The interval the inputs actually support, and where a point sits in it.

    This is the honest headline, and a point estimate is not. The recommendation
    is a deterministic function of four inputs, one of which -- the forward
    return -- cannot be estimated from any amount of history. Across values of
    those inputs that are all individually defensible the answer spans more than
    a factor of two, so quoting the centre of that range without the range
    overstates what the analysis knows by a wide margin.

    ``percentile_of_point`` guards specifically against over-correction: after
    an input choice is revised, it says whether the new figure is central or has
    merely moved to the opposite corner. A revision that lands near 50 is a
    recentring; one that lands near 0 or 100 has replaced one extreme with
    another.
    """
    if box is None:
        box = sensitivity_box()
    values = box["leverage"].to_numpy()
    result = {
        "minimum": float(values.min()),
        "median": float(np.median(values)),
        "maximum": float(values.max()),
        "ratio_max_to_min": float(values.max() / values.min()),
        "cells": int(values.size),
    }
    if point_estimate is not None:
        result["point_estimate"] = float(point_estimate)
        result["percentile_of_point"] = float(100.0 * np.mean(values < point_estimate))
    return result


def input_sensitivity(
    returns: pd.Series,
    financing_cost: float,
    mu_geometric: float,
    volatility: float,
    bump: float = 0.001,
    grid: np.ndarray | None = None,
) -> pd.DataFrame:
    """How far the optimum moves per unit change in each input.

    The point of this is to establish the *accuracy* of a leverage figure, which
    is a different question from its precision. A grid search reports as many
    decimals as it is asked for, and those digits are reproducible; whether they
    mean anything depends on how tightly the inputs are known.

    A decimal place of leverage is only informative if the inputs are known to
    better than the bump that moves the answer by that much. Here a tenth of a
    percentage point on the forward return -- an order of magnitude finer than
    anyone can forecast it -- moves the optimum by more than a hundredth of a
    turn, which is what makes a third decimal place noise.

    Note the return and the financing cost have *equal and opposite* derivatives,
    both ``1 / sigma^2``, since the optimum depends only on the spread between
    them. The return dominates the uncertainty not because the answer is more
    sensitive to it but because it is known far less precisely: the financing
    rate is measurable to a few tenths of a percentage point, while the forward
    return is not pinned to within several. Comparing raw sensitivities rather
    than sensitivity times uncertainty gets this backwards.
    """
    if grid is None:
        grid = np.arange(0.5, 2.51, 0.001)
    base = empirical_optimal_leverage(
        returns, financing_cost, mu_geometric, volatility=volatility, grid=grid
    )["empirical_leverage"]
    rows = []
    for name, kwargs in (
        ("mu_geometric", {"mu_geometric": mu_geometric + bump}),
        ("volatility", {"volatility": volatility + bump}),
        ("financing_cost", {"financing_cost": financing_cost + bump}),
    ):
        arguments = {
            "mu_geometric": mu_geometric,
            "volatility": volatility,
            "financing_cost": financing_cost,
        }
        arguments.update(kwargs)
        bumped = empirical_optimal_leverage(
            returns,
            arguments["financing_cost"],
            arguments["mu_geometric"],
            volatility=arguments["volatility"],
            grid=grid,
        )["empirical_leverage"]
        rows.append(
            {
                "input": name,
                "bump": bump,
                "leverage": bumped,
                "change": bumped - base,
                "leverage_per_unit": (bumped - base) / bump,
            }
        )
    table = pd.DataFrame(rows).set_index("input")
    table.attrs["base_leverage"] = base
    return table


def exposure_drift(
    returns: pd.DataFrame,
    weight_qld: float,
    rebalance: str = "ME",
) -> dict[str, float]:
    """How far realised exposure wanders from its target between rebalances.

    Sets an upper bound on the precision worth quoting, independent of any
    estimation question: a target that cannot be held to a given number of
    decimals cannot be acted on to that many either. Between monthly
    rebalances the two legs compound at different rates, so realised exposure
    occupies a band around ``1 + weight_qld`` rather than sitting on it.
    """
    from .backtest import _rebalance_flags

    frame = returns[["QQQ", "QLD"]].dropna()
    target = np.array([1.0 - weight_qld, weight_qld])
    flags = _rebalance_flags(frame.index, rebalance)
    values = target.copy()
    realised = np.empty(len(frame))
    for position, row in enumerate(frame.to_numpy()):
        if flags[position] and position > 0:
            values = values.sum() * target
        values = values * (1.0 + row)
        realised[position] = 1.0 + values[1] / values.sum()
    return {
        "target_exposure": 1.0 + weight_qld,
        "minimum": float(realised.min()),
        "maximum": float(realised.max()),
        "std": float(realised.std(ddof=1)),
        "typical_band": float(2.0 * realised.std(ddof=1)),
    }


def optimal_band(
    returns: pd.DataFrame,
    weight_qld: float,
    sigma2: float,
    bands: tuple[float, ...] = (0.0, 0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.08, 0.12, 0.20, 0.30),
    transaction_cost_bps: float = 2.0,
    tax_rate: float = 0.0,
    embedded_gain_fraction: float = 0.0,
) -> pd.DataFrame:
    """No-trade band width that minimises the total cost of holding a target.

    Two costs move in opposite directions with the band, and both are small
    enough that the comparison has to be done in the same units rather than
    argued about. Trading cost falls roughly with the reciprocal of the band,
    because annual turnover does. Drift cost rises with its square: the growth
    penalty for sitting at leverage ``L`` instead of the optimum is
    ``0.5*sigma^2*(L-L*)^2``, which is second order and therefore very forgiving
    of small deviations.

    That asymmetry -- first-order trading cost against second-order drift cost --
    is why the answer is a band and not a date, and why the band widens sharply
    once trading carries tax. In a sheltered account the whole curve is a
    rounding error and the minimum is shallow; in a taxable one the tax term
    dominates every other consideration by an order of magnitude.

    **Growth is deliberately not the objective here.** Backtested growth by band
    is confounded: a wider band lets exposure drift up in a rising market, and on
    a sample whose realised return exceeded the assumed forward return that
    drift is rewarded, making wide bands look good for reasons that have nothing
    to do with rebalancing. Shuffling the return sequence removes most of the
    apparent advantage, which identifies it as momentum in the realised path
    rather than a property of the policy. Cost minimisation is not exposed to
    that confound.
    """
    from .backtest import threshold_backtest

    target = np.array([1.0 - weight_qld, weight_qld])
    asset_returns = returns[["QQQ", "QLD"]].dropna().to_numpy(dtype=float)
    rows = []
    for band in bands:
        _, stats = threshold_backtest(
            returns,
            weight_qld,
            band,
            transaction_cost_bps=transaction_cost_bps,
            tax_rate=tax_rate,
            embedded_gain_fraction=embedded_gain_fraction,
        )
        values = target.copy()
        squared = np.empty(len(asset_returns))
        for position, row in enumerate(asset_returns):
            total = values.sum()
            if position > 0 and abs(values[1] / total - weight_qld) > band:
                values = target * total
            values = values * (1.0 + row)
            squared[position] = (values[1] / values.sum() - weight_qld) ** 2
        drift = 0.5 * sigma2 * float(squared.mean())
        rows.append(
            {
                "band": band,
                "exposure_low": 1.0 + weight_qld - band,
                "exposure_high": 1.0 + weight_qld + band,
                "trades_per_year": stats["trades_per_year"],
                "trading_cost": stats["annual_cost"],
                "drift_cost": drift,
                "total_cost": stats["annual_cost"] + drift,
            }
        )
    return pd.DataFrame(rows).set_index("band")
