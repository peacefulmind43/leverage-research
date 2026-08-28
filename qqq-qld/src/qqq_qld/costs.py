"""Empirical estimation of QLD's embedded cost of leverage.

A QQQ/QLD blend is a way of *borrowing*. The blend's target exposure ``1 + w``
is achievable three other ways -- broker margin, index futures, or a box-spread
loan -- and choosing between them is a comparison of borrowing costs, not of
strategies. That comparison needs a number this repository did not previously
produce: the interest rate QLD effectively charges.

This module recovers it from the funds' own return histories rather than
assuming it, and expresses it as a rate directly comparable to a broker's
quoted margin rate.

Two results make the comparison tractable.

**The fee premium is a closed form, invariant to leverage.** Holding weight
``w`` in QLD and ``1-w`` in QQQ borrows ``w`` and pays a weighted expense ratio
of ``(1-w)*ER_QQQ + w*ER_QLD``. Holding ``1+w`` leverage on margin borrows the
same ``w`` and pays ``(1+w)*ER_QQQ``. Setting the two total costs equal and
dividing through by ``w`` gives

    c_margin = c_swap + (ER_QLD - 2*ER_QQQ)

The ``w`` cancels: the fee penalty per dollar borrowed is the same whether the
blend is 90/10 or 0/100. With the current published expense ratios this premium
is 0.95% - 2*0.20% = 0.55% per year, and :data:`BLEND_FEE_PREMIUM` records it.

**The financing rate itself is identified by a regression.** QLD targets exactly
2x QQQ's *index* daily, so its observed return satisfies

    r_QLD = 2*r_QQQ + (2*ER_QQQ - ER_QLD - financing)

because the ``2*r_QQQ`` term double-counts QQQ's own expense ratio, which QLD
does not pay. Everything except ``financing`` is published, so subtracting a
contemporaneous risk-free rate from the residual leaves the spread QLD's swap
counterparties charge over that benchmark. :func:`implied_financing` does this.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import TRADING_DAYS

#: Published net expense ratios. Override if the funds change them.
EXPENSE_RATIO_QQQ = 0.0020
EXPENSE_RATIO_QLD = 0.0095

#: Extra cost per dollar borrowed of borrowing via a QQQ/QLD blend rather than
#: on margin, from fund fees alone. Invariant to the blend weight -- see module
#: docstring. Add it to the swap spread to compare against a broker's rate.
BLEND_FEE_PREMIUM = EXPENSE_RATIO_QLD - 2.0 * EXPENSE_RATIO_QQQ


def implied_financing(
    returns: pd.DataFrame,
    risk_free: pd.Series | float = 0.0,
    expense_ratio_qqq: float = EXPENSE_RATIO_QQQ,
    expense_ratio_qld: float = EXPENSE_RATIO_QLD,
    target_beta: float = 2.0,
) -> dict[str, float]:
    """Recover the financing rate embedded in QLD from realised returns.

    ``risk_free`` is an annualised rate, either a constant or a daily series
    aligned to ``returns`` (a contemporaneous series is strongly preferred: the
    benchmark rate moved from roughly 5% to zero and back within this sample,
    and a constant would push all of that variation into the estimated spread).

    ``target_beta`` is fixed at 2.0 rather than estimated because QLD's
    prospectus *defines* its daily objective as 2x. Estimating the slope instead
    lets tracking noise leak into the intercept, which is the quantity of
    interest here; :func:`tracking_regression` reports the free-slope fit
    separately as a diagnostic.

    Returns the annualised drag versus 2x QQQ (``alpha``), the implied all-in
    financing rate, and the implied ``spread`` over the supplied benchmark.
    """
    for column in ("QQQ", "QLD"):
        if column not in returns.columns:
            raise ValueError(f"{column!r} not found in returns columns")
    frame = returns[["QQQ", "QLD"]].dropna()
    if frame.empty:
        raise ValueError("returns cannot be empty")

    if isinstance(risk_free, pd.Series):
        rf = risk_free.reindex(frame.index).ffill()
        if rf.isna().any():
            raise ValueError("risk_free has no value at or before the first return date")
    else:
        rf = pd.Series(float(risk_free), index=frame.index)

    alpha = float((frame["QLD"] - target_beta * frame["QQQ"]).mean() * TRADING_DAYS)
    borrowed = target_beta - 1.0
    # alpha = target_beta*ER_QQQ - ER_QLD - borrowed*financing, solved for financing.
    fee_offset = target_beta * expense_ratio_qqq - expense_ratio_qld
    financing = (fee_offset - alpha) / borrowed
    return {
        "alpha": alpha,
        "mean_risk_free": float(rf.mean()),
        "implied_financing_rate": financing,
        "implied_spread": financing - float(rf.mean()),
        "years": len(frame) / TRADING_DAYS,
    }


def implied_financing_by_period(
    returns: pd.DataFrame,
    risk_free: pd.Series | float = 0.0,
    freq: str = "5YE",
    **kwargs,
) -> pd.DataFrame:
    """Re-estimate :func:`implied_financing` within non-overlapping windows.

    The spread is not a constant of nature: it reflects what QLD's swap
    counterparties charged at the time, and it widens when funding markets are
    stressed. Reporting a single full-sample number hides that. Any window whose
    estimate is far from the others deserves a look at what was happening to
    funding markets then -- and, for windows after this repository's data splice
    date, at whether missing fund distributions are inflating it.
    """
    frame = returns[["QQQ", "QLD"]].dropna()
    rows: list[dict[str, float | str]] = []
    for label, chunk in frame.groupby(pd.Grouper(freq=freq)):
        if len(chunk) < TRADING_DAYS:
            continue
        rf = risk_free.reindex(chunk.index) if isinstance(risk_free, pd.Series) else risk_free
        estimate = implied_financing(chunk, rf, **kwargs)
        rows.append(
            {
                "period_end": str(label.date()),
                "start": str(chunk.index.min().date()),
                "end": str(chunk.index.max().date()),
                **estimate,
            }
        )
    return pd.DataFrame(rows).set_index("period_end")


def tracking_regression(returns: pd.DataFrame) -> dict[str, float]:
    """Free-slope OLS of QLD on QQQ, as a check that QLD tracks its 2x objective.

    A slope materially away from 2.0 means the fixed-beta assumption in
    :func:`implied_financing` is contaminating that estimate, and the financing
    number should be treated as unreliable rather than merely noisy.
    """
    frame = returns[["QQQ", "QLD"]].dropna()
    slope, intercept = np.polyfit(frame["QQQ"].to_numpy(), frame["QLD"].to_numpy(), 1)
    residual = frame["QLD"] - (slope * frame["QQQ"] + intercept)
    return {
        "beta": float(slope),
        "alpha": float(intercept * TRADING_DAYS),
        "r_squared": float(1.0 - residual.var(ddof=1) / frame["QLD"].var(ddof=1)),
        "tracking_error": float(residual.std(ddof=1) * np.sqrt(TRADING_DAYS)),
    }


def effective_borrow_rate(
    benchmark_rate: float,
    swap_spread: float,
    expense_ratio_qqq: float = EXPENSE_RATIO_QQQ,
    expense_ratio_qld: float = EXPENSE_RATIO_QLD,
) -> dict[str, float]:
    """QLD's all-in cost per dollar borrowed, as a rate comparable to margin.

    The returned ``effective_rate`` is the margin rate at which borrowing from a
    broker and holding the blend cost exactly the same, so it can be compared
    directly against a broker's quoted rate to decide between them. It is
    invariant to how much leverage is being taken.
    """
    fee_premium = expense_ratio_qld - 2.0 * expense_ratio_qqq
    financing = benchmark_rate + swap_spread
    return {
        "benchmark_rate": benchmark_rate,
        "swap_spread": swap_spread,
        "financing_rate": financing,
        "fee_premium": fee_premium,
        "effective_rate": financing + fee_premium,
    }


def blend_cost_at_weight(
    weight_qld: float,
    benchmark_rate: float,
    swap_spread: float,
    expense_ratio_qqq: float = EXPENSE_RATIO_QQQ,
    expense_ratio_qld: float = EXPENSE_RATIO_QLD,
) -> float:
    """Total annual cost drag of a blend at ``weight_qld``, as a fraction of NAV.

    Unlike :func:`effective_borrow_rate` this is *not* invariant to weight: it is
    the rate per dollar borrowed multiplied by the amount borrowed, plus the
    unlevered expense ratio that is paid either way.
    """
    financing = benchmark_rate + swap_spread
    fees = (1.0 - weight_qld) * expense_ratio_qqq + weight_qld * expense_ratio_qld
    return weight_qld * financing + fees
