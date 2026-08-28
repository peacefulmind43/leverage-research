"""Tests for the repository's stated leverage recommendation."""

import numpy as np
import pandas as pd
import pytest

from qqq_qld.recommend import (
    HOUSE_VIEW,
    breakeven_table,
    empirical_optimal_leverage,
    horizon_optimal_leverage,
    optimal_leverage,
    required_return,
)

# The measured half of the recommendation, from the reconstructed 1985-2026
# sample and the funds' own returns. Pinned here so a change in either shows up
# as a failing test rather than a quietly different headline number.
SIGMA2 = 0.065901
FINANCING = 0.0541


def test_house_view_recommendation_is_pinned():
    """The headline number, to the precision it is published at.

    If this fails, the recommendation in README.md and results/summary.md is
    stale and must be restated rather than the test relaxed.
    """
    result = optimal_leverage(SIGMA2, FINANCING)
    assert result["risk_aversion"] == 1.0
    assert round(result["unconstrained_leverage"], 2) == 1.04
    assert result["binding"] is False


def test_gamma_is_not_what_drives_the_answer():
    """Both plausible risk aversions land at ~1.00x, for different reasons.

    Guards against the reading that the recommendation is an artefact of risk
    aversion. At gamma=1 the optimum is interior and just above 1x; at gamma=2
    it is far below 1x and clipped. The recommendation is robust to the
    preference here precisely because mu happens to sit near breakeven -- what
    it is *not* robust to is mu, which is the point of the breakeven table.
    """
    kelly = optimal_leverage(SIGMA2, FINANCING, risk_aversion=1.0)
    averse = optimal_leverage(SIGMA2, FINANCING, risk_aversion=2.0)
    assert round(kelly["recommended_leverage"], 1) == 1.0
    assert round(averse["recommended_leverage"], 1) == 1.0
    assert kelly["binding"] is False and averse["binding"] is True


def test_boundary_and_interior_solutions_are_distinguished():
    """A clipped 1.00x and a chosen 1.00x mean different things.

    The distinction is the difference between "leverage is marginally
    unattractive" and "you would hold less than 100% of this asset if you
    could", so the flag has to survive refactoring.
    """
    binding = optimal_leverage(SIGMA2, FINANCING, mu_geometric=0.09, risk_aversion=2.0)
    assert binding["unconstrained_leverage"] < 1.0
    assert binding["binding"] is True

    interior = optimal_leverage(SIGMA2, FINANCING, mu_geometric=0.13, risk_aversion=1.0)
    assert 1.0 < interior["unconstrained_leverage"] < 2.0
    assert interior["binding"] is False
    assert interior["recommended_leverage"] == interior["unconstrained_leverage"]


def test_geometric_input_is_lifted_to_an_arithmetic_mean():
    result = optimal_leverage(SIGMA2, FINANCING, mu_geometric=0.09)
    assert np.isclose(result["mu_arithmetic"], 0.09 + 0.5 * SIGMA2)
    assert np.isclose(result["excess_over_financing"], result["mu_arithmetic"] - FINANCING)


def test_required_return_inverts_optimal_leverage():
    """The breakeven table must be the exact inverse, not an approximation."""
    for leverage in (1.0, 1.15, 1.3, 1.75):
        for gamma in (1.0, 1.5, 2.0, 3.0):
            mu = required_return(leverage, SIGMA2, FINANCING, gamma)
            back = optimal_leverage(
                SIGMA2, FINANCING, mu_geometric=mu, risk_aversion=gamma, min_leverage=0.0
            )
            assert np.isclose(back["unconstrained_leverage"], leverage)


def test_full_leverage_requires_the_trailing_return_to_repeat():
    """The finding the recommendation rests on, asserted rather than narrated.

    Even at full Kelly, 2x is optimal only if forward returns match the 15.4%
    this sample realised over forty years -- in the best-performing major index,
    selected with hindsight.
    """
    trailing_geometric = 0.154
    required = required_return(2.0, SIGMA2, FINANCING, HOUSE_VIEW["risk_aversion"])
    assert np.isclose(required, trailing_geometric, atol=0.005)
    assert required_return(1.0, SIGMA2, FINANCING, 1.0) < 0.09


def test_higher_financing_cost_reduces_recommended_leverage():
    cheap = optimal_leverage(SIGMA2, 0.02, mu_geometric=0.12, risk_aversion=1.0)
    dear = optimal_leverage(SIGMA2, 0.06, mu_geometric=0.12, risk_aversion=1.0)
    assert cheap["unconstrained_leverage"] > dear["unconstrained_leverage"]
    # The gap is exactly the cost difference over variance.
    gap = cheap["unconstrained_leverage"] - dear["unconstrained_leverage"]
    assert np.isclose(gap, 0.04 / SIGMA2)


def test_excluding_the_crisis_window_would_raise_the_recommendation():
    """Why the reconstruction is not optional.

    The live-only sample's variance is materially lower, and since leverage is
    penalised by variance, using it inflates the answer.
    """
    live_sigma2 = 0.2207**2
    full = optimal_leverage(SIGMA2, FINANCING, mu_geometric=0.12, risk_aversion=1.0)
    live = optimal_leverage(live_sigma2, FINANCING, mu_geometric=0.12, risk_aversion=1.0)
    assert live["unconstrained_leverage"] > full["unconstrained_leverage"] + 0.3


def test_breakeven_table_shape_and_monotonicity():
    table = breakeven_table(SIGMA2, FINANCING)
    assert list(table.index) == [1.00, 1.15, 1.30, 1.50, 2.00]
    for column in table.columns:
        if column.startswith("required_mu"):
            assert table[column].is_monotonic_increasing


@pytest.mark.parametrize(("sigma2", "gamma"), [(0.0, 1.0), (0.05, 0.0), (0.05, -1.0)])
def test_optimal_leverage_rejects_degenerate_inputs(sigma2, gamma):
    with pytest.raises(ValueError):
        optimal_leverage(sigma2, FINANCING, risk_aversion=gamma)


def _fat_tailed_series(days=10000, seed=0):
    """Returns with realistic excess kurtosis, so the tail correction can bite."""
    rng = np.random.default_rng(seed)
    normal = rng.normal(0.0005, 0.010, days)
    jumps = rng.standard_t(3, days) * 0.004
    return pd.Series(normal + jumps, index=pd.bdate_range("1990-01-01", periods=days))


def test_empirical_leverage_rescales_to_the_forward_assumption():
    """The shift must change the level and leave the shape alone."""
    series = _fat_tailed_series()
    result = empirical_optimal_leverage(series, FINANCING, mu_geometric=0.09)
    assert np.isclose(result["mu_geometric"], 0.09, atol=1e-6)
    assert result["excess_kurtosis"] > 1.0


def test_fat_tails_lower_the_optimum_below_the_lognormal_formula():
    """The correction's sign is the claim: tails punish leverage.

    The closed form assumes lognormal returns and therefore understates the
    variance penalty on a real, leptokurtic series.
    """
    series = _fat_tailed_series()
    sigma2 = float(series.var(ddof=1) * 252)
    empirical = empirical_optimal_leverage(series, FINANCING, mu_geometric=0.12)
    closed = optimal_leverage(
        sigma2, FINANCING, mu_geometric=0.12, risk_aversion=1.0, min_leverage=0.0
    )
    assert empirical["empirical_leverage"] <= closed["unconstrained_leverage"]


def test_horizon_table_median_and_mean_diverge_with_leverage():
    """Why the median is the statistic to read.

    Mean terminal wealth is carried by a thin right tail and keeps rising with
    leverage past the point where the median has turned over; a report that
    quoted the mean would recommend far more leverage than is optimal.
    """
    series = _fat_tailed_series(days=6000)
    table = horizon_optimal_leverage(
        series, FINANCING, mu_geometric=0.09, years=20, samples=300, seed=1
    )
    best_median = table["median_multiple"].idxmax()
    assert table["mean_multiple"].idxmax() > best_median
    assert table["p5_multiple"].is_monotonic_decreasing


def test_horizon_index_supports_exact_lookups():
    """Regression: a float32-ish arange index broke .loc[1.0] lookups."""
    series = _fat_tailed_series(days=3000)
    table = horizon_optimal_leverage(
        series, FINANCING, mu_geometric=0.09, years=10, samples=100, seed=2
    )
    assert 1.0 in table.index
    assert table.loc[1.0, "prob_beats_unlevered"] == 0.0
