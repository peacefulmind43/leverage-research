"""Tests for QLD's embedded cost of leverage."""

import numpy as np
import pandas as pd
import pytest

from qqq_qld.costs import (
    BLEND_FEE_PREMIUM,
    blend_cost_at_weight,
    effective_borrow_rate,
    implied_financing,
    implied_financing_by_period,
    tracking_regression,
)

ER_QQQ = 0.0020
ER_QLD = 0.0095


def synthetic_pair(financing=0.05, rf=0.04, days=1260, seed=0):
    """Build QQQ/QLD returns with a known financing rate baked in.

    Constructed the way the funds actually work, so recovering ``financing``
    from the output is a real round trip rather than an algebraic identity: the
    index return is the shared driver, QQQ pays only its own expense ratio, and
    QLD doubles the index while paying financing on the borrowed notional.
    """
    index = pd.bdate_range("2010-01-04", periods=days)
    rng = np.random.default_rng(seed)
    underlying = pd.Series(rng.normal(0.0004, 0.012, days), index=index)
    qqq = underlying - ER_QQQ / 252
    qld = 2 * underlying - financing / 252 - ER_QLD / 252
    risk_free = pd.Series(rf, index=index)
    return pd.DataFrame({"QQQ": qqq, "QLD": qld}), risk_free


def test_implied_financing_recovers_a_known_rate():
    returns, risk_free = synthetic_pair(financing=0.05, rf=0.04)
    result = implied_financing(returns, risk_free)
    assert np.isclose(result["implied_financing_rate"], 0.05, atol=1e-9)
    assert np.isclose(result["implied_spread"], 0.01, atol=1e-9)


@pytest.mark.parametrize("financing", [0.0, 0.02, 0.08])
def test_implied_financing_is_unbiased_across_rate_levels(financing):
    returns, risk_free = synthetic_pair(financing=financing, rf=0.03)
    result = implied_financing(returns, risk_free)
    assert np.isclose(result["implied_financing_rate"], financing, atol=1e-9)


def test_implied_financing_tracks_a_time_varying_benchmark():
    """A constant rate assumption would push rate moves into the spread.

    The sample this repository uses spans a benchmark that went from 5% to zero
    and back, so a contemporaneous series is not a refinement -- using a
    constant would corrupt the estimate outright.
    """
    index = pd.bdate_range("2010-01-04", periods=1260)
    rng = np.random.default_rng(3)
    underlying = pd.Series(rng.normal(0.0004, 0.012, len(index)), index=index)
    rf = pd.Series(np.linspace(0.0, 0.06, len(index)), index=index)
    spread = 0.009
    returns = pd.DataFrame(
        {
            "QQQ": underlying - ER_QQQ / 252,
            "QLD": 2 * underlying - (rf + spread) / 252 - ER_QLD / 252,
        }
    )
    assert np.isclose(implied_financing(returns, rf)["implied_spread"], spread, atol=1e-9)
    constant = implied_financing(returns, float(rf.mean()))
    assert np.isclose(constant["implied_spread"], spread, atol=1e-9)


def test_fee_premium_is_invariant_to_blend_weight():
    """The closed form behind the margin comparison.

    Borrowing via the blend versus on margin differs by ``ER_QLD - 2*ER_QQQ``
    per dollar borrowed at *every* weight. If this ever stops holding, the
    single-number margin comparison in the report is no longer valid.
    """
    assert np.isclose(BLEND_FEE_PREMIUM, ER_QLD - 2 * ER_QQQ)
    benchmark, spread = 0.037, 0.0116
    for weight in (0.05, 0.3, 0.75, 1.0):
        blend = blend_cost_at_weight(weight, benchmark, spread)
        margin_rate = effective_borrow_rate(benchmark, spread)["effective_rate"]
        margin = weight * margin_rate + (1 + weight) * ER_QQQ
        assert np.isclose(blend, margin, atol=1e-12)


def test_effective_rate_is_financing_plus_premium():
    result = effective_borrow_rate(0.037, 0.0116)
    assert np.isclose(result["financing_rate"], 0.037 + 0.0116)
    assert np.isclose(result["effective_rate"], 0.037 + 0.0116 + BLEND_FEE_PREMIUM)


def test_tracking_regression_recovers_the_two_times_objective():
    returns, _ = synthetic_pair()
    fit = tracking_regression(returns)
    assert np.isclose(fit["beta"], 2.0, atol=1e-6)
    assert fit["r_squared"] > 0.999


def test_period_estimates_split_the_sample():
    returns, risk_free = synthetic_pair(days=2520)
    table = implied_financing_by_period(returns, risk_free, freq="2YE")
    assert len(table) >= 2
    assert np.allclose(table["implied_financing_rate"], 0.05, atol=1e-9)


def test_implied_financing_rejects_missing_columns():
    with pytest.raises(ValueError, match="not found"):
        implied_financing(pd.DataFrame({"QQQ": [0.01, 0.02]}))
