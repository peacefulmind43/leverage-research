"""Command-line interface for the complete research pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .costs import effective_borrow_rate, implied_financing, implied_financing_by_period
from .data import download_prices, prices_to_returns
from .extend import (
    calibrate_synthetic,
    calibration_report,
    download_index,
    download_risk_free,
    extend_history,
    stress_episodes,
)
from .leverage import compare_rebalance_frequencies, rebalance_drag
from .optimize import (
    evaluate_grid,
    kelly_implied_qld_weight,
    kelly_optimal_leverage,
    kelly_sensitivity,
    select_optima,
    stationary_block_bootstrap_weights,
    walk_forward,
)
from .recommend import (
    breakeven_table,
    empirical_optimal_leverage,
    flatness,
    horizon_optimal_leverage,
    horizon_stability,
    optimal_leverage,
    sensitivity_box,
)
from .report import save_figures, write_summary


def _cached(path: Path, refresh: bool, fetch):
    """Fetch a series once and reuse it, so reruns are deterministic and offline."""
    if path.exists() and not refresh:
        series = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
        return pd.to_numeric(series, errors="coerce").dropna()
    series = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    series.to_csv(path)
    return series


def run(
    config_path: str,
    refresh: bool = False,
    fast: bool = False,
    samples: int | None = None,
) -> None:
    root = Path(config_path).resolve().parent.parent
    with open(config_path, encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)
    data_cfg = cfg["data"]
    portfolio_cfg = cfg["portfolio"]
    opt = cfg["optimization"]
    report_cfg = cfg["report"]
    cost_cfg = cfg.get("costs", {})
    extend_cfg = cfg.get("extend", {})

    prices = download_prices(
        data_cfg["tickers"],
        data_cfg["start"],
        data_cfg.get("end"),
        root / data_cfg["cache"],
        refresh=refresh,
        source=data_cfg.get("source", "yahoo"),
    )
    live_returns = prices_to_returns(prices)

    expense_kwargs = {
        "expense_ratio_qqq": cost_cfg.get("expense_ratio_qqq", 0.0020),
        "expense_ratio_qld": cost_cfg.get("expense_ratio_qld", 0.0095),
    }
    risk_free = _cached(
        root / extend_cfg.get("risk_free_cache", "work/risk_free.csv"),
        refresh,
        lambda: download_risk_free(extend_cfg.get("risk_free_series", "DTB3")),
    )

    # QLD's swap spread, recovered from the live funds only -- reconstructed
    # returns are built *using* this number, so including them would be circular.
    financing = implied_financing(live_returns, risk_free, **expense_kwargs)
    swap_spread = cost_cfg.get("swap_spread")
    if swap_spread is None:
        swap_spread = financing["implied_spread"]
    costs = effective_borrow_rate(
        cost_cfg.get("benchmark_rate", 0.0370), swap_spread, **expense_kwargs
    )
    cost_windows = implied_financing_by_period(
        live_returns, risk_free, freq=cost_cfg.get("estimate_window", "5YE"), **expense_kwargs
    )

    returns = live_returns
    extras: dict[str, object] = {"costs": costs, "cost_windows": cost_windows}
    window_note = (
        "> The sample covers QLD's live history only, which begins after the 2000-2002 "
        "unwind -- the worst outcome a leveraged Nasdaq position has faced."
    )
    if extend_cfg.get("enabled", False):
        index = _cached(
            root / extend_cfg.get("index_cache", "work/index.csv"),
            refresh,
            lambda: download_index(
                extend_cfg.get("index_ticker", "^NDX"),
                extend_cfg.get("index_start", "1985-01-01"),
            ),
        )
        index_returns = index.pct_change(fill_method=None).dropna()
        calibration = calibrate_synthetic(live_returns, index_returns, risk_free, **expense_kwargs)
        extras["calibration_report"] = calibration_report(
            live_returns, index_returns, risk_free, calibration, **expense_kwargs
        )
        returns, meta = extend_history(
            live_returns, index_returns, risk_free, calibration, **expense_kwargs
        )
        extras["calibration"] = meta
        window_note = (
            f"> Returns before {meta['splice_date']} are reconstructed from "
            f"{extend_cfg.get('index_ticker', '^NDX')} and a contemporaneous short rate, so the "
            "sample spans the 1987 crash and the 2000-2002 unwind; live fund returns are used "
            "from that date on. See the reconstruction fit below."
        )
    extras["window_note"] = window_note
    extras["stress"] = stress_episodes(returns)

    risk_aversion = opt.get("risk_aversion", 1.0)
    common = dict(
        rebalance=portfolio_cfg["rebalance"],
        transaction_cost_bps=portfolio_cfg["transaction_cost_bps"],
        annual_risk_free_rate=opt["annual_risk_free_rate"],
    )
    grid = evaluate_grid(returns, step=opt["grid_step"], risk_aversion=risk_aversion, **common)
    selected = select_optima(grid, opt["target_volatility"], opt["max_drawdown_limit"])
    walk_table, walk_returns = walk_forward(
        returns,
        min_train_years=opt["min_train_years"],
        test_years=opt["test_years"],
        objective=opt["walk_forward_objective"],
        step=opt["grid_step"],
        risk_aversion=risk_aversion,
        **common,
    )
    if samples is not None:
        sample_count = samples
    elif fast:
        sample_count = min(100, opt["bootstrap_samples"])
    else:
        sample_count = opt["bootstrap_samples"]
    bootstrap = stationary_block_bootstrap_weights(
        returns,
        samples=sample_count,
        block_days=opt["bootstrap_block_days"],
        objective=opt.get("bootstrap_objective", "log_growth"),
        step=opt["grid_step"],
        seed=opt["seed"],
        risk_aversion=risk_aversion,
        **common,
    )
    kelly = kelly_optimal_leverage(
        returns,
        asset="QQQ",
        financing_cost=costs["effective_rate"],
        risk_aversion=1.0,
    )
    extras["kelly_risk_adjusted"] = kelly_optimal_leverage(
        returns,
        asset="QQQ",
        financing_cost=costs["effective_rate"],
        risk_aversion=risk_aversion,
    )
    kelly_weight = kelly_implied_qld_weight(kelly)
    reference_weight = max(kelly_implied_qld_weight({"full_kelly": kelly["half_kelly"]}), 0.30)
    drag_rows = {
        "Kelly-implied": rebalance_drag(returns, kelly_weight, **common),
        "Reference 30% QLD": rebalance_drag(returns, 0.30, **common),
    }
    frequency_table = compare_rebalance_frequencies(
        returns,
        reference_weight,
        transaction_cost_bps=portfolio_cfg["transaction_cost_bps"],
        annual_risk_free_rate=opt["annual_risk_free_rate"],
    )
    trailing_geometric = float(
        (1 + returns["QQQ"]).prod() ** (252 / len(returns)) - 1
    )
    mu_scenarios = {
        "Trailing sample (this backtest)": trailing_geometric,
        **opt.get("mu_scenarios", {}),
    }
    sensitivity = kelly_sensitivity(
        kelly["sigma2"],
        mu_scenarios,
        financing_cost=costs["effective_rate"],
        risk_aversion=risk_aversion,
    )

    rec_cfg = cfg.get("recommendation", {})
    # Forward inputs, which may deliberately differ from the sample's own: the
    # full-sample volatility is dominated by 1995-2002, and a multi-decade
    # holder pays the average future short rate rather than today's spot.
    forward_volatility = rec_cfg.get("volatility") or float(np.sqrt(kelly["sigma2"]))
    forward_sigma2 = forward_volatility**2
    forward_cost = (
        effective_borrow_rate(rec_cfg["benchmark_rate"], swap_spread, **expense_kwargs)[
            "effective_rate"
        ]
        if rec_cfg.get("benchmark_rate") is not None
        else costs["effective_rate"]
    )
    recommendation = optimal_leverage(
        forward_sigma2,
        forward_cost,
        mu_geometric=rec_cfg.get("mu_geometric", 0.09),
        risk_aversion=rec_cfg.get("risk_aversion", 2.0),
        min_leverage=rec_cfg.get("min_leverage", 1.0),
        max_leverage=rec_cfg.get("max_leverage", 2.0),
    )
    # Three estimators of the same quantity, in increasing realism: the closed
    # form assumes lognormal returns; the empirical version compounds through
    # the actual path so fat tails bite; the horizon version resamples finite
    # holding periods because Kelly's optimality is asymptotic. Agreement
    # between them is the check that the headline number is not an artefact of
    # the lognormal assumption.
    recommendation["empirical"] = empirical_optimal_leverage(
        returns["QQQ"],
        forward_cost,
        rec_cfg.get("mu_geometric", 0.095),
        volatility=forward_volatility,
    )["empirical_leverage"]
    horizon = horizon_optimal_leverage(
        returns["QQQ"],
        forward_cost,
        rec_cfg.get("mu_geometric", 0.095),
        volatility=forward_volatility,
        years=rec_cfg.get("horizon_years", 30),
        samples=rec_cfg.get("horizon_samples", 2000),
    )
    recommendation["horizon_years"] = rec_cfg.get("horizon_years", 30)
    # The bootstrap's argmax carries sampling noise of a few hundredths, so it
    # is reported as the interval it is; the deterministic full-path estimator
    # supplies the point estimate.
    recommendation["horizon"] = horizon_stability(
        returns["QQQ"],
        forward_cost,
        rec_cfg.get("mu_geometric", 0.095),
        volatility=forward_volatility,
        years=rec_cfg.get("horizon_years", 30),
        samples=rec_cfg.get("horizon_samples", 2000),
        grid=np.arange(1.0, 1.81, 0.01),
    )
    extras["recommendation"] = recommendation
    extras["horizon_table"] = horizon
    extras["flatness"] = flatness(horizon)
    extras["sensitivity_box"] = sensitivity_box()
    extras["breakeven"] = breakeven_table(forward_sigma2, forward_cost)

    results_dir = root / report_cfg["results_dir"]
    assets_dir = root / report_cfg["assets_dir"]
    results_dir.mkdir(parents=True, exist_ok=True)
    grid.to_csv(results_dir / "weight_grid.csv")
    walk_table.to_csv(results_dir / "walk_forward.csv", index=False)
    bootstrap.to_csv(results_dir / "bootstrap_weights.csv", index=False)
    cost_windows.to_csv(results_dir / "financing_by_period.csv")
    extras["breakeven"].to_csv(results_dir / "leverage_breakeven.csv")
    horizon.to_csv(results_dir / "horizon_wealth.csv")
    extras["stress"].to_csv(results_dir / "stress_episodes.csv")
    save_figures(
        returns,
        grid,
        selected,
        bootstrap,
        assets_dir,
        portfolio_cfg["rebalance"],
        portfolio_cfg["transaction_cost_bps"],
    )
    write_summary(
        results_dir / "summary.md",
        returns,
        grid,
        selected,
        walk_table,
        walk_returns,
        bootstrap,
        kelly,
        kelly_weight,
        drag_rows,
        frequency_table,
        sensitivity,
        cfg,
        extras=extras,
    )
    print(f"Analysis complete: {results_dir / 'summary.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Research QQQ + QLD allocation weights")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--refresh", action="store_true", help="redownload market data")
    parser.add_argument("--fast", action="store_true", help="shorthand for --samples 100")
    parser.add_argument(
        "--samples",
        type=int,
        default=None,
        help="override the configured bootstrap sample count",
    )
    args = parser.parse_args()
    run(args.config, refresh=args.refresh, fast=args.fast, samples=args.samples)


if __name__ == "__main__":
    main()
