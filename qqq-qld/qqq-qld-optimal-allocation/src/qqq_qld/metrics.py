"""Performance and risk metrics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def drawdown(returns: pd.Series) -> pd.Series:
    wealth = (1.0 + returns).cumprod()
    return wealth / wealth.cummax() - 1.0


def performance_metrics(returns: pd.Series, annual_risk_free_rate: float = 0.0) -> dict[str, float]:
    clean = returns.dropna()
    if clean.empty:
        raise ValueError("returns cannot be empty")
    years = len(clean) / TRADING_DAYS
    terminal = float((1.0 + clean).prod())
    cagr = terminal ** (1.0 / years) - 1.0
    volatility = float(clean.std(ddof=1) * math.sqrt(TRADING_DAYS))
    daily_rf = (1.0 + annual_risk_free_rate) ** (1.0 / TRADING_DAYS) - 1.0
    excess = clean - daily_rf
    sharpe = float(excess.mean() / clean.std(ddof=1) * math.sqrt(TRADING_DAYS))
    downside = np.minimum(excess.to_numpy(), 0.0)
    downside_deviation = float(np.sqrt(np.mean(downside**2)) * math.sqrt(TRADING_DAYS))
    sortino = (cagr - annual_risk_free_rate) / downside_deviation if downside_deviation else np.nan
    max_dd = float(drawdown(clean).min())
    calmar = cagr / abs(max_dd) if max_dd else np.nan
    return {
        "cagr": cagr,
        "volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "terminal_multiple": terminal,
    }
