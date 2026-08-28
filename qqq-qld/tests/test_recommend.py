"""Tests for the repository's stated leverage recommendation."""

import numpy as np
import pandas as pd
import pytest

from qqq_qld.recommend import (
    HOUSE_VIEW,
    breakeven_table,
    credible_range,
    empirical_optimal_leverage,
    exposure_drift,
    horizon_optimal_leverage,
    horizon_stability,
    input_sensitivity,
    optimal_leverage,
    required_return,
    sensitivity_box,
)

# The measured half of the recommendation, from the reconstructed 1985-2026
# sample and the funds' own returns. Pinned here so a change in either shows up
# as a failing test rather than a quietly different headline number.
# Forward inputs, matching config/default.yaml's `recommendation` block: a
# volatility between the full-sample 25.67% and the post-2003 22.3%, and a
# financing cost built on the long-run rather than the spot short rate.
SIGMA2 = 0.235**2
FINANCING = 0.0501
SAMPLE_SIGMA2 = 0.065901


def test_house_view_recommendation_is_pinned():
    """The headline number, to the precision it is published at.

    If this fails, the recommendation in README.md and results/summary.md is
    stale and must be restated rather than the test relaxed.
    """
    result = optimal_leverage(SIGMA2, FINANCING)
    assert result["risk_aversion"] == 1.0
    assert result["mu_geometric"] == 0.095
    assert round(result["unconstrained_leverage"], 2) == 1.31
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
    assert kelly["unconstrained_leverage"] > 1.0 and kelly["binding"] is False
    assert averse["unconstrained_leverage"] < 1.0 and averse["binding"] is True


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
    required = required_return(2.0, SAMPLE_SIGMA2, 0.0541, HOUSE_VIEW["risk_aversion"])
    assert np.isclose(required, trailing_geometric, atol=0.005)
    assert required_return(1.0, SIGMA2, FINANCING, 1.0) < HOUSE_VIEW["mu_geometric"]


def test_higher_financing_cost_reduces_recommended_leverage():
    cheap = optimal_leverage(SIGMA2, 0.02, mu_geometric=0.12, risk_aversion=1.0)
    dear = optimal_leverage(SIGMA2, 0.06, mu_geometric=0.12, risk_aversion=1.0)
    assert cheap["unconstrained_leverage"] > dear["unconstrained_leverage"]
    # The gap is exactly the cost difference over variance.
    gap = cheap["unconstrained_leverage"] - dear["unconstrained_leverage"]
    assert np.isclose(gap, 0.04 / SIGMA2)


def test_stacking_conservative_inputs_lands_on_a_corner_not_a_centre():
    """The error this module made once, asserted so it cannot recur silently.

    Each conservative input is individually defensible. Taken together they
    produce the minimum of the plausible region, which is not a cautious
    central estimate but an extreme one.
    """
    box = sensitivity_box()
    # The most conservative value of every input at once: highest volatility,
    # highest financing cost, lowest assumed return.
    corner = optimal_leverage(
        0.2567**2, 0.0541, mu_geometric=0.08, risk_aversion=1.0, min_leverage=0.0
    )["unconstrained_leverage"]
    assert np.isclose(corner, box["leverage"].min(), atol=0.01)
    assert box["leverage"].median() > corner + 0.25

    # The revision this repository actually made is central rather than a corner,
    # which is the check that it recentred instead of over-correcting.
    published = optimal_leverage(0.235**2, 0.0501, min_leverage=0.0)
    assert corner < published["unconstrained_leverage"] < box["leverage"].max()


def test_rescaling_preserves_shape_while_retargeting_scale():
    """Substituting a forward volatility must not launder away the fat tails.

    Rescaling standardises *log* returns, whose standardised moments are
    preserved exactly. The reported kurtosis is measured on simple returns, and
    ``expm1`` is non-linear, so it shifts by a few percent -- close is the
    correct expectation here, not equal. What matters is that the series stays
    strongly leptokurtic rather than being flattened toward Gaussian.
    """
    series = _fat_tailed_series()
    original = empirical_optimal_leverage(series, FINANCING, mu_geometric=0.095)
    rescaled = empirical_optimal_leverage(
        series, FINANCING, mu_geometric=0.095, volatility=0.235
    )
    assert np.isclose(rescaled["excess_kurtosis"], original["excess_kurtosis"], rtol=0.10)
    assert rescaled["excess_kurtosis"] > 3.0
    assert np.isclose(rescaled["mu_geometric"], 0.095, atol=1e-6)


def test_bootstrap_cannot_support_two_decimals():
    """Why the headline comes from the deterministic estimator.

    The block bootstrap's argmax moves with the resampling seed, so quoting it
    to two decimals would be false precision. Reporting it as an interval, and
    taking the point estimate from the full realised path, is the fix.
    """
    series = _fat_tailed_series(days=4000)
    spread = horizon_stability(
        series,
        FINANCING,
        mu_geometric=0.095,
        volatility=0.235,
        seeds=(0, 1, 2, 3),
        years=15,
        samples=250,
        grid=np.arange(1.0, 1.61, 0.01),
    )
    assert spread["maximum"] > spread["minimum"]
    assert spread["seeds"] == 4


def test_excluding_the_crisis_window_would_raise_the_recommendation():
    """Why the reconstruction is not optional.

    The live-only sample's variance is materially lower, and since leverage is
    penalised by variance, using it inflates the answer.
    """
    live_sigma2 = 0.2207**2
    full = optimal_leverage(SAMPLE_SIGMA2, FINANCING, mu_geometric=0.12, risk_aversion=1.0)
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


def test_credible_range_spans_more_than_the_point_estimate_suggests():
    """The range is the finding. If it ever narrows, the claim must be restated."""
    band = credible_range(point_estimate=1.23)
    assert band["minimum"] < 1.0 < band["maximum"]
    assert band["ratio_max_to_min"] > 2.0
    # The published point estimate must be central, not a corner.
    assert 25.0 < band["percentile_of_point"] < 75.0


def test_percentile_flags_a_corner_masquerading_as_a_correction():
    """The specific guard against over-correcting under pushback.

    A revised figure that lands near 0 or 100 has swapped one extreme for the
    other rather than recentring, and the percentile is what reveals that.
    """
    box = sensitivity_box()
    low = credible_range(box, point_estimate=float(box["leverage"].min()))
    high = credible_range(box, point_estimate=float(box["leverage"].max()))
    assert low["percentile_of_point"] == 0.0
    assert high["percentile_of_point"] > 95.0


def test_closed_form_is_biased_high_against_discrete_rebalancing():
    """The continuous-time formula is the approximation, not the truth.

    Verified on lognormal returns where the analytic answer is exact by
    construction: daily discrete rebalancing still gives up roughly a tenth of a
    turn of leverage against it, so the gap on real data is not evidence of a
    bug and the two should not be expected to agree exactly.
    """
    rng = np.random.default_rng(0)
    mu_geometric, sigma, cost = 0.12, 0.20, 0.04
    daily = np.log1p(mu_geometric) / 252 + sigma / np.sqrt(252) * rng.standard_normal(252 * 4000)
    series = pd.Series(np.expm1(daily))
    empirical = empirical_optimal_leverage(series, cost, grid=np.arange(0.0, 4.01, 0.01))
    analytic = optimal_leverage(
        sigma**2, cost, mu_geometric=mu_geometric, risk_aversion=1.0, min_leverage=0.0
    )
    assert empirical["empirical_leverage"] < analytic["unconstrained_leverage"]
    assert analytic["unconstrained_leverage"] - empirical["empirical_leverage"] < 0.25


def test_third_decimal_is_below_the_input_resolution():
    """The claim that a three-decimal leverage figure is noise.

    A tenth of a percentage point on the forward return -- far finer than it can
    be forecast -- must move the optimum by more than 0.001, which is what makes
    the third decimal uninformative however reproducibly it is computed.
    """
    series = _fat_tailed_series(days=6000)
    table = input_sensitivity(
        series, FINANCING, 0.095, 0.235, bump=0.001, grid=np.arange(0.8, 2.01, 0.001)
    )
    assert abs(table.loc["mu_geometric", "change"]) > 0.001
    # The optimum depends only on the spread between return and financing cost,
    # so their derivatives are equal and opposite, both 1/sigma^2. The return
    # dominates the *uncertainty* because it is known far less precisely -- not
    # because the answer is more sensitive to it. Asserting the symmetry keeps
    # that distinction from being quietly reintroduced as a sensitivity claim.
    per_unit_mu = table.loc["mu_geometric", "leverage_per_unit"]
    per_unit_cost = table.loc["financing_cost", "leverage_per_unit"]
    assert np.isclose(per_unit_mu, -per_unit_cost, rtol=0.1)
    assert abs(per_unit_mu) > 1.0


def test_exposure_drift_bounds_the_precision_worth_quoting():
    """A target that cannot be held to three decimals cannot be acted on to three."""
    index = pd.bdate_range("2010-01-04", periods=2520)
    rng = np.random.default_rng(4)
    underlying = pd.Series(rng.normal(0.0004, 0.012, len(index)), index=index)
    frame = pd.DataFrame({"QQQ": underlying, "QLD": 2 * underlying - 0.05 / 252})
    drift = exposure_drift(frame, 0.23)
    assert drift["minimum"] < drift["target_exposure"] < drift["maximum"]
    assert drift["typical_band"] > 0.001
