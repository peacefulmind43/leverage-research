# Leverage research

How much should a long-only investor borrow against an equity fund?
This repository answers that question for two funds, with the same method:

| Folder | Fund | How the leverage is bought |
|---|---|---|
| [`qqq-qld/`](qqq-qld/) | Nasdaq-100 (QQQ) | a blend of QQQ and QLD, a 2x daily fund |
| [`spmo/`](spmo/) | S&P 500 Momentum (SPMO) | broker margin at real tiered rates |

Each folder is a full project, with its own README, tests and results.

## The shared method

1. **Price the borrowing.** QLD's embedded borrowing rate is estimated from the
   two funds' own returns (about the short rate plus 1.7%). SPMO uses the
   broker's published margin tiers.
2. **Choose by growth, not by a ratio.** Sharpe, Sortino and Calmar do not change
   with leverage, so they cannot choose it. Both projects use Kelly (expected log
   growth), a CRRA certainty equivalent, and the bootstrap distribution of
   outcomes.
3. **Put the bad years in the sample.** QQQ/QLD returns are rebuilt back to 1985,
   so 1987 and 2000-02 are included. For SPMO, an early synthetic history was
   removed and replaced with the published index (see below).
4. **Report how much the answer moves, not only the answer.** The leverage depends
   on the forward return, which history cannot estimate well. Both projects show
   how the answer changes when that input changes.

## What each project found

**QQQ/QLD:** across 45 input sets that each look reasonable, the growth-optimal
leverage runs from 0.89x to 1.92x. The range is the result. A point
estimate (1.23x) is given only with that range. In 2000-02 a 1.3x blend fell
91.5%.

**SPMO:** an audit of my own first answer found three errors, all in favour of
leverage. The fund's alpha was mostly momentum-factor exposure (t = 1.16).
Interest accrued only on trading days, not every calendar day, so it was about 30% too low.
The pre-2015 history was synthetic. The synthetic history is now gone, and
all results use the real S&P 500 Momentum Index. That data starts in 2016 for
now, so the SPMO results are **preliminary**. Its README explains what is
missing.

## Run

Python 3.11 or newer. Each project installs and tests on its own:

```bash
cd spmo      # or: cd qqq-qld
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Continuous integration runs both test suites on every push.

## Not financial advice

This is personal research. Nothing here is a recommendation to borrow.
