"""Tables, figures, and Markdown research report generation."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .backtest import portfolio_returns
from .metrics import drawdown, performance_metrics


def _pct(value: float) -> str:
    return "N/A" if pd.isna(value) else f"{value:.1%}"


def save_figures(
    returns: pd.DataFrame,
    grid: pd.DataFrame,
    selected: dict[str, pd.Series],
    bootstrap: pd.Series,
    assets_dir: str | Path,
    rebalance: str,
    transaction_cost_bps: float,
) -> None:
    out = Path(assets_dir)
    out.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.plot(grid.index * 100, grid["cagr"] * 100, label="CAGR")
    ax.plot(grid.index * 100, grid["volatility"] * 100, label="Volatility")
    ax.set(xlabel="QLD weight (%)", ylabel="Annualized (%)", title="Return and risk by QLD weight")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "weight_landscape.png", dpi=180)
    plt.close(fig)

    weights = sorted({0.0, 0.25, 0.5, 0.75, 1.0, float(grid["sharpe"].idxmax())})
    fig, ax = plt.subplots(figsize=(9, 5.2))
    for weight in weights:
        port = portfolio_returns(
            returns,
            weight,
            rebalance=rebalance,
            transaction_cost_bps=transaction_cost_bps,
        )
        ax.plot((1 + port).cumprod(), label=f"{weight:.0%} QLD")
    ax.set_yscale("log")
    ax.set(title="Growth of $1 (log scale)", ylabel="Portfolio value")
    ax.legend(ncol=2)
    fig.tight_layout()
    fig.savefig(out / "growth_of_one.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5.2))
    for label in ["max_sharpe", "max_calmar", "max_cagr"]:
        weight = float(selected[label].name)
        port = portfolio_returns(
            returns,
            weight,
            rebalance=rebalance,
            transaction_cost_bps=transaction_cost_bps,
        )
        ax.plot(drawdown(port) * 100, label=f"{label}: {weight:.0%} QLD")
    ax.set(title="Drawdowns", ylabel="Drawdown (%)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "drawdowns.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.6))
    bins = np.arange(-0.005, 1.025, 0.025)
    ax.hist(bootstrap, bins=bins, edgecolor="white")
    ax.axvline(bootstrap.median(), color="black", linestyle="--", label="Median")
    ax.set(
        xlabel="Optimal QLD weight",
        ylabel="Bootstrap samples",
        title="Optimal-weight stability",
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "bootstrap_weights.png", dpi=180)
    plt.close(fig)


def write_summary(
    path: str | Path,
    returns: pd.DataFrame,
    grid: pd.DataFrame,
    selected: dict[str, pd.Series],
    walk_table: pd.DataFrame,
    walk_returns: pd.Series,
    bootstrap: pd.Series,
    config: dict,
) -> None:
    oos = performance_metrics(walk_returns, config["optimization"]["annual_risk_free_rate"])
    lines = [
        "# QQQ + QLD Empirical Results",
        "",
        f"> Data window: {returns.index.min().date()} through {returns.index.max().date()};",
        f"> {config['portfolio']['rebalance']} rebalancing; one-way turnover cost: "
        f"{config['portfolio']['transaction_cost_bps']:.1f} bps.",
        "> The sample covers QLD's full common live history. The pre- and post-2022 data "
        "segments are validated over their overlap and linked at the splice date.",
        "",
        "## Bottom line",
        "",
        "The historical evidence does not support a universally optimal QQQ/QLD mix. Both funds "
        "track the same index, so combining them primarily selects a daily exposure between "
        "approximately 1x and 2x rather than adding diversification.",
        "Maximizing in-sample CAGR drives the allocation to 100% QLD, while maximizing Sharpe or "
        "Calmar drives it to 100% QQQ. Intermediate weights become meaningful when the investor "
        "specifies a volatility target or drawdown constraint.",
        "",
        "## The optimal allocation depends on the objective",
        "",
        "| Objective | QQQ | QLD | Effective daily exposure | CAGR | Volatility | "
        "Maximum drawdown | Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "max_cagr": "Maximum in-sample CAGR",
        "max_sharpe": "Maximum in-sample Sharpe",
        "max_calmar": "Maximum in-sample Calmar",
        "target_volatility": (
            f"Closest to {config['optimization']['target_volatility']:.0%} volatility"
        ),
        "max_cagr_with_drawdown_limit": (
            "Maximum CAGR with drawdown no worse than "
            f"{config['optimization']['max_drawdown_limit']:.0%}"
        ),
    }
    for key, row in selected.items():
        if row.empty:
            lines.append(f"| {labels[key]} | N/A | N/A | N/A | N/A | N/A | N/A | N/A |")
            continue
        w = float(row.name)
        lines.append(
            f"| {labels[key]} | {1 - w:.0%} | {w:.0%} | {1 + w:.2f}x | "
            f"{_pct(row['cagr'])} | {_pct(row['volatility'])} | "
            f"{_pct(row['max_drawdown'])} | {row['sharpe']:.2f} |"
        )
    q_low, q_med, q_high = bootstrap.quantile([0.05, 0.5, 0.95])
    lines += [
        "",
        "## Out-of-sample performance and stability",
        "",
        f"The expanding-window walk-forward strategy produced an out-of-sample CAGR of "
        f"**{_pct(oos['cagr'])}**, a Sharpe ratio of **{oos['sharpe']:.2f}**, and a maximum "
        f"drawdown of **{_pct(oos['max_drawdown'])}**.",
        "For each test year, the highest-Sharpe weight is selected using only information that "
        "was previously available, making this result more realistic than a full-sample optimum.",
        "",
        f"Across the moving-block bootstrap samples, the median highest-Sharpe QLD weight is "
        f"**{q_med:.0%}**, with a 5th–95th percentile range of "
        f"**{q_low:.0%}–{q_high:.0%}**. A wider interval indicates that the exact optimal "
        "percentage is less stable.",
        "",
        "## Interpretation limits",
        "",
        "The practical appeal of QQQ plus QLD is that two liquid ETFs can continuously adjust "
        "target daily Nasdaq-100 exposure from approximately 1x to 2x.",
        "However, the funds track the same index and do not diversify across asset classes. "
        "QLD resets daily, so long-horizon results depend on path, volatility, financing, fees, "
        "and tracking error.",
        "The table reports estimates for this historical window and these assumptions. It is not "
        "a forecast, a guarantee, or personalized investment advice.",
        "",
        "## Charts",
        "",
        "![Weight landscape](../assets/weight_landscape.png)",
        "",
        "![Growth of one](../assets/growth_of_one.png)",
        "",
        "![Drawdowns](../assets/drawdowns.png)",
        "",
        "![Bootstrap stability](../assets/bootstrap_weights.png)",
        "",
        "## Walk-forward annual selections",
        "",
        walk_table.to_markdown(index=False, floatfmt=".4f"),
        "",
    ]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
