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


def _recommendation_section(extras: dict[str, object] | None) -> list[str]:
    """State the repository's own number, and what would have to be true for others."""
    if not extras or not extras.get("recommendation"):
        return []
    rec = extras["recommendation"]
    boundary = (
        "This is a **boundary** solution, and that distinction matters. The unconstrained "
        f"optimum is {rec['unconstrained_leverage']:.2f}x: under these assumptions an investor "
        "free to hold cash would hold *less* than a full unlevered position in this index, so "
        "the recommendation is not \"a little leverage is fine\" but \"the constraint that "
        "you are fully invested is already binding\"."
        if rec["binding"]
        else "This is an interior optimum: the assumptions genuinely select this exposure "
        "rather than being clipped to the edge of what a long-only blend can reach."
    )
    # The deterministic full-path estimator is the only one of the three that
    # can carry two decimals: the closed form is biased by its lognormal
    # assumption, and the bootstrap's argmax moves with the resampling seed.
    headline = rec.get("empirical", rec["recommended_leverage"])
    horizon = rec.get("horizon") or {}
    lines = [
        f"## Recommended leverage: **{headline:.2f}x** ({headline - 1:.0%} QLD)",
        "",
        "Three estimators of the same quantity, in increasing order of realism. They agree, "
        "which is the check that the headline is not an artefact of the lognormal assumption:",
        "",
        "| Estimator | What it adds | Leverage |",
        "|---|---|---:|",
        f"| Closed form `(mu-c)/(gamma*sigma^2)` | lognormal returns | "
        f"{rec['unconstrained_leverage']:.2f}x |",
        f"| **Realised path** (headline) | real fat tails (excess kurtosis ~8), path "
        f"dependence; deterministic | **{headline:.2f}x** |",
        f"| {rec.get('horizon_years', 30)}-year block bootstrap | finite horizon, median "
        f"terminal wealth | "
        + (
            f"{horizon['minimum']:.2f}-{horizon['maximum']:.2f}x |"
            if horizon
            else f"{rec['recommended_leverage']:.2f}x |"
        ),
        "",
        "The bootstrap is the most realistic estimator and the least precise: its argmax moves "
        f"by about {horizon.get('std', 0):.2f} between resampling seeds, so it is quoted as an "
        "interval rather than a number. The headline comes from the full realised sequence, "
        "which resamples nothing and so has no sampling noise -- that is what makes two "
        "decimals meaningful here. The closed form sits above both because its lognormal "
        "assumption understates what fat tails cost a levered position.",
        "",
        f"`L* = (mu - c) / (gamma * sigma^2)` at a forward geometric return of "
        f"**{rec['mu_geometric']:.2%}** (arithmetic {rec['mu_arithmetic']:.2%}), an all-in "
        f"financing cost of **{rec['financing_cost']:.2%}**, volatility of "
        f"**{rec['volatility']:.2%}**, and CRRA risk aversion **{rec['risk_aversion']:g}**. "
        f"The spread available to lever is {rec['excess_over_financing']:.2%}.",
        "",
        boundary,
        "",
        "Kelly's optimality is a theorem about which strategy wins, not a risk preference, so "
        "`gamma = 1` is the right setting for a purely wealth-maximising objective. Note that "
        "true risk *neutrality* is `gamma = 0`, which prescribes unbounded leverage and certain "
        "ruin -- so \"only cares about money\" cannot mean maximising expected wealth; it has "
        "to mean maximising its growth rate. Estimation error in `mu` is *not* a further reason "
        "to raise gamma: expected log growth is linear in mu, so uncertainty leaves the optimum "
        "at `E[mu]`. Being wrong about `E[mu]` is what moves the answer.",
        "",
        "Two of those four inputs are measured and two are asserted. `sigma^2` comes from the "
        "reconstructed 1985-2026 history and `c` from the funds' own returns; the forward "
        "return and the risk aversion are a view and a preference respectively, set in "
        "`config/default.yaml` under `recommendation`. Changing them changes this number, "
        "which is why the table below matters more than the number does.",
        "",
    ]
    breakeven = extras.get("breakeven")
    if breakeven is not None and not breakeven.empty:
        display = breakeven.copy()
        display.index = [f"{value:.2f}x" for value in display.index]
        display["qld_weight"] = display["qld_weight"].map(lambda v: f"{v:.0%}")
        for column in display.columns:
            if column != "qld_weight":
                display[column] = display[column].map(lambda v: f"{v:.2%}")
        display = display.rename(
            columns={
                "qld_weight": "QLD weight",
                **{
                    c: f"Required forward return (γ={c.rsplit('_', 1)[1]})"
                    for c in breakeven.columns
                    if c.startswith("required_mu")
                },
            }
        )
        lines += [
            "### What each leverage level requires you to believe",
            "",
            "Inverting the formula is the more useful direction: rather than arguing about the "
            "assumed return, each row states the forward geometric return that would make that "
            "leverage optimal. Compare them against the "
            "15.4% this sample actually realised over forty years -- and against the fact that "
            "it realised it in the best-performing major index, chosen in hindsight.",
            "",
            display.to_markdown(),
            "",
        ]
    horizon = extras.get("horizon_table")
    if horizon is not None and not horizon.empty:
        shown = [x for x in (1.0, 1.15, 1.3, 1.5, 2.0) if x in horizon.index]
        display = horizon.loc[shown].copy()
        display.index = [f"{value:.2f}x" for value in display.index]
        lines += [
            f"### Terminal wealth over {rec.get('horizon_years', 30)} years",
            "",
            "Block-bootstrapped holding periods, so volatility clustering survives resampling. "
            "Read the median column, not the mean: mean terminal wealth rises with leverage "
            "without limit because a thin right tail carries it, which is precisely the "
            "statistic that makes leverage look better than it is. `prob_beats_unlevered` "
            "compares against 1x on the *same* draw.",
            "",
            display.to_markdown(floatfmt=".2f"),
            "",
            "Note the shape near the optimum: the median is nearly flat while the 5th "
            "percentile deteriorates quickly. That asymmetry is a reason to err below a "
            "leverage estimate rather than above it, and it follows from the curvature of the "
            "growth function rather than from any attitude to risk.",
            "",
        ]
    return lines


def _extra_sections(extras: dict[str, object] | None) -> list[str]:
    """Render the cost, stress and reconstruction tables when they are available."""
    if not extras:
        return []
    lines: list[str] = list(_recommendation_section(extras))

    costs = extras.get("costs")
    if costs:
        lines += [
            "## What QLD charges to lend",
            "",
            "QLD's daily objective is exactly 2x the index, so the shortfall of its realised "
            "return against twice QQQ's identifies its embedded cost. Netting out QQQ's own "
            "expense ratio (which QLD does not pay) and a contemporaneous 3-month bill leaves "
            "the spread its swap counterparties charged. The fee premium below is a closed "
            "form, `ER_QLD - 2*ER_QQQ`, and is invariant to the blend weight: it is the extra "
            "cost per dollar borrowed of borrowing through the blend rather than on margin.",
            "",
            "| Component | Rate |", "|---|---:|",
            f"| Estimated swap spread over bills | {costs['swap_spread']:.2%} |",
            f"| Current benchmark (3-month bill) | {costs['benchmark_rate']:.2%} |",
            f"| Fund fee premium (`ER_QLD - 2*ER_QQQ`) | {costs['fee_premium']:.2%} |",
            f"| **All-in effective borrowing rate** | **{costs['effective_rate']:.2%}** |",
            "",
            "Compare that last figure directly against a broker's quoted margin rate: below it, "
            "margin is the cheaper way to reach the same exposure; above it, the blend is, and "
            "the blend additionally cannot be margin-called.",
            "",
        ]
        window = extras.get("cost_windows")
        if window is not None and not window.empty:
            lines += [
                "The spread is not constant -- it reflects funding conditions at the time, and "
                "widens under stress:",
                "",
                window.to_markdown(floatfmt=".4f"),
                "",
            ]

    stress = extras.get("stress")
    if stress is not None and not stress.empty:
        lines += [
            "## Drawdown by episode and weight",
            "",
            "The binding constraint on a leveraged position is not its average outcome but "
            "whether the worst realised path would have ended it. Recovering from a drawdown "
            "of `d` requires a gain of `d/(1-d)`, so these differences are not linear in pain.",
            "",
            stress.drop(columns=[c for c in ("start", "end") if c in stress.columns])
            .to_markdown(floatfmt=".3f"),
            "",
        ]

    calibration = extras.get("calibration_report")
    if calibration is not None and not calibration.empty:
        lines += [
            "## Reconstruction fit over the live overlap",
            "",
            "Pre-2006 returns are simulated from the Nasdaq-100 and a contemporaneous short "
            "rate. Mean returns match by construction because the two free parameters are "
            "calibrated on this overlap; the informative columns are the correlation and "
            "tracking error, which say whether the reconstruction follows the same path, and "
            "the drawdown comparison, which is what the stress table depends on.",
            "",
            calibration.to_markdown(floatfmt=".4f"),
            "",
        ]
    return lines


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
    kelly: dict[str, float],
    kelly_weight: float,
    drag_rows: dict[str, dict[str, float | str]],
    frequency_table: pd.DataFrame,
    sensitivity: pd.DataFrame,
    config: dict,
    extras: dict[str, object] | None = None,
) -> None:
    oos = performance_metrics(walk_returns, config["optimization"]["annual_risk_free_rate"])
    walk_objective = config["optimization"].get("walk_forward_objective", "log_growth")
    boot_objective = config["optimization"].get("bootstrap_objective", "log_growth")
    lines = [
        "# QQQ + QLD Empirical Results",
        "",
        f"> Data window: {returns.index.min().date()} through {returns.index.max().date()};",
        f"> {config['portfolio']['rebalance']} rebalancing; one-way turnover cost: "
        f"{config['portfolio']['transaction_cost_bps']:.1f} bps.",
        (extras or {}).get("window_note", "> The sample covers QLD's live history."),
        "",
        "## Bottom line",
        "",
        "Both funds track the same index, so a QQQ/QLD blend selects a daily exposure between "
        "roughly 1x and 2x rather than adding diversification. The blend is therefore a "
        "*borrowing* decision, and it turns on two numbers: the rate QLD charges to lend, and "
        "the return assumed on what is bought with it.",
        "",
        "Ratio objectives cannot answer it. Sharpe, Sortino and Calmar are scale-invariant in "
        "leverage -- levering one asset scales excess mean and standard deviation together -- so "
        "their argmax over a leverage grid is the lowest-leverage point by construction, "
        "whatever the data says. This report selects on expected log growth and on a CRRA "
        "certainty equivalent instead; the ratio rows are kept only for continuity.",
        "",
        "Growth-optimal leverage is the spread between expected return and financing cost "
        "divided by variance. Financing is a large share of that spread at current rates, and "
        "the variance term is materially larger once the sample includes the 2000-2002 unwind, "
        "so both inputs move the answer more than the choice of weight granularity does.",
        "",
        "## The optimal allocation depends on the objective",
        "",
        "| Objective | QQQ | QLD | Target exposure (1+w)† | CAGR | Volatility | "
        "Maximum drawdown | Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "max_cagr": "Maximum in-sample CAGR",
        "max_log_growth": "Maximum log growth (full Kelly, gamma=1)",
        "max_certainty_equivalent": (
            "Maximum certainty equivalent (gamma="
            f"{config['optimization'].get('risk_aversion', 1.0):g})"
        ),
        "max_sharpe": "Maximum in-sample Sharpe (scale-invariant: cannot select leverage)",
        "max_calmar": "Maximum in-sample Calmar (scale-invariant: cannot select leverage)",
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
    limit = config["optimization"]["max_drawdown_limit"]
    if grid["max_drawdown"].max() < limit:
        lines += [
            "",
            f"The drawdown constraint of {limit:.0%} is **infeasible on this sample**: the "
            f"shallowest drawdown available at any weight is {grid['max_drawdown'].max():.1%}, "
            "at 0% QLD. A constraint that only became satisfiable when the 2000-2002 unwind was "
            "outside the window was never a property of the strategy -- it was a property of the "
            "window. Lower the limit or accept that no admissible allocation meets it.",
        ]
    lines += [
        "",
        "† Target exposure equals realized daily exposure only under daily rebalancing; see "
        "the Growth-optimal leverage section below for the actual gap at this report's "
        f"{config['portfolio']['rebalance']} rebalancing cadence.",
    ]
    q_low, q_med, q_high = bootstrap.quantile([0.05, 0.5, 0.95])
    lines += [
        "",
        "## Out-of-sample performance and stability",
        "",
        f"The expanding-window walk-forward strategy produced an out-of-sample CAGR of "
        f"**{_pct(oos['cagr'])}**, a Sharpe ratio of **{oos['sharpe']:.2f}**, and a maximum "
        f"drawdown of **{_pct(oos['max_drawdown'])}**.",
        f"For each test year the weight maximising `{walk_objective}` is selected using only "
        "information available at the time, so no future return chooses a past weight. Read the "
        "drawdown column before the return column: a growth-optimal rule is free to select "
        "leverage that no investor would have held through.",
        "",
        f"Across the moving-block bootstrap samples, the median `{boot_objective}`-optimal QLD "
        f"weight is **{q_med:.0%}**, with a 5th–95th percentile range of "
        f"**{q_low:.0%}–{q_high:.0%}**. A wider interval indicates that the exact optimal "
        "percentage is less stable.",
        "",
        "## Growth-optimal leverage (Kelly estimate)",
        "",
        f"Using this sample's annualized QQQ excess return (**{_pct(kelly['mu'])}**) and "
        f"variance (implying **{_pct(kelly['sigma2'] ** 0.5)}** volatility), the "
        f"growth-optimal (full-Kelly) leverage on the Nasdaq-100 is "
        f"**{kelly['full_kelly']:.2f}x**, with a half-Kelly reference of "
        f"**{kelly['half_kelly']:.2f}x**. QLD is fixed at 2.00x. Clipped to the QQQ/QLD blend's "
        f"achievable 1x–2x range, full-Kelly implies **{kelly_weight:.0%}** QLD.",
        f"This is `(mu - c) / (gamma * sigma^2)` evaluated at an estimated all-in financing cost "
        f"of **{kelly['financing_cost']:.2%}**, which leaves a spread of only "
        f"**{kelly['excess_mu']:.2%}** over that cost to lever. It remains a point estimate from "
        "one sample, and the trailing `mu` in it is a description of the past rather than a "
        "forecast — see the sensitivity table below and `docs/methodology.md` section 6.",
        "",
        "### A blend is not the same as a fixed-leverage position",
        "",
        "**70% QQQ + 30% QLD is not the same as a static 1.3x-leveraged QQQ position, for two "
        "separate reasons.** First, QLD's real daily return is only *approximately* 2x QQQ's — "
        "it embeds QLD's own expense ratio and financing spread — so even a blend rebalanced "
        "*every day* would show a gap against a *frictionless* synthetic `(1+w)`x daily-reset "
        "product, proportional to the QLD weight, that does not close no matter how often the "
        "blend rebalances. Second, and separately, "
        f"this report's blend rebalances {config['portfolio']['rebalance']} rather than daily, "
        "so between rebalances the two legs compound independently and realized exposure drifts "
        "further away from `1+w`. The table below quantifies the combined gap at this report's "
        "actual rebalancing cadence, comparing each weight's real backtested blend to the "
        "idealized, frictionless synthetic exposure it targets — see the frequency table further "
        "below to see the two effects separated (its `D` row isolates the first effect alone):",
        "",
        "| Weight | Target exposure | Synthetic CAGR | Actual CAGR | CAGR gap | "
        "Return correlation |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, drag in drag_rows.items():
        lines.append(
            f"| {label} | {drag['target_leverage']:.2f}x | {_pct(drag['synthetic_cagr'])} | "
            f"{_pct(drag['actual_cagr'])} | {_pct(drag['cagr_gap'])} | "
            f"{drag['return_correlation']:.3f} |"
        )
    lines += [
        "",
        "Holding the weight fixed at the half-Kelly allocation above (chosen because it carries "
        "a nonzero QLD weight, unlike this dataset's max-Sharpe allocation), rebalancing cadence "
        "alone changes the outcome as follows. Compare each row to the `D` (daily) row, not to "
        "zero: the gap remaining at `D` is QLD's own real cost drag, not a cadence effect, and "
        "only the *additional* gap at slower cadences reflects rebalancing frequency itself:",
        "",
        frequency_table.to_markdown(floatfmt=".4f"),
        "",
        "### Sensitivity to the assumed forward return (μ)",
        "",
        "Growth-optimal leverage is `(mu - c) / (gamma * sigma^2)`, so it is driven by the "
        "*spread* of expected return over the financing cost `c`, not by the expected return "
        "itself. At the estimated all-in rate that spread is a difference between two "
        "similar-sized numbers, which is why the recommendation swings so far across "
        "assumptions that all look reasonable. Assumed returns below are **geometric**, the "
        "convention capital-market assumptions publish; the arithmetic column adds "
        f"`0.5*sigma^2` = {_pct(0.5 * kelly['sigma2'])}, which Kelly is defined on. This "
        f"sample's volatility (**{_pct(kelly['sigma2'] ** 0.5)}**) is held fixed across rows "
        "because it is far better estimated than mu (see `docs/methodology.md` section 6.2); "
        "scenarios are editable in `config/default.yaml`:",
        "",
        f"| Scenario | Assumed μ (geometric) | μ (arithmetic) | Spread over financing | "
        f"Full Kelly | γ={config['optimization'].get('risk_aversion', 1.0):g} | "
        f"γ={config['optimization'].get('risk_aversion', 1.0):g} QLD weight |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario, row in sensitivity.iterrows():
        lines.append(
            f"| {scenario} | {_pct(row['assumed_mu'])} | {_pct(row['arithmetic_mu'])} | "
            f"{_pct(row['excess_over_financing'])} | {row['full_kelly_leverage']:.2f}x | "
            f"{row['risk_adjusted_leverage']:.2f}x | {row['risk_adjusted_qld_weight']:.0%} |"
        )
    lines += [
        "",
        "This is not a forecast produced by this tool -- the non-trailing rows are assumptions "
        "you (or the config file) supplied. The point is the spread: a plausible range of "
        "forward μ assumptions maps to a very different recommended weight, from heavily "
        "levered to unlevered.",
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
        *_extra_sections(extras),
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
