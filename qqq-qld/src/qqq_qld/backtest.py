"""Portfolio simulation with explicit periodic rebalancing."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _rebalance_flags(index: pd.DatetimeIndex, frequency: str) -> np.ndarray:
    """Mark the first row and the last trading day of each rebalance period."""
    if frequency.upper() in {"D", "DAILY"}:
        return np.ones(len(index), dtype=bool)
    # Pandas uses ``ME`` for month-end offsets but ``M`` for monthly periods.
    period_frequency = {"ME": "M", "QE": "Q", "YE": "Y"}.get(frequency.upper(), frequency)
    periods = index.to_period(period_frequency)
    flags = np.r_[False, periods[1:] != periods[:-1]]
    flags = np.roll(flags, -1)
    flags[-1] = False
    flags[0] = True
    return flags


def backtest(
    returns: pd.DataFrame,
    weight_qld: float,
    rebalance: str = "ME",
    transaction_cost_bps: float = 0.0,
    initial_value: float = 1.0,
) -> pd.Series:
    """Simulate a long-only QQQ/QLD portfolio.

    ``weight_qld`` is the target QLD weight and ``1-weight_qld`` the QQQ weight.
    Costs are applied to one-way turnover at each rebalance. Fund expenses and
    distributions are already embedded in adjusted prices.
    """
    if not 0 <= weight_qld <= 1:
        raise ValueError("weight_qld must be between 0 and 1")
    if not {"QQQ", "QLD"}.issubset(returns.columns):
        raise ValueError("returns must contain QQQ and QLD columns")
    if returns.empty:
        raise ValueError("returns cannot be empty")

    target = np.array([1.0 - weight_qld, weight_qld], dtype=float)
    asset_returns = returns[["QQQ", "QLD"]].to_numpy(dtype=float)
    flags = _rebalance_flags(returns.index, rebalance)
    values = target * float(initial_value)
    nav = np.empty(len(returns), dtype=float)
    cost_rate = transaction_cost_bps / 10_000.0

    for i, daily in enumerate(asset_returns):
        if flags[i] and i > 0:
            total = values.sum()
            current_weights = values / total
            one_way_turnover = 0.5 * np.abs(target - current_weights).sum()
            total *= 1.0 - one_way_turnover * cost_rate
            values = target * total
        values *= 1.0 + daily
        nav[i] = values.sum()

    return pd.Series(nav, index=returns.index, name=f"QLD {weight_qld:.0%}")


def portfolio_returns(*args, **kwargs) -> pd.Series:
    """Return simple daily portfolio returns from :func:`backtest`."""
    nav = backtest(*args, initial_value=1.0, **kwargs)
    first_return = nav.iloc[0] - 1.0
    out = nav.pct_change(fill_method=None)
    out.iloc[0] = first_return
    return out
