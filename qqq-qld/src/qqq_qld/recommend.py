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

``risk_aversion`` -- a preference, not a fact. The default is 2 (half-Kelly).
Full Kelly is log utility, which on this data selects allocations whose
historical drawdowns approach total loss; a rule that would have required
holding through -98% is not a rule anyone follows. Two is also the standard
practitioner response to exactly the estimation error in ``mu`` described
above.

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
    "risk_aversion": 2.0,
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
