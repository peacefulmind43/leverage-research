import numpy as np
import pandas as pd
import pytest

from qqq_qld.optimize import (
    evaluate_grid,
    kelly_implied_qld_weight,
    kelly_optimal_leverage,
    select_optima,
    stationary_block_bootstrap_weights,
    walk_forward,
)


def sample_returns(years: int = 3):
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2010-01-04", periods=252 * years)
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


def test_kelly_optimal_leverage_matches_closed_form():
    rng = np.random.default_rng(3)
    index = pd.bdate_range("2015-01-02", periods=252 * 4)
    daily_mu, daily_sigma = 0.0004, 0.012
    qqq = rng.normal(daily_mu, daily_sigma, len(index))
    returns = pd.DataFrame({"QQQ": qqq, "QLD": 2 * qqq}, index=index)

    result = kelly_optimal_leverage(returns, asset="QQQ", annual_risk_free_rate=0.0)

    expected_mu = qqq.mean() * 252
    expected_sigma2 = qqq.var(ddof=1) * 252
    assert np.isclose(result["mu"], expected_mu)
    assert np.isclose(result["sigma2"], expected_sigma2)
    assert np.isclose(result["full_kelly"], expected_mu / expected_sigma2)
    assert np.isclose(result["half_kelly"], result["full_kelly"] / 2.0)


def test_kelly_optimal_leverage_rejects_missing_asset():
    returns = sample_returns()
    with pytest.raises(ValueError, match="not found"):
        kelly_optimal_leverage(returns, asset="SPY")


@pytest.mark.parametrize(
    ("full_kelly", "expected_weight"),
    [(3.0, 1.0), (0.3, 0.0), (1.5, 0.5)],
)
def test_kelly_implied_qld_weight_clips_to_achievable_range(full_kelly, expected_weight):
    weight = kelly_implied_qld_weight({"full_kelly": full_kelly})
    assert np.isclose(weight, expected_weight)


def test_walk_forward_uses_expanding_non_overlapping_windows():
    returns = sample_returns(years=6)
    table, oos_returns = walk_forward(
        returns,
        min_train_years=2,
        test_years=1,
        objective="sharpe",
        step=0.25,
    )
    assert not table.empty
    assert table["selected_weight_qld"].between(0, 1).all()

    test_starts = pd.to_datetime(table["test_start"])
    test_ends = pd.to_datetime(table["test_end"])
    # Non-overlapping: each window starts after the previous one ends.
    assert (test_starts.iloc[1:].to_numpy() > test_ends.iloc[:-1].to_numpy()).all()
    # Out-of-sample series never extends before the first test window starts.
    assert oos_returns.index.min() >= test_starts.iloc[0]
    assert oos_returns.index.max() <= test_ends.iloc[-1]
