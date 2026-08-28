"""Tests for the repository's stated leverage recommendation."""

import numpy as np
import pytest

from qqq_qld.recommend import HOUSE_VIEW, breakeven_table, optimal_leverage, required_return

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
    assert round(result["recommended_leverage"], 2) == 1.00
    assert round(result["unconstrained_leverage"], 2) == 0.52
    assert result["binding"] is True


def test_recommendation_is_a_boundary_not_an_interior_solution():
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


def test_leverage_above_one_requires_near_trailing_returns():
    """The finding the recommendation rests on, asserted rather than narrated.

    At the house risk aversion, even 1.15x needs a forward return above what
    this sample realised over forty years in the best-performing major index.
    """
    trailing_geometric = 0.154
    required = required_return(1.15, SIGMA2, FINANCING, HOUSE_VIEW["risk_aversion"])
    assert required > trailing_geometric


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
