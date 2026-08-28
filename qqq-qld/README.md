
# QQQ + QLD Optimal Leverage

This repository asks what target QLD weight is optimal in a long-only QQQ/QLD portfolio, and
treats that as what it actually is: a decision about how much to borrow, at a knowable price, to
buy an asset with an unknowable forward return.

The pipeline runs a rebalanced backtest with transaction costs, an expanding-window walk-forward,
a moving-block bootstrap, and a Kelly/CRRA growth analysis. Two things distinguish it from a
conventional weight sweep. It **estimates QLD's embedded borrowing rate from the funds' own return
histories** rather than assuming one, and it **reconstructs returns back to 1985** so the sample
contains the 1987 crash and the 2000-2002 unwind rather than beginning after them.

Full output lives in [`results/summary.md`](results/summary.md); the math and assumptions are in
[`docs/methodology.md`](docs/methodology.md).

## The number

**1.00x — that is, 0% QLD.** Not from risk aversion: this is full Kelly, `gamma = 1`, the
objective that maximises wealth and nothing else. At an all-in borrowing cost of 5.41% and a
crisis-inclusive volatility of 25.67%, the spread available to lever is simply too thin to pay for
the variance it buys.

Kelly is the right objective for a money-only question because its claim is a theorem rather than
a preference: a log-wealth maximiser almost surely ends up richer than any essentially different
strategy, and Kelly also maximises median terminal wealth. True risk *neutrality* is `gamma = 0`,
which prescribes unbounded leverage and certain ruin — so "only cares about money" cannot mean
maximising expected wealth; it has to mean maximising its growth rate.

Three estimators, in increasing order of realism, agree:

| Estimator | What it adds | Leverage |
|---|---|---:|
| Closed form `(mu-c)/(gamma*sigma^2)` | lognormal returns | 1.04x |
| Realised path | real fat tails (excess kurtosis ~8), path dependence | 0.99x |
| 30-year block bootstrap | finite horizon, median terminal wealth | 1.00x |

Raising `gamma` to 2 does not change the headline, but it changes its character: the unconstrained
optimum falls to 0.52x and 1.00x becomes a *boundary*. At `gamma = 1` it is an interior optimum —
a stronger result, and the one reported here.

Inverting the formula is more useful than arguing about the assumption, so the report also states
what each leverage level requires you to believe about forward returns:

| Leverage | QLD weight | Required return (γ=1) | (γ=1.5) | (γ=2) |
|---|---:|---:|---:|---:|
| 1.00x | 0% | 8.71% | 12.00% | 15.30% |
| 1.15x | 15% | 9.70% | 13.49% | 17.27% |
| 1.30x | 30% | 10.68% | 14.97% | 19.25% |
| 1.50x | 50% | 12.00% | 16.95% | 21.89% |
| 2.00x | 100% | 15.30% | 21.89% | 28.48% |

This sample realised 15.4% geometric over forty years, in the best-performing major index selected
with hindsight. Read the γ=1 column: **2.00x is growth-optimal if and only if forward returns
match that trailing figure**, and 1.30x needs 10.68%. So the recommendation is not really a claim
about leverage — it is a claim that forward Nasdaq-100 returns are nearer 9% than 15%, taken at a
financing cost the last forty years mostly did not charge. Disagree with that and the number
moves: μ of 12% gives 1.35x over a 30-year horizon, μ of 15.4% gives 1.95x. The repository
computes it either way; `results/horizon_wealth.csv` has the wealth distributions.

One asymmetry is worth noting because it is structural rather than psychological: near the
optimum, median terminal wealth is nearly flat while the 5th percentile falls away quickly. That
follows from the curvature of the growth function, and it argues for erring below a leverage
estimate rather than above it.

## Key findings

- **A leverage decision cannot be made with a ratio objective, and an earlier version of this
  README reported one as evidence.** Sharpe, Sortino and Calmar are scale-invariant in leverage:
  levering a single asset multiplies excess mean and standard deviation by the same factor, so the
  ratio is flat in the frictionless case and strictly falling once financing and fees are paid.
  The argmax over a leverage grid is therefore the lowest-leverage grid point *by construction*.
  The previous finding that walk-forward and bootstrap "both independently select 0% QLD" was this
  identity restated, not an out-of-sample result — the bootstrap's 0%–0% percentile band was a
  tautology reported as certainty. Selection now runs on expected log growth or a CRRA certainty
  equivalent, and the same bootstrap returns a genuinely wide 11%–100% band.

- **QLD lends at roughly the short rate plus 1.7%, and that number decides more than the weight
  does.** QLD's daily objective is exactly 2x the index, so the shortfall of its realised return
  against twice QQQ's identifies its embedded cost. Netting out QQQ's own expense ratio and a
  contemporaneous 3-month bill leaves a swap spread of about **1.16%**, stable in sign across
  sub-periods but wider under funding stress. Adding the fund-fee premium gives an all-in
  **effective borrowing rate near 5.4%** at current rates. That figure is directly comparable to a
  broker's quoted margin rate, and the comparison is the whole decision: below it, margin reaches
  the same exposure more cheaply; above it, the blend does — and the blend cannot be margin-called.

- **The fee premium is a closed form and does not depend on the weight.** Borrowing through the
  blend rather than on margin costs `ER_QLD - 2*ER_QQQ` per dollar borrowed — 0.55% per year at
  current expense ratios — at 90/10 and at 0/100 alike. Earlier versions described this gap only
  as "proportional to QLD weight", which is true of the total but obscures that the *rate* is
  constant and therefore quotable as a single number.

- **Excluding 2000-2002 was not a minor sampling limitation.** Reconstructed from the Nasdaq-100,
  the full history has almost the same mean return as the live sample (17.6% vs 17.8% arithmetic)
  but materially higher volatility (**25.7% vs 22.1%**). Because growth-optimal leverage divides by
  variance, that difference alone cuts full-Kelly leverage from 2.55x to **1.85x** without any
  change of view about returns. The reconstruction is calibrated on the twenty-year live overlap
  and reproduces the real funds' worst drawdown there to within 0.2 points (-82.97% vs -83.13%).

- **At full Kelly the drawdowns are not survivable, and the walk-forward shows it.** Through
  2000-2002 a 1.3x blend drew down **-91.5%** and a 2.0x blend **-98.8%**; the log-growth
  walk-forward, selecting honestly out of sample, still produced a **-98.2%** maximum drawdown.
  Recovering from -91.5% requires a 1076% gain. Full Kelly is log utility, which is not a
  preference any real portfolio holds; at a CRRA gamma of 2 the same data selects 0% QLD.

- **The recommendation is dominated by an assumption the backtest cannot supply.** Growth-optimal
  leverage is `(mu - c) / (gamma * sigma^2)` — driven by the *spread* of expected return over
  financing, a difference between two similar-sized numbers. Across forward-return assumptions
  that all look defensible, full-Kelly leverage ranges from 2.02x down to 0.13x. Capital-market
  assumptions are published as geometric returns and Kelly is defined on arithmetic means, so the
  pipeline converts between them; skipping that step understates mu by 3.3 points here.

There is no universally optimal allocation. The honest output of this repository is a price for
leverage, a variance estimate that includes the worst case, and an explicit statement of how much
the answer depends on a forward return nobody can estimate well.

## Usage

```bash
pip install -r requirements.txt -e .
python -m qqq_qld.cli --config config/default.yaml   # full run
python -m qqq_qld.cli --fast                          # quick run, fewer bootstrap samples
```

Edit `config/default.yaml` to change rebalancing, costs, CRRA `risk_aversion`, or the
`optimization.mu_scenarios` forward-return assumptions. Set `costs.benchmark_rate` to the current
short rate — the leverage recommendation moves with it. Set `extend.enabled: false` to revert to
QLD's live history alone, at the cost of dropping the worst episode from the sample. Results are
written to `results/summary.md` and `assets/`.

A separate, detailed backtest of one specific allocation is in
[`backtests/qqq70_qld30`](backtests/qqq70_qld30).

This repository is provided for reference only. Not financial advice.
