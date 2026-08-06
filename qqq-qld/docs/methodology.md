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
g_L \approx L\mu - \frac12L^2\sigma^2 - \text{financing} - \text{fees}.
\]

Leverage raises exposure to a positive drift, but the penalty grows roughly with the square of
leverage. Therefore an interior growth-optimal exposure can exist. Its location changes when drift,
volatility, financing cost, valuation, or market regime changes. Historical Nasdaq performance was
exceptionally strong and should not be treated as a known future mean.

`qqq_qld.optimize.kelly_optimal_leverage` estimates the full-Kelly leverage implied by this
approximation as \(L^*=\mu/\sigma^2\), using the sample's annualized QQQ excess arithmetic mean
and variance, ignoring the financing and fee terms above. It also reports the conventional
half-Kelly haircut (\(L^*/2\)), which is the standard practitioner response to estimation error in
\(\mu\) and \(\sigma^2\) rather than a distinct model. Both figures are reported alongside the
grid search in `results/summary.md`. Because \(\mu\) is estimated with much more noise than
\(\sigma^2\), and the admissible QQQ/QLD blend only spans 1x-2x exposure, this estimate should be
read as a directional check on whether 2x over- or undershoots the data's implied growth-optimal
exposure — not as a precise target.

### 6.1 A blend is not the same as a fixed-leverage position

`qqq_qld.optimize.kelly_implied_qld_weight` clips \(L^*-1\) into the achievable \([0,1]\) QLD
weight range so it can be read as a QQQ/QLD allocation. This mapping is only exact under one
specific condition: **daily rebalancing**. QLD's daily return is approximately \(2r_t\), where
\(r_t\) is QQQ's daily return. A blend with QLD weight \(w\), rebalanced to target every day,
therefore has daily return

\[
(1-w)\,r_t + w\,(2r_t) = (1+w)\,r_t,
\]

which is algebraically identical to a synthetic \((1+w)\)x daily-reset leveraged product. It is
*not* identical under less frequent rebalancing (this repository's default is monthly, `ME`):
between rebalance dates the QQQ and QLD legs compound independently, so the blend's realized
exposure drifts away from \(1+w\) rather than tracking it exactly — a smaller-scale version of
the same volatility-drag mechanism that makes QLD itself diverge from "2x QQQ" over multi-day
holding periods.

`qqq_qld.leverage` makes this concrete instead of leaving it as an assumption:

- `simulate_daily_reset_leverage` builds the idealized, frictionless synthetic \(L\)x product
  directly from actual discretized daily returns (rather than only the continuous-time \(g_L\)
  approximation above), so it captures real discretized volatility drag and serves as ground
  truth for a given \(L\).
- `rebalance_drag` backtests the real QQQ/QLD blend at a given weight and rebalancing frequency
  (via `qqq_qld.backtest.portfolio_returns`) against that synthetic benchmark, reporting the CAGR
  gap and return correlation between the two.
- `compare_rebalance_frequencies` holds the target weight fixed and varies only the rebalancing
  cadence, showing empirically how much cadence alone changes the outcome on this dataset.

`results/summary.md`'s Kelly section reports these comparisons at this repository's actual
configured rebalancing frequency, so the gap between "target exposure" and "realized exposure"
is shown rather than assumed away.

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
