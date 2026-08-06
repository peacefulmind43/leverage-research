"""Idealized daily-reset leverage benchmark and rebalancing-drag diagnostics.

Quantifies the gap between a periodically rebalanced QQQ/QLD blend (the real,
tradable strategy simulated in ``backtest.py``) and a hypothetical continuously
daily-reset leveraged product at the same target exposure. The two are only
equivalent when the blend itself is rebalanced daily; see docs/methodology.md
section 6.
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

    The blend's target exposure is ``1 + weight_qld``. Under daily rebalancing this
    equals the synthetic :func:`simulate_daily_reset_leverage` product exactly (up
    to trading costs); under less frequent rebalancing the two diverge, which this
    reports as ``cagr_gap`` and ``return_correlation``.
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
    """Show how rebalancing cadence changes the achieved result for a fixed target weight."""
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
