"""Command-line interface for the complete research pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .data import download_prices, prices_to_returns
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
from .report import save_figures, write_summary


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

    prices = download_prices(
        data_cfg["tickers"],
        data_cfg["start"],
        data_cfg.get("end"),
        root / data_cfg["cache"],
        refresh=refresh,
        source=data_cfg.get("source", "yahoo"),
    )
    returns = prices_to_returns(prices)
    common = dict(
        rebalance=portfolio_cfg["rebalance"],
        transaction_cost_bps=portfolio_cfg["transaction_cost_bps"],
        annual_risk_free_rate=opt["annual_risk_free_rate"],
    )
    grid = evaluate_grid(returns, step=opt["grid_step"], **common)
    selected = select_optima(grid, opt["target_volatility"], opt["max_drawdown_limit"])
    walk_table, walk_returns = walk_forward(
        returns,
        min_train_years=opt["min_train_years"],
        test_years=opt["test_years"],
        objective=opt["walk_forward_objective"],
        step=opt["grid_step"],
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
        objective="sharpe",
        step=opt["grid_step"],
        seed=opt["seed"],
        **common,
    )
    kelly = kelly_optimal_leverage(
        returns, asset="QQQ", annual_risk_free_rate=opt["annual_risk_free_rate"]
    )
    kelly_weight = kelly_implied_qld_weight(kelly)
    half_kelly_weight = kelly_implied_qld_weight({"full_kelly": kelly["half_kelly"]})
    max_sharpe_weight = float(selected["max_sharpe"].name)
    drag_rows = {
        "Half-Kelly": rebalance_drag(returns, half_kelly_weight, **common),
        "Max-Sharpe (grid)": rebalance_drag(returns, max_sharpe_weight, **common),
    }
    frequency_table = compare_rebalance_frequencies(
        returns,
        max_sharpe_weight,
        transaction_cost_bps=portfolio_cfg["transaction_cost_bps"],
        annual_risk_free_rate=opt["annual_risk_free_rate"],
    )
    mu_scenarios = {
        "Trailing sample (this backtest)": kelly["mu"],
        **opt.get("mu_scenarios", {}),
    }
    sensitivity = kelly_sensitivity(kelly["sigma2"], mu_scenarios)

    results_dir = root / report_cfg["results_dir"]
    assets_dir = root / report_cfg["assets_dir"]
    results_dir.mkdir(parents=True, exist_ok=True)
    grid.to_csv(results_dir / "weight_grid.csv")
    walk_table.to_csv(results_dir / "walk_forward.csv", index=False)
    bootstrap.to_csv(results_dir / "bootstrap_weights.csv", index=False)
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
