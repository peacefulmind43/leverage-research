
# QQQ + QLD Optimal Leverage

This repository researches the optimal allocation between QQQ (unleveraged) and QLD (2x daily-reset)
on every available trading day from QLD's inception on June 19, 2006 through the latest completed
session. The pipeline runs a monthly-rebalanced backtest with transaction costs, an expanding-window
walk-forward validation, a moving-block bootstrap stability check, and a Kelly-criterion growth-rate
analysis — including a sensitivity table showing how the Kelly recommendation changes under
different assumed forward returns, since it should not be estimated from trailing performance alone.
Full output, including charts, lives in [`results/summary.md`](results/summary.md); the underlying
math and assumptions are documented in [`docs/methodology.md`](docs/methodology.md).

## Key findings

- **In-sample, different objectives disagree.** Maximizing CAGR pushes the allocation to 100% QLD
  (25.4% CAGR, but an 83.1% maximum drawdown); maximizing Sharpe or Calmar pushes it to 100% QQQ
  (16.7% CAGR, 53.4% maximum drawdown). A volatility- or drawdown-constrained investor lands
  somewhere around 84-86% QQQ / 14-16% QLD.
- **Out-of-sample, leverage does not pay off on this data.** The walk-forward test (selecting each
  year's weight using only prior data) and the moving-block bootstrap both independently select
  **0% QLD** as the highest-Sharpe allocation in almost every case — the in-sample case for QLD is
  considerably weaker once you stop using future information to choose past weights.
- **A blend is not a fixed leverage ratio, for two separate reasons.** QLD's real return only
  approximates 2x QQQ's (it embeds QLD's own expense ratio and financing spread), so a gap against
  a frictionless synthetic `(1+w)`x product persists even under daily rebalancing, proportional to
  QLD weight. Separately, at this repo's default monthly cadence the two legs also compound
  independently between rebalances, drifting exposure further from `1+w`. The second effect is
  empirically much smaller than the first on this dataset. See `qqq_qld.leverage` and methodology
  section 6.1.
- **The Kelly-implied leverage is extremely sensitive to the assumed forward return.** Using this
  sample's trailing return, full-Kelly implies up to 100% QLD. But that trailing return reflects an
  exceptional historical window, not a forecast, and Kelly leverage is far more sensitive to that
  assumption than to the (much better estimated) volatility term. Swapping in a more conservative,
  valuation-anchored forward-return assumption collapses the recommendation toward 0% QLD — in line
  with the out-of-sample evidence above. See the "Sensitivity to the assumed forward return" table
  in `results/summary.md` and methodology section 6.2.

There is no universally optimal allocation; the appropriate mix depends on the investor's objective,
risk tolerance, and — most importantly — an assumption about future returns that this backtest
cannot supply on its own.

## Usage

```bash
pip install -r requirements.txt -e .
python -m qqq_qld.cli --config config/default.yaml   # full run
python -m qqq_qld.cli --fast                          # quick run, fewer bootstrap samples
```

Edit `config/default.yaml` to change the rebalancing frequency, cost assumptions, or the
`optimization.mu_scenarios` forward-return assumptions used in the Kelly sensitivity table. Results
are written to `results/summary.md` and `assets/`.

A separate, detailed backtest of one specific allocation is in
[`backtests/qqq70_qld30`](backtests/qqq70_qld30).

This repository is provided for reference only. Not financial advice.
