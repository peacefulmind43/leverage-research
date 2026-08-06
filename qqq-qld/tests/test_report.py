import numpy as np
import pandas as pd

from qqq_qld.optimize import (
    evaluate_grid,
    kelly_optimal_leverage,
    select_optima,
    stationary_block_bootstrap_weights,
    walk_forward,
)
from qqq_qld.report import write_summary


def _synthetic_returns(years: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2015-01-02", periods=252 * years)
    qqq = rng.normal(0.0004, 0.01, len(index))
    qld = 2 * qqq - 0.0001 + rng.normal(0, 0.001, len(index))
    return pd.DataFrame({"QQQ": qqq, "QLD": qld}, index=index)


def _config() -> dict:
    return {
        "portfolio": {"rebalance": "ME", "transaction_cost_bps": 2.0},
        "optimization": {
            "annual_risk_free_rate": 0.0,
            "target_volatility": 0.20,
            "max_drawdown_limit": -0.99,
        },
    }


def test_write_summary_produces_expected_sections(tmp_path):
    returns = _synthetic_returns()
    config = _config()
    opt = config["optimization"]
    portfolio = config["portfolio"]

    grid = evaluate_grid(
        returns,
        step=0.5,
        rebalance=portfolio["rebalance"],
        transaction_cost_bps=portfolio["transaction_cost_bps"],
        annual_risk_free_rate=opt["annual_risk_free_rate"],
    )
    selected = select_optima(grid, opt["target_volatility"], opt["max_drawdown_limit"])
    walk_table, walk_returns = walk_forward(
        returns,
        min_train_years=1,
        test_years=1,
        step=0.5,
        rebalance=portfolio["rebalance"],
        transaction_cost_bps=portfolio["transaction_cost_bps"],
        annual_risk_free_rate=opt["annual_risk_free_rate"],
    )
    bootstrap = stationary_block_bootstrap_weights(returns, samples=5, step=0.5, seed=1)
    kelly = kelly_optimal_leverage(returns, annual_risk_free_rate=opt["annual_risk_free_rate"])

    out_path = tmp_path / "summary.md"
    write_summary(
        out_path, returns, grid, selected, walk_table, walk_returns, bootstrap, kelly, config
    )

    text = out_path.read_text(encoding="utf-8")
    assert "# QQQ + QLD Empirical Results" in text
    assert "## The optimal allocation depends on the objective" in text
    assert "## Out-of-sample performance and stability" in text
    assert "## Growth-optimal leverage (Kelly estimate)" in text
    assert "full-Kelly" in text
    assert "## Walk-forward annual selections" in text
    # A feasible max_cagr row should not degrade to the N/A placeholder row.
    assert "| Maximum in-sample CAGR | N/A |" not in text


def test_write_summary_handles_infeasible_drawdown_constraint(tmp_path):
    returns = _synthetic_returns()
    config = _config()
    config["optimization"]["max_drawdown_limit"] = -0.01
    opt = config["optimization"]
    portfolio = config["portfolio"]

    grid = evaluate_grid(
        returns,
        step=0.5,
        rebalance=portfolio["rebalance"],
        transaction_cost_bps=portfolio["transaction_cost_bps"],
        annual_risk_free_rate=opt["annual_risk_free_rate"],
    )
    selected = select_optima(grid, opt["target_volatility"], opt["max_drawdown_limit"])
    walk_table, walk_returns = walk_forward(
        returns,
        min_train_years=1,
        test_years=1,
        step=0.5,
        rebalance=portfolio["rebalance"],
        transaction_cost_bps=portfolio["transaction_cost_bps"],
        annual_risk_free_rate=opt["annual_risk_free_rate"],
    )
    bootstrap = stationary_block_bootstrap_weights(returns, samples=5, step=0.5, seed=1)
    kelly = kelly_optimal_leverage(returns, annual_risk_free_rate=opt["annual_risk_free_rate"])

    out_path = tmp_path / "summary.md"
    write_summary(
        out_path, returns, grid, selected, walk_table, walk_returns, bootstrap, kelly, config
    )

    text = out_path.read_text(encoding="utf-8")
    assert "| Maximum CAGR with drawdown no worse than -1% | N/A |" in text
