# Methodology

## 1. Research question

For a long-only portfolio invested only in QQQ and QLD, what target QLD weight would have been
optimal under a specified objective? The admissible set is:

\[
w_{QQQ}=1-w,\qquad w_{QLD}=w,\qquad 0\leq w\leq1.
\]

Because QQQ targets roughly 1x and QLD targets 2x of the same Nasdaq-100 benchmark on a daily
basis, the portfolio's instantaneous target exposure is approximately \(1+w\). This identity is
an exposure intuition, not a promise about multi-day returns.

## 2. Data

- The default sample covers QLD's entire live history from June 2006 to the latest completed session.
- Through 2022-02-11, it uses the open TuringTrader QQQ/QLD backfill series. After QLD's
  inception, those files track the live funds and provide continuous distribution-adjusted values.
- From 2022-02-14 onward, the series is extended with Nasdaq's official split-adjusted closes.
  Nasdaq cash distributions are reinvested for QQQ. Nasdaq does not expose QLD distributions;
  QLD's distribution yield is small, so the residual understatement is minor but non-zero.
- Over the source overlap, daily-return correlation is approximately 0.99983 for QQQ and 0.999999
  for QLD. Each Nasdaq tail is scaled to the final backfill value, preventing a splice jump.
- Set `source: yahoo` for Yahoo adjusted closes, which include splits and cash distributions, when
  that service is available and not rate limited.
- Only common trading dates are retained. A CSV cache records the exact dataset used for a run but
  is excluded from Git because redistributing vendor data may violate provider terms.

Production decisions should still be cross-checked against official fund NAV histories or a licensed
total-return dataset. The backtest never subtracts published expense ratios separately because fund
prices/NAVs are already net of fund operating expenses.

### 2.1 Reconstructing pre-inception history

QLD launched in June 2006. The live sample therefore begins *after* the two worst episodes a
leveraged Nasdaq position has faced — the 1987 crash and the 2000-2002 unwind, in which the
Nasdaq-100 fell roughly 83% peak to trough. Every drawdown estimate, and every drawdown
*constraint* calibrated against one, was previously fitted on a window that excluded the outcome
such constraints exist to guard against.

`qqq_qld.extend` reconstructs the missing period from the Nasdaq-100 and a contemporaneous
3-month Treasury bill, using the funds' published mechanics: QQQ is the index plus distributions
less its expense ratio; QLD is twice the index daily, less financing on the borrowed notional and
its own expense ratio. The two free parameters — index distribution yield and QLD's swap spread —
are **calibrated on the twenty-year live overlap**, not assumed, and each has a closed-form
solution because it enters its own equation additively.

Calibration matches mean returns by construction, so a small CAGR gap is weak evidence. The
reported checks that carry information are the daily-return correlation, the tracking error, and
the maximum-drawdown comparison — the last because the drawdown table is what the reconstruction
exists to produce. Over the overlap the reconstruction reproduces both funds' worst drawdowns to
within about 0.2 percentage points.

This remains a simulation of the *index* path, not a claim about what these tickers would have
returned had they existed. Treat pre-2006 figures as a stress scenario built from a real price
history, and note that `extend.enabled: false` reverts every result to the live window.

## 3. Portfolio mechanics

The default strategy targets a fixed QLD weight and rebalances at month end. Between rebalances,
weights drift with market returns. At each rebalance, one-way turnover is

\[
\text{turnover}_t=\frac12\sum_i |w_i^*-w_{i,t^-}|.
\]

The default implementation cost is 2 basis points times one-way turnover. Taxes, bid/ask spread
variation, market impact, account restrictions, and borrowing constraints are not modeled.

## 4. “Optimal” definitions

The grid searches QLD weights from 0% to 100% in 1-point increments and reports:

1. maximum in-sample CAGR;
2. maximum in-sample Sharpe ratio;
3. maximum in-sample Calmar ratio;
4. the allocation closest to a chosen annual volatility target;
5. maximum CAGR among allocations satisfying a maximum-drawdown constraint.

These are different optimization problems and are expected to produce different answers. The
risk-free rate defaults to zero so the result does not silently depend on a current cash yield;
change it in `config/default.yaml` for a different assumption.

### 4.1 Why Sharpe, Sortino and Calmar cannot select leverage

A QQQ/QLD blend does not choose *between* assets; it chooses how much of one asset to hold. For
that problem the reward-to-risk ratios are degenerate. Levering a single asset by \(L\) scales
both the excess mean and the standard deviation by \(L\), so

\[
\text{Sharpe}(L)=\frac{L(\mu-r)}{L\sigma}=\text{Sharpe}(1),
\]

leaving the ratio unchanged in the frictionless case, and strictly *decreasing* in \(L\) once
financing and fees are subtracted from the numerator but not the denominator. The argmax of such
an objective over a leverage grid is the lowest-leverage grid point, for every dataset, with no
dependence on the data at all.

This matters because the degeneracy is invisible in the output: a walk-forward that selects the
same minimum weight every year, and a bootstrap whose 5th and 95th percentiles coincide, both
*look* like unusually strong and stable evidence. Earlier versions of this repository reported
exactly that pattern as an out-of-sample finding against leverage. It was an identity.

`qqq_qld.optimize.SCALE_INVARIANT_OBJECTIVES` names these objectives and the walk-forward and
bootstrap now warn when one is passed. Selection defaults to `log_growth`; the ratio columns are
retained for continuity and comparability, not as leverage recommendations.

### 4.2 Log growth and the CRRA certainty equivalent

Expected log growth is the objective Kelly maximises and is not scale-invariant: it rises with
leverage while the drift term dominates and falls once the variance penalty takes over, so it has
an interior optimum that genuinely depends on the data.

Log growth corresponds to log utility, i.e. CRRA \(\gamma=1\), which is not a realistic
preference for a real portfolio — on this sample it selects allocations whose historical drawdowns
approach total loss. `qqq_qld.metrics.crra_certainty_equivalent` generalises it to

\[
\text{CE}(\gamma)=g-\tfrac12(\gamma-1)\sigma^{2},
\]

so fractional Kelly arises as the optimum under a stated risk preference rather than as an
unexplained haircut. Half-Kelly is exactly \(\gamma=2\). Individual investors are usually
calibrated between 2 and 4; the value is set in `config/default.yaml`.

## 4.3 What QLD charges to lend

A blend is a way of borrowing, so its cost is comparable to a margin rate and `qqq_qld.costs`
estimates it rather than assuming it. Because QLD's daily objective is exactly 2x the index, its
observed return satisfies

\[
r_{QLD}=2r_{QQQ}+\bigl(2\,\text{ER}_{QQQ}-\text{ER}_{QLD}-\text{financing}\bigr),
\]

where the \(2\,\text{ER}_{QQQ}\) term appears because doubling QQQ's *net* return
double-counts an expense ratio QLD does not pay. Every term but the financing rate is published,
so subtracting a contemporaneous benchmark from the residual identifies the spread QLD's swap
counterparties charge. The slope is fixed at 2.0 rather than estimated, because the prospectus
defines it; a free-slope regression is reported separately as a diagnostic, and a slope far from
2.0 would mean the intercept is contaminated.

Comparing the blend against margin at the same exposure gives a result that is invariant to how
much leverage is taken:

\[
c_{\text{margin}}=c_{\text{swap}}+\bigl(\text{ER}_{QLD}-2\,\text{ER}_{QQQ}\bigr).
\]

The weight cancels, so the fee penalty per dollar borrowed — 0.55% per year at current expense
ratios — is the same at any allocation and can be quoted as a single number. Note the estimate
inherits any bias in the return data: distributions missing from a data source after the splice
date depress QLD's measured return and inflate the implied spread, so period-by-period estimates
should be read alongside `docs/methodology.md` section 2 on data provenance.

## 5. Validation against overfitting

### Walk-forward

After an initial five-year training period, each calendar year's QLD weight is selected using only
prior data. The next year is then held out as the test set. The training window expands, and test
periods never overlap. This is still a historical simulation, but it avoids using future returns to
choose past weights.

### Moving-block bootstrap

Twenty-one-day blocks are sampled with replacement. For each synthetic history, the QLD weight
with the highest Sharpe ratio is recorded. The distribution measures estimation instability. For
computational efficiency, this diagnostic uses a daily-rebalanced return mixture and ignores tiny
periodic trading costs; the main grid and walk-forward engine use the full monthly mechanics.

## 6. Why leverage can help—and hurt

For an idealized daily-reset leveraged exposure \(L\), a continuous-time approximation to expected
log growth contains a volatility penalty:

\[
g(L) \approx L\mu - (L-1)c - \tfrac12\gamma L^2\sigma^2,
\qquad
L^{*}=\frac{\mu-c}{\gamma\sigma^{2}},
\]

where \(c\) is the all-in financing cost per dollar borrowed and \(\gamma\) is CRRA risk
aversion.

Leverage raises exposure to a positive drift, but the penalty grows roughly with the square of
leverage. Therefore an interior growth-optimal exposure can exist. Its location changes when drift,
volatility, financing cost, valuation, or market regime changes. Historical Nasdaq performance was
exceptionally strong and should not be treated as a known future mean.

**The financing cost belongs in the numerator, and omitting it is not a conservative
simplification.** Leverage buys \(\mu\) but pays \(c\) for it, so the quantity being levered is
the spread \(\mu-c\). Setting \(c=0\) prices the borrowing at zero and inflates \(L^*\) by
\(c/\sigma^2\) — on this sample, more than a full turn of leverage. Earlier versions of this
repository did exactly that, and reported a full-Kelly figure above 3.6x as a result.
`qqq_qld.optimize.kelly_optimal_leverage` now takes `financing_cost` explicitly; for a QQQ/QLD
blend it should be the effective rate derived in section 4.3, and for a margin position the
broker's quoted rate.

Note also that \(\mu\) here is an *arithmetic* mean, while published capital-market assumptions
are geometric. The two differ by \(\tfrac12\sigma^2\), which is over three percentage points at
this sample's volatility — a large error in a numerator that is itself a difference of two
similar-sized numbers. `kelly_sensitivity` converts geometric inputs by default. It also reports the conventional
half-Kelly haircut (\(L^*/2\)), which is the standard practitioner response to estimation error in
\(\mu\) and \(\sigma^2\) rather than a distinct model. Both figures are reported alongside the
grid search in `results/summary.md`. Because \(\mu\) is estimated with much more noise than
\(\sigma^2\), and the admissible QQQ/QLD blend only spans 1x-2x exposure, this estimate should be
read as a directional check on whether 2x over- or undershoots the data's implied growth-optimal
exposure — not as a precise target.

### 6.1 A blend is not the same as a fixed-leverage position

`qqq_qld.optimize.kelly_implied_qld_weight` clips \(L^*-1\) into the achievable \([0,1]\) QLD
weight range so it can be read as a QQQ/QLD allocation. This mapping is an idealization with two
separate sources of error, which are easy to conflate:

**QLD is a real fund, not literally \(2r_t\).** QLD's daily return is only *approximately*
\(2r_t\), where \(r_t\) is QQQ's daily return — the real fund's return is \(2r_t\) minus its own
daily expense-ratio and financing-spread drag on the leveraged notional. The algebraic identity

\[
(1-w)\,r_t + w\,(2r_t) = (1+w)\,r_t,
\]

which makes a QLD-weight-\(w\) blend rebalanced daily *exactly* equal to a synthetic
\((1+w)\)x daily-reset product, only holds for this idealized \(2r_t\), not for QLD's real
return. Substituting the real fund's return, a daily-rebalanced blend already carries a gap
against a *frictionless* synthetic \((1+w)\)x product, proportional to \(w\), that does not
close no matter how often the blend rebalances.

**Rebalancing cadence adds a second, separate effect.** Independent of the point above, this
repository's default monthly (`ME`) cadence lets the QQQ/QLD weight drift between rebalance
dates rather than tracking \(1+w\) continuously — a smaller-scale version of the same
volatility-drag mechanism that makes QLD itself diverge from "2x QQQ" over multi-day holding
periods. This is the effect that daily rebalancing specifically would reduce; it is empirically
much smaller than the first effect on this dataset (see below).

`qqq_qld.leverage` makes this concrete instead of leaving it as an assumption:

- `simulate_daily_reset_leverage` builds the idealized, frictionless synthetic \(L\)x product
  directly from actual discretized daily returns (rather than only the continuous-time \(g_L\)
  approximation above), so it captures real discretized volatility drag and serves as ground
  truth for a given \(L\).
- `rebalance_drag` backtests the real QQQ/QLD blend at a given weight and rebalancing frequency
  (via `qqq_qld.backtest.portfolio_returns`) against that frictionless synthetic benchmark,
  reporting the CAGR gap and return correlation between the two. Because the synthetic omits
  QLD's own real costs, this gap bundles both effects above — it is not purely a cadence
  measurement.
- `compare_rebalance_frequencies` holds the target weight fixed and varies only the rebalancing
  cadence. Its `D` (daily) row still carries the full real-cost effect; the *change* from that
  row to slower cadences is the cadence effect in isolation. On this dataset at a representative
  nonzero QLD weight, that incremental cadence effect is roughly an order of magnitude smaller
  than the real-cost baseline already present at daily cadence.

`results/summary.md`'s Kelly section reports these comparisons at this repository's actual
configured rebalancing frequency, so the gap between "target exposure" and "realized exposure"
is shown rather than assumed away — and shows the daily-cadence row alongside it specifically so
the real-cost baseline isn't mistaken for a cadence effect.

### 6.2 Why μ deserves the most scrutiny

`kelly_optimal_leverage` estimates μ as this sample's trailing annualized QQQ excess
arithmetic mean. That number describes the historical window; it is not a forecast, and
it deserves far more skepticism than σ² does when read as an input to a forward-looking
allocation decision. Three reasons:

- **μ is linear in the Kelly formula; σ² is not.** `L* = μ / σ²` moves one-for-one with
  μ but is only quadratically penalized by σ² in the underlying growth-rate
  approximation. Over any realistic sample length, the standard error on an annualized
  mean return is large relative to the mean itself, while realized variance is
  comparatively stable and persistent (volatility clusters and mean-reverts; average
  return does not). The least reliable input is the one the recommendation is most
  sensitive to.
- **A high current valuation is itself evidence that expected forward growth is
  already priced in.** Realizing a widely anticipated growth story (e.g. AI-driven
  earnings growth) does not by itself produce trailing-style excess returns once that
  anticipation is already reflected in the multiple an investor pays today. Forward
  return requires growth *beyond* what the current price already assumes, not merely
  the growth that is currently expected.
- **The dot-com precedent shows a real trend and a poor forward trade can coexist.**
  The internet turned out to be as transformative as its most bullish believers
  argued, yet many broad tech indices did not reclaim their 2000 valuations for over a
  decade. Being correct about the underlying technology and being correct about the
  price paid for it are different claims, and history has already run something close
  to this experiment once.

`qqq_qld.optimize.kelly_sensitivity` operationalizes this: it holds this sample's σ²
fixed (the more trustworthy estimate) and recomputes the implied Kelly
leverage/weight across a set of alternative, user-supplied forward μ assumptions,
configured in `config/default.yaml` under `optimization.mu_scenarios`. `results/summary.md`
reports this alongside the trailing-sample figure so the reader sees the spread of
plausible outcomes rather than one point estimate presented as if it were reliable.
This does not replace judgment about what μ to assume -- it makes the consequence of
that judgment explicit and adjustable.

## 7. Known limitations

- Survivorship/selection bias: QQQ and QLD are chosen after their success is known.
- The actual common history starts in 2006 and contains only a few major bear markets.
- Parameter uncertainty dominates false precision between nearby weights.
- QQQ and QLD are not diversifiers; both concentrate risk in the Nasdaq-100.
- QLD's daily objective creates path dependence and potential tracking differences over longer
  horizons.
- The backtest omits taxes and investor-specific constraints.
- Past performance does not guarantee future results. This repository is research, not investment
  advice.

## 8. Primary references

- [ProShares QLD official fund page](https://www.proshares.com/our-etfs/leveraged-and-inverse/qld)
- [ProShares QLD summary prospectus](https://www.proshares.com/globalassets/proshares/prospectuses/qld_summary_prospectus.pdf)
- [Invesco QQQ official fund page](https://www.invesco.com/qqq-etf/en/home.html)
- [SEC / Investor.gov leveraged and inverse ETF bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/sec)
- [TuringTrader backfill repository](https://github.com/fbertram/TuringTrader/tree/master/Data/backfills)
- [Nasdaq QQQ historical prices](https://www.nasdaq.com/market-activity/etf/qqq/historical)
