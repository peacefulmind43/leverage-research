"""Command-line interface for the complete research pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .data import download_prices, prices_to_returns
from .optimize import evaluate_grid, select_optima, stationary_block_bootstrap_weights, walk_forward
from .report import save_figures, write_summary


def run(config_path: str, refresh: bool = False, fast: bool = False) -> None:
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
    samples = min(100, opt["bootstrap_samples"]) if fast else opt["bootstrap_samples"]
    bootstrap = stationary_block_bootstrap_weights(
        returns,
        samples=samples,
        block_days=opt["bootstrap_block_days"],
        objective="sharpe",
        step=opt["grid_step"],
        seed=opt["seed"],
        **common,
    )

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
        cfg,
    )
    print(f"Analysis complete: {results_dir / 'summary.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Research QQQ + QLD allocation weights")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--refresh", action="store_true", help="redownload market data")
    parser.add_argument("--fast", action="store_true", help="use 100 bootstrap samples")
    args = parser.parse_args()
    run(args.config, refresh=args.refresh, fast=args.fast)


if __name__ == "__main__":
    main()
