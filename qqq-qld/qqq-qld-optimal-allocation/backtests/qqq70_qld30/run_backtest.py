"""Generate the dedicated 70% QQQ / 30% QLD backtest report."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from qqq_qld.backtest import portfolio_returns  # noqa: E402
from qqq_qld.data import download_prices, prices_to_returns  # noqa: E402
from qqq_qld.metrics import drawdown, performance_metrics  # noqa: E402

STRATEGIES = {
    "70% QQQ / 30% QLD": 0.30,
    "100% QQQ": 0.00,
    "100% QLD": 1.00,
}


def _strategy_returns(returns: pd.DataFrame, rebalance: str, cost_bps: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            name: portfolio_returns(
                returns,
                weight_qld=weight,
                rebalance=rebalance,
                transaction_cost_bps=cost_bps,
            )
            for name, weight in STRATEGIES.items()
        }
    )


def _summary_table(strategy_returns: pd.DataFrame, risk_free_rate: float) -> pd.DataFrame:
    rows = []
    for strategy, series in strategy_returns.items():
        metrics = performance_metrics(series, risk_free_rate)
        rows.append(
            {
                "strategy": strategy,
                "qqq_weight": 1.0 - STRATEGIES[strategy],
                "qld_weight": STRATEGIES[strategy],
                "effective_daily_exposure": 1.0 + STRATEGIES[strategy],
                **metrics,
            }
        )
    return pd.DataFrame(rows).set_index("strategy")


def _period_returns(strategy_returns: pd.DataFrame, frequency: str) -> pd.DataFrame:
    periods = strategy_returns.index.to_period(frequency)
    out = (1.0 + strategy_returns).groupby(periods).prod() - 1.0
    out.index = out.index.astype(str)
    out.index.name = "period"
    return out


def _drawdown_episodes(returns: pd.Series) -> pd.DataFrame:
    dd = drawdown(returns)
    underwater = dd < 0
    starts = np.flatnonzero(underwater.to_numpy() & ~underwater.shift(fill_value=False).to_numpy())
    ends = np.flatnonzero(~underwater.to_numpy() & underwater.shift(fill_value=False).to_numpy())
    rows: list[dict[str, object]] = []

    for start in starts:
        later_ends = ends[ends > start]
        recovered = len(later_ends) > 0
        end = int(later_ends[0]) if recovered else len(dd) - 1
        episode = dd.iloc[start : end + 1]
        trough_date = episode.idxmin()
        rows.append(
            {
                "peak_date": dd.index[max(start - 1, 0)].date(),
                "trough_date": trough_date.date(),
                "recovery_date": dd.index[end].date() if recovered else "Not recovered",
                "max_drawdown": float(episode.min()),
                "trading_days_to_trough": int(dd.index.get_loc(trough_date) - start + 1),
                "total_trading_days": int(end - start + 1),
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("max_drawdown").head(10).reset_index(drop=True)


def _save_figures(strategy_returns: pd.DataFrame, assets_dir: Path, initial_value: float) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    wealth = (1.0 + strategy_returns).cumprod() * initial_value
    fig, ax = plt.subplots(figsize=(10, 5.6))
    wealth.plot(ax=ax)
    ax.set_yscale("log")
    ax.set(title="Growth of $10,000 (log scale)", ylabel="Portfolio value ($)", xlabel="")
    fig.tight_layout()
    fig.savefig(assets_dir / "equity_curve.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.2))
    for name, series in strategy_returns.items():
        ax.plot(drawdown(series) * 100, label=name)
    ax.set(title="Portfolio drawdowns", ylabel="Drawdown (%)", xlabel="")
    ax.legend()
    fig.tight_layout()
    fig.savefig(assets_dir / "drawdowns.png", dpi=180)
    plt.close(fig)

    annual = _period_returns(strategy_returns, "Y") * 100
    fig, ax = plt.subplots(figsize=(11, 5.6))
    annual.plot(kind="bar", ax=ax, width=0.82)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set(title="Calendar-year returns", ylabel="Return (%)", xlabel="")
    ax.legend(ncol=3)
    fig.tight_layout()
    fig.savefig(assets_dir / "calendar_year_returns.png", dpi=180)
    plt.close(fig)


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _write_readme(
    strategy_returns: pd.DataFrame,
    summary: pd.DataFrame,
    annual: pd.DataFrame,
    episodes: pd.DataFrame,
    rebalance: str,
    cost_bps: float,
    initial_value: float,
) -> None:
    target = summary.loc["70% QQQ / 30% QLD"]
    target_returns = strategy_returns["70% QQQ / 30% QLD"]
    terminal_value = initial_value * float((1.0 + target_returns).prod())
    best_year = annual["70% QQQ / 30% QLD"].idxmax()
    worst_year = annual["70% QQQ / 30% QLD"].idxmin()
    best_return = annual.loc[best_year, "70% QQQ / 30% QLD"]
    worst_return = annual.loc[worst_year, "70% QQQ / 30% QLD"]

    display_summary = summary[
        ["cagr", "volatility", "sharpe", "sortino", "max_drawdown", "calmar", "terminal_multiple"]
    ].copy()
    for column in ["cagr", "volatility", "max_drawdown"]:
        display_summary[column] = display_summary[column].map(_pct)
    display_summary["sharpe"] = display_summary["sharpe"].map(lambda x: f"{x:.2f}")
    display_summary["sortino"] = display_summary["sortino"].map(lambda x: f"{x:.2f}")
    display_summary["calmar"] = display_summary["calmar"].map(lambda x: f"{x:.2f}")
    display_summary["terminal_multiple"] = display_summary["terminal_multiple"].map(
        lambda x: f"{x:.1f}x"
    )

    display_episodes = episodes.copy()
    if not display_episodes.empty:
        display_episodes["max_drawdown"] = display_episodes["max_drawdown"].map(_pct)

    lines = [
        "# 70% QQQ / 30% QLD Backtest",
        "",
        "This directory contains the dedicated, reproducible backtest for the author's stated "
        "allocation: **70% QQQ and 30% QLD**. It is a leveraged Nasdaq-100 position with an "
        "approximate target daily exposure of **1.30x**, not a diversified stock/bond portfolio.",
        "",
        "## Assumptions",
        "",
        f"- Full common history: {strategy_returns.index.min().date()} through "
        f"{strategy_returns.index.max().date()} ({len(strategy_returns):,} daily returns)",
        f"- Rebalancing: `{rebalance}` (month-end)",
        f"- One-way turnover cost: {cost_bps:.1f} bps",
        "- Dividends and fund expenses are reflected in the adjusted price series where available",
        "- No taxes, bid/ask spread, account restrictions, or investor cash flows",
        "",
        "## Full-period result",
        "",
        f"A ${initial_value:,.0f} initial investment grew to approximately "
        f"**${terminal_value:,.0f}**. "
        f"The strategy returned **{_pct(target['cagr'])} CAGR** with "
        f"**{_pct(target['volatility'])} annualized volatility** and a "
        f"**{_pct(target['max_drawdown'])} maximum drawdown**.",
        "",
        display_summary.to_markdown(),
        "",
        "## Calendar-year breakdown",
        "",
        f"The best calendar year was **{best_year}** ({_pct(best_return)}); "
        f"the worst was **{worst_year}** ({_pct(worst_return)}).",
        "",
        "The complete table is available in "
        "[`results/calendar_year_returns.csv`](results/calendar_year_returns.csv).",
        "",
        "## Largest drawdown episodes",
        "",
        (
            display_episodes.to_markdown(index=False)
            if not display_episodes.empty
            else "No drawdowns found."
        ),
        "",
        "## Charts",
        "",
        "![Equity curve](assets/equity_curve.png)",
        "",
        "![Drawdowns](assets/drawdowns.png)",
        "",
        "![Calendar-year returns](assets/calendar_year_returns.png)",
        "",
        "## Reproduce",
        "",
        "Run from the repository root:",
        "",
        "```bash",
        ".venv/bin/python backtests/qqq70_qld30/run_backtest.py",
        "```",
        "",
        "Generated files:",
        "",
        "- `results/summary_metrics.csv`",
        "- `results/calendar_year_returns.csv`",
        "- `results/monthly_returns.csv`",
        "- `results/largest_drawdowns.csv`",
        "- `assets/equity_curve.png`",
        "- `assets/drawdowns.png`",
        "- `assets/calendar_year_returns.png`",
        "",
        "## Risk notice",
        "",
        "QLD seeks 2x the **daily** Nasdaq-100 return. Daily reset, volatility, financing costs, "
        "fees, and path dependence can make long-horizon results differ substantially from a "
        "constant 1.30x index investment. Historical results are not a forecast. This research "
        "is for reference only and is not financial advice.",
        "",
    ]
    (BACKTEST_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    with (ROOT / "config" / "default.yaml").open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    data_cfg = config["data"]
    portfolio_cfg = config["portfolio"]
    risk_free_rate = config["optimization"]["annual_risk_free_rate"]
    prices = download_prices(
        data_cfg["tickers"],
        data_cfg["start"],
        data_cfg.get("end"),
        cache=ROOT / data_cfg["cache"],
        source=data_cfg.get("source", "hybrid"),
    )
    returns = prices_to_returns(prices)
    strategy_returns = _strategy_returns(
        returns,
        portfolio_cfg["rebalance"],
        portfolio_cfg["transaction_cost_bps"],
    )
    summary = _summary_table(strategy_returns, risk_free_rate)
    annual = _period_returns(strategy_returns, "Y")
    monthly = _period_returns(strategy_returns[["70% QQQ / 30% QLD"]], "M")
    episodes = _drawdown_episodes(strategy_returns["70% QQQ / 30% QLD"])

    results_dir = BACKTEST_DIR / "results"
    assets_dir = BACKTEST_DIR / "assets"
    results_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(results_dir / "summary_metrics.csv")
    annual.to_csv(results_dir / "calendar_year_returns.csv")
    monthly.to_csv(results_dir / "monthly_returns.csv")
    episodes.to_csv(results_dir / "largest_drawdowns.csv", index=False)
    _save_figures(strategy_returns, assets_dir, portfolio_cfg["initial_value"])
    _write_readme(
        strategy_returns,
        summary,
        annual,
        episodes,
        portfolio_cfg["rebalance"],
        portfolio_cfg["transaction_cost_bps"],
        portfolio_cfg["initial_value"],
    )
    print(f"70/30 backtest complete: {BACKTEST_DIR / 'README.md'}")


if __name__ == "__main__":
    main()
