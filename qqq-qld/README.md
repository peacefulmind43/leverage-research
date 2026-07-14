
# QQQ + QLD Optimal Leverage

This repository analyses every available trading day from QLD's inception on June 19, 2006,
through July 13, 2026 to estimate the optimal allocation between QQQ and QLD. The backtest includes
monthly rebalancing, transaction costs, walk forward validation, and block bootstrap testing. In
this sample, 100% QLD produced the highest CAGR (25.4%) but also suffered an 83.1% maximum
drawdown, while 100% QQQ delivered the strongest risk adjusted performance. A more balanced
allocation of approximately 84% QQQ and 16% QLD returned 18.3% annually with a maximum drawdown
near 60%. There is no universally optimal allocation; the appropriate mix depends on the
investor's objective and risk tolerance.

This repository is provided for reference only. A detailed backtest of my favorite allocation is
available in [`backtests/qqq70_qld30`](backtests/qqq70_qld30). Not Financial Advice.
