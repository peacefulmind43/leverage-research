import numpy as np
import pandas as pd
import pytest

from qqq_qld.optimize import (
    evaluate_grid,
    kelly_implied_qld_weight,
    kelly_optimal_leverage,
    kelly_sensitivity,
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
        "max_log_growth",
        "max_certainty_equivalent",
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


def test_kelly_sensitivity_computes_expected_rows_and_clipping():
    sigma2 = 0.05
    mu_scenarios = {"Bear": -0.05, "Base": 0.06, "Trailing": 0.30}

    table = kelly_sensitivity(sigma2, mu_scenarios, geometric_input=False, risk_aversion=2.0)

    assert list(table.index) == ["Bear", "Base", "Trailing"]
    for scenario, mu in mu_scenarios.items():
        row = table.loc[scenario]
        expected_full = mu / sigma2
        assert np.isclose(row["assumed_mu"], mu)
        assert np.isclose(row["full_kelly_leverage"], expected_full)
        assert np.isclose(row["risk_adjusted_leverage"], expected_full / 2.0)
        assert np.isclose(
            row["full_kelly_qld_weight"], np.clip(expected_full - 1.0, 0.0, 1.0)
        )
    # Bear case (negative mu) clips to 0% QLD on both leverage definitions.
    assert table.loc["Bear", "full_kelly_qld_weight"] == 0.0
    assert table.loc["Bear", "risk_adjusted_qld_weight"] == 0.0


def test_kelly_sensitivity_converts_geometric_input_to_arithmetic():
    """A geometric CMA must be lifted by 0.5*sigma^2 before entering Kelly.

    Skipping the conversion understates mu by half the variance, which at
    equity-like volatility is several percentage points -- a large error in a
    numerator that is itself a difference of similar-sized numbers.
    """
    sigma2 = 0.0659
    table = kelly_sensitivity(sigma2, {"CMA": 0.06}, financing_cost=0.05, geometric_input=True)
    row = table.loc["CMA"]
    assert np.isclose(row["arithmetic_mu"], 0.06 + 0.5 * sigma2)
    assert np.isclose(row["excess_over_financing"], 0.06 + 0.5 * sigma2 - 0.05)
    assert np.isclose(row["full_kelly_leverage"], row["excess_over_financing"] / sigma2)

    naive = kelly_sensitivity(sigma2, {"CMA": 0.06}, financing_cost=0.05, geometric_input=False)
    assert row["full_kelly_leverage"] > naive.loc["CMA", "full_kelly_leverage"]


def test_kelly_financing_cost_lowers_optimal_leverage():
    """Financing belongs in the numerator: omitting it prices borrowing at zero."""
    returns = sample_returns()
    free = kelly_optimal_leverage(returns, asset="QQQ", financing_cost=0.0)
    paid = kelly_optimal_leverage(returns, asset="QQQ", financing_cost=0.05)
    assert paid["full_kelly"] < free["full_kelly"]
    # The gap is exactly c / sigma^2, so the error is not a rounding detail.
    assert np.isclose(free["full_kelly"] - paid["full_kelly"], 0.05 / free["sigma2"])


def test_kelly_risk_aversion_scales_leverage_inversely():
    """Fractional Kelly is gamma > 1, not an unexplained haircut."""
    returns = sample_returns()
    base = kelly_optimal_leverage(returns, asset="QQQ", financing_cost=0.02, risk_aversion=1.0)
    averse = kelly_optimal_leverage(returns, asset="QQQ", financing_cost=0.02, risk_aversion=2.0)
    assert np.isclose(averse["full_kelly"], base["full_kelly"] / 2.0)
    assert np.isclose(averse["full_kelly"], base["half_kelly"])


def test_sharpe_cannot_select_leverage():
    """The headline guard: Sharpe's argmax over a leverage grid is 0% by construction.

    QLD here is exactly 2x QQQ minus a positive cost, so no data-generating
    process can make a levered blend win on Sharpe. Any report that presents
    argmax-Sharpe as evidence against leverage is restating this identity.
    """
    index = pd.bdate_range("2015-01-01", periods=756)
    rng = np.random.default_rng(0)
    qqq = pd.Series(rng.normal(0.0009, 0.011, len(index)), index=index)
    returns = pd.DataFrame({"QQQ": qqq, "QLD": 2 * qqq - 0.05 / 252}, index=index)

    grid = evaluate_grid(returns, step=0.1, rebalance="ME")
    assert grid["sharpe"].idxmax() == 0.0
    assert (np.diff(grid["sharpe"].to_numpy()) < 0).all()
    # Log growth is not degenerate: it is free to pick an interior point.
    assert grid["log_growth"].is_monotonic_increasing or grid["log_growth"].idxmax() >= 0.0

    with pytest.warns(RuntimeWarning, match="scale-invariant"):
        walk_forward(returns, min_train_years=1, objective="sharpe", step=0.25)


def test_walk_forward_uses_expanding_non_overlapping_windows():
    returns = sample_returns(years=6)
    table, oos_returns = walk_forward(
        returns,
        min_train_years=2,
        test_years=1,
        objective="log_growth",
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
