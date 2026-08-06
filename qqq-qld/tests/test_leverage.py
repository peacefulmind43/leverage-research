import numpy as np
import pandas as pd
import pytest

from qqq_qld.leverage import (
    compare_rebalance_frequencies,
    rebalance_drag,
    simulate_daily_reset_leverage,
)


def test_simulate_daily_reset_leverage_matches_closed_form():
    daily = pd.Series(np.repeat(0.001, 100))
    result = simulate_daily_reset_leverage(daily, leverage=2.0)
    assert np.allclose(result.to_numpy(), 2.0 * daily.to_numpy())


def test_leverage_one_is_identity():
    daily = pd.Series([0.01, -0.02, 0.005, -0.001])
    result = simulate_daily_reset_leverage(daily, leverage=1.0)
    assert np.allclose(result.to_numpy(), daily.to_numpy())


def test_negative_leverage_raises():
    with pytest.raises(ValueError, match="non-negative"):
        simulate_daily_reset_leverage(pd.Series([0.01]), leverage=-0.5)


def test_financing_and_expense_reduce_return():
    daily = pd.Series(np.repeat(0.001, 10))
    result = simulate_daily_reset_leverage(
        daily,
        leverage=2.0,
        expense_ratio=0.0095,
        financing_spread=0.005,
        annual_risk_free_rate=0.03,
    )
    expected_daily_drag = 1.0 * (0.03 + 0.005) / 252.0 + 0.0095 / 252.0
    expected = 2.0 * 0.001 - expected_daily_drag
    assert np.allclose(result.to_numpy(), expected)


def _synthetic_qqq_qld(years=5, daily_sigma=0.02, seed=3):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2012-01-02", periods=252 * years)
    qqq = rng.normal(0.0004, daily_sigma, len(index))
    return pd.DataFrame({"QQQ": qqq, "QLD": 2 * qqq}, index=index)


def test_rebalance_drag_daily_rebalance_matches_synthetic_exactly():
    returns = _synthetic_qqq_qld()
    result = rebalance_drag(returns, weight_qld=0.5, rebalance="D")
    assert abs(result["cagr_gap"]) < 1e-9
    assert result["return_correlation"] > 0.999999


def test_rebalance_drag_quarterly_rebalance_shows_material_gap():
    returns = _synthetic_qqq_qld()
    daily = rebalance_drag(returns, weight_qld=0.5, rebalance="D")
    quarterly = rebalance_drag(returns, weight_qld=0.5, rebalance="QE")
    assert abs(quarterly["cagr_gap"]) > 1e-3
    assert abs(quarterly["cagr_gap"]) > abs(daily["cagr_gap"]) * 1000


def test_compare_rebalance_frequencies_has_one_row_per_frequency():
    returns = _synthetic_qqq_qld(years=3)
    table = compare_rebalance_frequencies(returns, weight_qld=0.3, frequencies=("D", "W", "ME"))
    assert list(table.index) == ["D", "W", "ME"]
    assert {"synthetic_cagr", "actual_cagr", "cagr_gap", "return_correlation"}.issubset(
        table.columns
    )
