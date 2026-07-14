import numpy as np
import pandas as pd
import pytest

from qqq_qld.backtest import backtest, portfolio_returns


@pytest.fixture
def returns():
    index = pd.bdate_range("2024-01-02", periods=80)
    return pd.DataFrame({"QQQ": 0.001, "QLD": 0.002}, index=index)


def test_endpoint_weights_match_single_assets(returns):
    qqq = portfolio_returns(returns, weight_qld=0.0, rebalance="ME")
    qld = portfolio_returns(returns, weight_qld=1.0, rebalance="ME")
    np.testing.assert_allclose(qqq, returns["QQQ"], rtol=1e-12)
    np.testing.assert_allclose(qld, returns["QLD"], rtol=1e-12)


def test_daily_rebalancing_matches_weighted_daily_return(returns):
    mixed = portfolio_returns(returns, weight_qld=0.4, rebalance="D")
    expected = 0.6 * returns["QQQ"] + 0.4 * returns["QLD"]
    np.testing.assert_allclose(mixed, expected, rtol=1e-12)


def test_invalid_weight_rejected(returns):
    with pytest.raises(ValueError, match="between 0 and 1"):
        backtest(returns, weight_qld=1.01)


def test_transaction_cost_cannot_improve_nav():
    index = pd.bdate_range("2024-01-02", periods=80)
    alternating = np.where(np.arange(80) % 2 == 0, 0.02, -0.015)
    returns = pd.DataFrame({"QQQ": alternating, "QLD": -alternating}, index=index)
    free = backtest(returns, 0.5, rebalance="D", transaction_cost_bps=0)
    costly = backtest(returns, 0.5, rebalance="D", transaction_cost_bps=10)
    assert costly.iloc[-1] < free.iloc[-1]
