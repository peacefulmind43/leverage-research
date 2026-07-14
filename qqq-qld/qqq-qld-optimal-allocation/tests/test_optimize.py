import numpy as np
import pandas as pd

from qqq_qld.optimize import evaluate_grid, select_optima, stationary_block_bootstrap_weights


def sample_returns():
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2010-01-04", periods=756)
    qqq = rng.normal(0.0005, 0.01, len(index))
    qld = 2 * qqq - 0.0001 + rng.normal(0, 0.001, len(index))
    return pd.DataFrame({"QQQ": qqq, "QLD": qld}, index=index)


def test_grid_contains_endpoints_and_expected_rows():
    grid = evaluate_grid(sample_returns(), step=0.25)
    assert list(grid.index) == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert set(["cagr", "sharpe", "max_drawdown"]).issubset(grid.columns)


def test_select_optima_returns_all_definitions():
    grid = evaluate_grid(sample_returns(), step=0.25)
    selected = select_optima(grid, target_volatility=0.20, max_drawdown_limit=-0.50)
    assert set(selected) == {
        "max_cagr",
        "max_sharpe",
        "max_calmar",
        "target_volatility",
        "max_cagr_with_drawdown_limit",
    }


def test_bootstrap_is_seeded_and_bounded():
    returns = sample_returns()
    first = stationary_block_bootstrap_weights(returns, samples=10, step=0.1, seed=5)
    second = stationary_block_bootstrap_weights(returns, samples=10, step=0.1, seed=5)
    pd.testing.assert_series_equal(first, second)
    assert first.between(0, 1).all()
