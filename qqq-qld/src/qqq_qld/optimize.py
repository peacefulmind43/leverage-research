"""Grid optimization, walk-forward selection, and bootstrap stability."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import portfolio_returns
from .metrics import performance_metrics


def evaluate_grid(
    returns: pd.DataFrame,
    step: float = 0.01,
    rebalance: str = "ME",
    transaction_cost_bps: float = 0.0,
    annual_risk_free_rate: float = 0.0,
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
        rows.append({"weight_qld": float(weight), "weight_qqq": 1.0 - float(weight), **metrics})
    return pd.DataFrame(rows).set_index("weight_qld")


def select_optima(
    grid: pd.DataFrame,
    target_volatility: float,
    max_drawdown_limit: float,
) -> dict[str, pd.Series]:
    """Select optima under several non-equivalent definitions."""
    feasible = grid[grid["max_drawdown"] >= max_drawdown_limit]
    selections = {
        "max_cagr": grid.loc[grid["cagr"].idxmax()],
        "max_sharpe": grid.loc[grid["sharpe"].idxmax()],
        "max_calmar": grid.loc[grid["calmar"].idxmax()],
        "target_volatility": grid.loc[(grid["volatility"] - target_volatility).abs().idxmin()],
    }
    selections["max_cagr_with_drawdown_limit"] = (
        feasible.loc[feasible["cagr"].idxmax()] if not feasible.empty else pd.Series(dtype=float)
    )
    return selections


def walk_forward(
    returns: pd.DataFrame,
    min_train_years: int = 5,
    test_years: int = 1,
    objective: str = "sharpe",
    step: float = 0.01,
    rebalance: str = "ME",
    transaction_cost_bps: float = 0.0,
    annual_risk_free_rate: float = 0.0,
) -> tuple[pd.DataFrame, pd.Series]:
    """Expanding-window selection with non-overlapping out-of-sample tests."""
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
    objective: str = "sharpe",
    step: float = 0.01,
    seed: int = 42,
    **grid_kwargs,
) -> pd.Series:
    """Estimate optimal-weight stability with a moving-block bootstrap.

    For speed, bootstrap selection uses the daily-rebalanced QQQ/QLD mixture.
    This is an intentionally disclosed approximation to the monthly-rebalanced
    full backtest; it answers whether the estimated exposure itself is stable.
    """
    if objective != "sharpe":
        raise ValueError("The fast bootstrap currently supports objective='sharpe' only")
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
        sharpes = (portfolio_means - daily_rf) / np.sqrt(variances) * np.sqrt(252.0)
        chosen[sample] = float(weights[int(np.nanargmax(sharpes))])
    return pd.Series(chosen, name=f"bootstrap_optimal_{objective}")
