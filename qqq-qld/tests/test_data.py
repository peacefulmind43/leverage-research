import numpy as np
import pandas as pd
import pytest

from qqq_qld.data import _validate_prices, prices_to_returns


def _valid_prices(rows: int = 300) -> pd.DataFrame:
    index = pd.bdate_range("2020-01-02", periods=rows)
    return pd.DataFrame(
        {"QQQ": np.linspace(100, 150, rows), "QLD": np.linspace(50, 90, rows)},
        index=index,
    )


def test_validate_prices_accepts_clean_data():
    _validate_prices(_valid_prices(), ["QQQ", "QLD"])


def test_validate_prices_rejects_missing_ticker():
    prices = _valid_prices().drop(columns=["QLD"])
    with pytest.raises(ValueError, match="Missing ticker columns"):
        _validate_prices(prices, ["QQQ", "QLD"])


def test_validate_prices_rejects_short_sample():
    prices = _valid_prices(rows=100)
    with pytest.raises(ValueError, match="Fewer than 252"):
        _validate_prices(prices, ["QQQ", "QLD"])


def test_validate_prices_rejects_nan():
    prices = _valid_prices()
    prices.iloc[10, 0] = np.nan
    with pytest.raises(ValueError, match="complete and strictly positive"):
        _validate_prices(prices, ["QQQ", "QLD"])


def test_validate_prices_rejects_non_positive():
    prices = _valid_prices()
    prices.iloc[10, 0] = 0.0
    with pytest.raises(ValueError, match="complete and strictly positive"):
        _validate_prices(prices, ["QQQ", "QLD"])


def test_prices_to_returns_matches_pct_change():
    prices = _valid_prices(rows=10)
    returns = prices_to_returns(prices)
    expected = prices.pct_change(fill_method=None).dropna(how="any")
    pd.testing.assert_frame_equal(returns, expected)
    assert len(returns) == len(prices) - 1
