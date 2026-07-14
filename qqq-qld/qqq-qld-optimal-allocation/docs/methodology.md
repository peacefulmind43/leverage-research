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
