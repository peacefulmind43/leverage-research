"""Idealized daily-reset leverage benchmark and rebalancing-drag diagnostics.

Quantifies the gap between a periodically rebalanced QQQ/QLD blend (the real,
tradable strategy simulated in ``backtest.py``, using QLD's actual fund returns)
and a hypothetical, frictionless (by default) daily-reset leveraged product at
the same target exposure. Two distinct effects open this gap, and it is easy to
conflate them:

1. **QLD's own real costs.** QLD's real daily return is only *approximately*
   2x QQQ's -- it embeds QLD's own expense ratio and daily financing spread on
   its leveraged notional. ``simulate_daily_reset_leverage`` defaults those
   costs to zero, so comparing real QLD-based returns against that frictionless
   default carries a persistent gap proportional to QLD weight, present at
   *any* rebalancing cadence, including daily.
2. **Rebalancing cadence.** Independent of (1), a blend that rebalances less
   often than daily lets the QQQ/QLD weight drift between rebalance dates,
   adding a further, typically much smaller, path-dependent gap on top.

``compare_rebalance_frequencies`` isolates (2): its ``D`` (daily) row still
carries the full effect of (1), so read the *change* across rows, not the
absolute level, as the cadence effect. See docs/methodology.md section 6.1.
"""

from __future__ import annotations

import pandas as pd

from .backtest import portfolio_returns
from .metrics import TRADING_DAYS, performance_metrics


def simulate_daily_reset_leverage(
    daily_returns: pd.Series,
    leverage: float,
    expense_ratio: float = 0.0,
    financing_spread: float = 0.0,
    annual_risk_free_rate: float = 0.0,
) -> pd.Series:
    """Simulate a frictionless (by default) daily-reset ``leverage``x product.

    ``daily_returns`` is the unleveraged underlying's daily simple return series.
    Financing is charged only on the borrowed fraction (``leverage - 1``) at
    ``annual_risk_free_rate + financing_spread``; fund expenses accrue daily at
    ``expense_ratio / 252``. Both default to zero, giving a pure closed-form
    check of ``leverage * daily_returns`` against docs/methodology.md section 6's
    ``g_L`` formula.
    """
    if leverage < 0:
        raise ValueError("leverage must be non-negative")
    clean = daily_returns.dropna()
    borrow_fraction = max(leverage - 1.0, 0.0)
    daily_financing = borrow_fraction * (annual_risk_free_rate + financing_spread) / TRADING_DAYS
    daily_expense = expense_ratio / TRADING_DAYS
    return leverage * clean - daily_financing - daily_expense


def rebalance_drag(
    returns: pd.DataFrame,
    weight_qld: float,
    rebalance: str,
    transaction_cost_bps: float = 0.0,
    annual_risk_free_rate: float = 0.0,
    asset: str = "QQQ",
) -> dict[str, float | str]:
    """Compare an actual QQQ/QLD blend to the idealized synthetic exposure it targets.

    The blend's target exposure is ``1 + weight_qld``. ``cagr_gap`` and
    ``return_correlation`` report the resulting divergence, but do not attribute
    it to rebalancing cadence alone: the frictionless-by-default synthetic omits
    QLD's own real expense ratio and financing spread, so a gap persists even at
    daily cadence, proportional to ``weight_qld``. Use
    :func:`compare_rebalance_frequencies` to see the incremental cadence effect
    on top of that baseline. See docs/methodology.md section 6.1.
    """
    target_leverage = 1.0 + weight_qld
    synthetic = simulate_daily_reset_leverage(returns[asset], target_leverage)
    actual = portfolio_returns(
        returns,
        weight_qld=weight_qld,
        rebalance=rebalance,
        transaction_cost_bps=transaction_cost_bps,
    )
    synthetic, actual = synthetic.align(actual, join="inner")
    synthetic_metrics = performance_metrics(synthetic, annual_risk_free_rate)
    actual_metrics = performance_metrics(actual, annual_risk_free_rate)
    return {
        "target_leverage": target_leverage,
        "rebalance": rebalance,
        "synthetic_cagr": synthetic_metrics["cagr"],
        "actual_cagr": actual_metrics["cagr"],
        "cagr_gap": actual_metrics["cagr"] - synthetic_metrics["cagr"],
        "synthetic_volatility": synthetic_metrics["volatility"],
        "actual_volatility": actual_metrics["volatility"],
        "return_correlation": float(synthetic.corr(actual)),
    }


def compare_rebalance_frequencies(
    returns: pd.DataFrame,
    weight_qld: float,
    frequencies: tuple[str, ...] = ("D", "W", "ME", "QE"),
    transaction_cost_bps: float = 0.0,
    annual_risk_free_rate: float = 0.0,
    asset: str = "QQQ",
) -> pd.DataFrame:
    """Show how rebalancing cadence changes the achieved result for a fixed target weight.

    Every row still carries QLD's real cost drag versus the frictionless synthetic
    (see module docstring); compare rows to each other, not to zero, to read off
    the cadence effect alone.
    """
    rows = [
        rebalance_drag(
            returns,
            weight_qld,
            rebalance=frequency,
            transaction_cost_bps=transaction_cost_bps,
            annual_risk_free_rate=annual_risk_free_rate,
            asset=asset,
        )
        for frequency in frequencies
    ]
    return pd.DataFrame(rows).set_index("rebalance")
