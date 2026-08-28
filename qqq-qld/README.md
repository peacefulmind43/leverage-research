
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

## The number: 0.89x to 1.92x, point estimate 1.23x

**The range is the finding. The point estimate is not, and should not be relied on as one.** The
recommendation is a deterministic function of four inputs, one of which — the forward return —
cannot be estimated from any quantity of history. Across 45 combinations of values that are each
individually defensible, the answer spans a factor of 2.2. The point estimate sits at the 42nd
percentile of that region, which is reported because an earlier revision of this repository sat at
the extreme low corner and called it a recommendation; landing near the middle is the check that a
correction has recentred rather than swapped one extreme for the other.

Within that framing: **1.23x — about 23% QLD / 77% QQQ** — at full Kelly, `gamma = 1`, the
objective that maximises wealth and nothing else, since Kelly's dominance is a theorem rather than
a preference. (True risk *neutrality* is `gamma = 0`, which prescribes unbounded leverage and
certain ruin, so "only cares about money" has to mean maximising the growth rate, not expected
wealth.)

### How to actually run it

The full decision sequence, with live numbers, is the **"What to actually do"** section at the top
of [`results/summary.md`](results/summary.md); it is generated from the config, so editing the
assumptions edits the instructions. In short:

1. **Compare two borrowing rates.** The blend charges 5.41% all-in. Look up the margin rate your
   broker would actually charge at your balance and take the cheaper — but note the blend cannot be
   margin-called, and at low leverage the gap is small either way.
2. **Pick the leverage from your own return view**, using the required-return table. The point
   estimate is a default, not a finding.
3. **Cap it at about 1.3x.** Past there, median wealth falls *and* the tail worsens. This holds
   across the whole input range, unlike the exact figure below it.
4. **Set the rebalancing band by account type:** ±3 points of QLD weight in a sheltered account,
   ±20 or wider in a taxable one — and if you are still contributing, rebalance with new money
   instead, which costs no realised gain at all.
5. **Re-run when rates move.** One point on the financing rate is worth about 0.18x of leverage.

And price the path first: through 2000-2002 this allocation drew down **90%**, needing an 890% gain
to recover. Every figure here assumes you hold through that. If you would have sold, the honest
adjustment is less leverage, not more tolerance.

### What is measured and what is asserted

Confidence in the parts of this analysis is very unequal, and the parts are separable:

| Claim | Basis | Confidence |
|---|---|---|
| QLD's all-in borrowing rate ≈ benchmark + 1.71% | identified two independent ways from fund returns, agreeing to 0.001% | high |
| Reward-to-risk ratios cannot select leverage | algebraic identity; verified strictly monotone | high |
| Financing belongs in the Kelly numerator | algebra; omitting it inflated `L*` by `c/sigma^2` | high |
| A 1.3x blend drew down -91.5% through 2000-2002 | measured on a reconstruction validated to 0.2pp on drawdown | high |
| Median gain from 1x to the optimum ≈ 0.12%/yr | bootstrapped; robust across seeds and inputs | high |
| Forward volatility is 23.5% rather than 22.3% or 25.67% | a judgement about regime recurrence | low |
| Forward geometric return is 9.5% | an assumption; no method here estimates it | very low |
| Therefore `L*` = 1.23x | inherits the two rows above | **low** |

### On quoting decimals

The deterministic estimator on a 0.001 grid returns **1.235x**. That figure is *reproducible* to
three decimals and *accurate* to about ±0.5, and the gap between those two words is the whole
point:

| | Magnitude | What it does to the 3rd decimal |
|---|---|---|
| Input uncertainty (forward return ±2-3pp) | ±0.3 to ±0.5 | swamps it by 300-500x |
| Monthly rebalancing drift at a 23% target | ±0.005 | swamps it by 5x |
| Bootstrap resampling noise | ±0.02 | swamps it by 20x |

Realised exposure at a 23% QLD target wanders between 1.204x and 1.249x under monthly
rebalancing, so the third decimal is not merely unknowable — it is not *holdable*. Return and
financing cost have equal and opposite derivatives (both `1/sigma^2`, about 18 per unit here),
since only their spread matters; the return dominates because it is known far less precisely, not
because the answer is more sensitive to it.

The closed form is also biased about 0.1x high against daily rebalancing — verified on lognormal
returns where the analytic answer is exact by construction — which is why the headline comes from
the realised-path estimator rather than the formula.

| Estimator | What it adds | Leverage |
|---|---|---:|
| Closed form `(mu-c)/(gamma*sigma^2)` | lognormal returns | 1.31x |
| **Realised path** (headline) | fat tails, path dependence; deterministic | **1.23x** |
| 30-year block bootstrap | finite horizon, median terminal wealth | 1.20–1.27x |

The headline is the deterministic estimator by design. The closed form sits high because its
lognormal assumption understates what excess kurtosis near 8 costs a levered position, and the
bootstrap's argmax moves about 0.02 between resampling seeds, so neither can carry two decimals.

Inputs: forward geometric return 9.5%, volatility 23.5%, all-in financing 5.01%. Volatility is
*not* the full-sample 25.67% — that figure is carried almost entirely by 1995-2002, which realised
38.9%, while every other era in the sample runs 18.8-22.6% and the post-2003 index has done 22.3%
through the GFC, COVID and 2022. Financing is built on the long-run short rate rather than today's
spot, because a multi-decade holder pays the average future rate.

### But leverage buys much less here than it looks like it should

This is the part worth internalising, and it is why "just hold QQQ" is not a silly answer:

| Leverage | Median wealth (30y) | vs 1x, annualised | 5th percentile | vs 1x |
|---|---:|---:|---:|---:|
| 1.00x | 15.7x | — | 1.81x | — |
| 1.15x | 16.4x | +0.11%/yr | 1.36x | ×0.75 |
| 1.23x | ~16.5x | +0.12%/yr | ~1.15x | ×0.64 |
| 1.30x | 16.5x | +0.12%/yr | 0.99x | ×0.55 |
| 2.00x | 10.3x | −1.51%/yr | 0.12x | ×0.07 |

Moving from 1x to the growth optimum raises median terminal wealth by **about 0.12% per year** —
inside the noise of the return assumption that produced it — while the 5th percentile falls by a
third. The Kelly curve is flat at its peak and the left tail is not. That asymmetry is structural,
following from the curvature of the growth function rather than from any attitude to risk, and it
argues for erring below a leverage estimate rather than above it.

### Where the disagreement actually lives

Nothing above is robust to the forward return, and everything above is robust to the method:

| Leverage | Required forward return (γ=1) |
|---|---:|
| 1.00x | 7.77% |
| 1.15x | 8.60% |
| 1.30x | 9.43% |
| 1.50x | 10.53% |
| 2.00x | 13.29% |

So the recommendation is not really a claim about leverage. It is a claim that forward
Nasdaq-100 returns are nearer 9.5% than 15%. Believe 12% and the answer is 1.77x; believe the
trailing 15.4% and it is 2.38x, i.e. the whole admissible range and then some. `sensitivity_box()` reports the whole plausible region — **1.04x to
1.92x** — and that range, not the point estimate, is the honest output.

One methodological warning, learned the hard way in this repository's own history: each input has a
defensible conservative value and a defensible central one, and taking the conservative end of all
of them at once does not produce a conservative answer. It produces the corner of the plausible
region while looking like the centre. An earlier revision did exactly that and reported 1.00x.

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
