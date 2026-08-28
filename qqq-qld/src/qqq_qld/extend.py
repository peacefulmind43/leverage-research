"""Reconstruct pre-2006 QQQ/QLD history from the underlying index.

QLD launched in June 2006, so this repository's sample begins after the two
worst episodes a leveraged Nasdaq position has ever faced: the 1987 crash and
the 2000-2002 unwind, in which the Nasdaq-100 fell roughly 83% peak to trough.
Every drawdown and constraint estimated on the live sample is therefore
estimated on a window that excludes the outcome those constraints exist to
guard against, and a maximum-drawdown limit fitted to it is not conservative --
it is uninformed.

The funds' mechanics are simple enough to reconstruct. QQQ is the index less an
expense ratio plus distributions; QLD is twice the index daily, less financing
on the borrowed notional and its own expense ratio. Both are simulated here
from the Nasdaq-100 and a contemporaneous short rate.

Two free parameters -- the index distribution yield and QLD's swap spread --
are *calibrated on the twenty-year live overlap* rather than assumed, and
:func:`calibration_report` states how closely the reconstruction then tracks
the real funds over that overlap. The reconstruction is only as trustworthy as
that fit, and it should be read as a stress scenario built from the real index
path, not as a claim about what these specific tickers would have returned.
"""

from __future__ import annotations

from io import StringIO

import numpy as np
import pandas as pd
import requests

from .costs import EXPENSE_RATIO_QLD, EXPENSE_RATIO_QQQ
from .metrics import TRADING_DAYS, drawdown

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
DEFAULT_INDEX = "^NDX"
DEFAULT_RATE_SERIES = "DTB3"


def download_risk_free(
    series_id: str = DEFAULT_RATE_SERIES,
    start: str = "1985-01-01",
    timeout: int = 30,
) -> pd.Series:
    """Daily annualised risk-free rate from FRED, as a decimal fraction.

    Defaults to the 3-month Treasury bill, the conventional proxy for the rate
    a swap counterparty finances at. FRED reports percent and leaves market
    holidays blank; both are handled here.
    """
    response = requests.get(FRED_CSV, params={"id": series_id, "cosd": start}, timeout=timeout)
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text), index_col=0, parse_dates=True)
    rate = pd.to_numeric(frame.iloc[:, 0], errors="coerce").ffill() / 100.0
    rate.name = series_id
    return rate.dropna()


def download_index(
    ticker: str = DEFAULT_INDEX,
    start: str = "1985-01-01",
    end: str | None = None,
) -> pd.Series:
    """Daily closes of the underlying price index."""
    import yfinance as yf

    raw = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError(f"No index history returned for {ticker}")
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna().astype(float).rename(ticker)


def _simulate(
    index_returns: pd.Series,
    risk_free: pd.Series,
    dividend_yield: float,
    swap_spread: float,
    expense_ratio_qqq: float,
    expense_ratio_qld: float,
) -> pd.DataFrame:
    """Simulate both funds' daily returns from index returns and a short rate."""
    rf = risk_free.reindex(index_returns.index).ffill().bfill()
    total = index_returns + dividend_yield / TRADING_DAYS
    qqq = total - expense_ratio_qqq / TRADING_DAYS
    qld = 2.0 * total - (rf + swap_spread) / TRADING_DAYS - expense_ratio_qld / TRADING_DAYS
    return pd.DataFrame({"QQQ": qqq, "QLD": qld})


def calibrate_synthetic(
    real_returns: pd.DataFrame,
    index_returns: pd.Series,
    risk_free: pd.Series,
    expense_ratio_qqq: float = EXPENSE_RATIO_QQQ,
    expense_ratio_qld: float = EXPENSE_RATIO_QLD,
) -> dict[str, float]:
    """Fit distribution yield and swap spread on the live overlap.

    Each parameter enters its own equation additively, so both have closed-form
    solutions from mean returns and no search is needed: the yield is whatever
    reconciles the index with QQQ, and the spread is then whatever reconciles
    twice the index with QLD.
    """
    common = real_returns.dropna().index.intersection(index_returns.dropna().index)
    if len(common) < TRADING_DAYS:
        raise ValueError("Need at least one year of overlap to calibrate")
    real = real_returns.loc[common]
    index = index_returns.loc[common]
    rf = risk_free.reindex(common).ffill().bfill()

    # QQQ = index + yield - ER  =>  yield = mean(QQQ - index) + ER
    dividend_yield = float((real["QQQ"] - index).mean() * TRADING_DAYS) + expense_ratio_qqq
    # QLD = 2*(index + yield) - (rf + spread) - ER  =>  spread from the residual
    total = index + dividend_yield / TRADING_DAYS
    residual = float((2.0 * total - real["QLD"]).mean() * TRADING_DAYS)
    swap_spread = residual - expense_ratio_qld - float(rf.mean())
    return {
        "dividend_yield": dividend_yield,
        "swap_spread": swap_spread,
        "overlap_start": str(common.min().date()),
        "overlap_end": str(common.max().date()),
        "overlap_years": len(common) / TRADING_DAYS,
    }


def calibration_report(
    real_returns: pd.DataFrame,
    index_returns: pd.Series,
    risk_free: pd.Series,
    calibration: dict[str, float],
    expense_ratio_qqq: float = EXPENSE_RATIO_QQQ,
    expense_ratio_qld: float = EXPENSE_RATIO_QLD,
) -> pd.DataFrame:
    """How closely the calibrated reconstruction tracks the real funds.

    Calibration matches mean returns by construction, so a small CAGR gap is
    weak evidence. The columns that carry information are the daily-return
    correlation and the tracking error: they say whether the reconstruction
    follows the same *path*, which is what a drawdown estimate depends on.
    """
    common = real_returns.dropna().index.intersection(index_returns.dropna().index)
    synthetic = _simulate(
        index_returns.loc[common],
        risk_free,
        calibration["dividend_yield"],
        calibration["swap_spread"],
        expense_ratio_qqq,
        expense_ratio_qld,
    )
    real = real_returns.loc[common]
    rows = []
    for column in ("QQQ", "QLD"):
        years = len(common) / TRADING_DAYS
        difference = synthetic[column] - real[column]
        rows.append(
            {
                "series": column,
                "real_cagr": float((1 + real[column]).prod() ** (1 / years) - 1),
                "synthetic_cagr": float((1 + synthetic[column]).prod() ** (1 / years) - 1),
                "correlation": float(synthetic[column].corr(real[column])),
                "tracking_error": float(difference.std(ddof=1) * np.sqrt(TRADING_DAYS)),
                "real_max_drawdown": float(drawdown(real[column]).min()),
                "synthetic_max_drawdown": float(drawdown(synthetic[column]).min()),
            }
        )
    return pd.DataFrame(rows).set_index("series")


def extend_history(
    real_returns: pd.DataFrame,
    index_returns: pd.Series,
    risk_free: pd.Series,
    calibration: dict[str, float] | None = None,
    expense_ratio_qqq: float = EXPENSE_RATIO_QQQ,
    expense_ratio_qld: float = EXPENSE_RATIO_QLD,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Splice reconstructed pre-inception returns onto the live fund history.

    Real returns always win where they exist; the reconstruction only fills the
    period before them. Returns the combined frame and the calibration used, so
    a report can state which portion of any result is simulated.
    """
    if calibration is None:
        calibration = calibrate_synthetic(
            real_returns, index_returns, risk_free, expense_ratio_qqq, expense_ratio_qld
        )
    splice = real_returns.dropna().index.min()
    early = index_returns.loc[index_returns.index < splice]
    if early.empty:
        raise ValueError("Index history does not predate the live fund history")
    synthetic = _simulate(
        early,
        risk_free,
        calibration["dividend_yield"],
        calibration["swap_spread"],
        expense_ratio_qqq,
        expense_ratio_qld,
    )
    combined = pd.concat([synthetic, real_returns.dropna()]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined, {**calibration, "splice_date": str(splice.date())}


def stress_episodes(
    returns: pd.DataFrame,
    weights: tuple[float, ...] = (0.0, 0.15, 0.3, 0.5, 1.0),
    episodes: dict[str, tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """Worst-case drawdown by QLD weight across named historical episodes.

    Reported per episode rather than only full-sample because the binding
    question for a leveraged position is not the average outcome but whether
    the worst realised path would have ended it.
    """
    from .backtest import portfolio_returns

    if episodes is None:
        episodes = {
            "1987 crash": ("1987-08-01", "1988-06-30"),
            "Dot-com 2000-2002": ("2000-03-01", "2002-12-31"),
            "GFC 2007-2009": ("2007-10-01", "2009-06-30"),
            "COVID 2020": ("2020-02-01", "2020-06-30"),
            "2022 rate shock": ("2022-01-01", "2022-12-31"),
            "Full sample": (str(returns.index.min().date()), str(returns.index.max().date())),
        }
    rows: list[dict[str, float | str]] = []
    for name, (start, end) in episodes.items():
        window = returns.loc[start:end]
        if len(window) < 20:
            continue
        row: dict[str, float | str] = {"episode": name, "start": start, "end": end}
        for weight in weights:
            series = portfolio_returns(window, weight_qld=weight, rebalance="ME")
            row[f"qld_{weight:.0%}"] = float(drawdown(series).min())
        rows.append(row)
    return pd.DataFrame(rows).set_index("episode")
