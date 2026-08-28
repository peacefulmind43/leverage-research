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
        "log_growth": log_growth(clean),
    }


def log_growth(returns: pd.Series) -> float:
    """Annualised mean log return -- the quantity Kelly leverage maximises.

    This is the correct objective for a leverage decision, and Sharpe is not.
    Sharpe is scale-invariant: levering a single asset by ``L`` multiplies both
    excess mean and standard deviation by ``L``, leaving the ratio unchanged in
    the frictionless case and strictly *decreasing* it once financing and fees
    are paid. Maximising Sharpe over a leverage grid therefore returns the
    lowest-leverage point on the grid by construction, whatever the data says --
    a property of the objective, not a finding about leverage.

    Log growth has no such degeneracy. It rises with leverage while the drift
    term dominates and falls once the ``-0.5*L^2*sigma^2`` variance penalty
    takes over, so it has an interior maximum that actually depends on the data.
    Note it equals ``log1p(cagr)``, so ranking by either is equivalent; it is
    reported separately because it is the additive quantity the Kelly algebra
    and :func:`crra_certainty_equivalent` are written in.
    """
    clean = returns.dropna()
    return float(np.log1p(clean).mean() * TRADING_DAYS)


def crra_certainty_equivalent(returns: pd.Series, risk_aversion: float = 1.0) -> float:
    """Annualised certainty-equivalent growth rate under CRRA utility.

    Generalises log growth to investors more risk-averse than Kelly's implied
    log utility. Under the usual lognormal approximation the certainty-equivalent
    rate is ``g - 0.5*(gamma-1)*sigma^2``: ``risk_aversion`` of 1 recovers log
    growth (full Kelly), and larger values penalise variance more, which is what
    makes fractional Kelly an optimum in its own right rather than an arbitrary
    haircut. Typical calibrations put individual investors near 2 to 4.
    """
    if risk_aversion <= 0:
        raise ValueError("risk_aversion must be positive")
    clean = returns.dropna()
    variance = float(clean.var(ddof=1) * TRADING_DAYS)
    return log_growth(clean) - 0.5 * (risk_aversion - 1.0) * variance
