"""Market-data download and validation."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf


def download_prices(
    tickers: list[str],
    start: str,
    end: str | None = None,
    cache: str | Path | None = None,
    refresh: bool = False,
    source: str = "yahoo",
) -> pd.DataFrame:
    """Download daily prices from Yahoo Finance or Nasdaq.

    A local CSV cache makes reruns deterministic until ``refresh=True`` is used.
    The common-date intersection is deliberate: a mixed portfolio cannot be
    implemented before every requested fund exists.
    """
    cache_path = Path(cache) if cache else None
    if cache_path and cache_path.exists() and not refresh:
        prices = pd.read_csv(cache_path, index_col=0, parse_dates=True)
    else:
        if source.lower() == "yahoo":
            prices = _download_yahoo(tickers, start, end)
        elif source.lower() == "nasdaq":
            prices = _download_nasdaq(tickers, start, end)
        elif source.lower() == "hybrid":
            prices = _download_hybrid(tickers, start, end)
        else:
            raise ValueError("source must be 'hybrid', 'yahoo', or 'nasdaq'")
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            prices.to_csv(cache_path)

    prices = prices.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    prices = prices[~prices.index.duplicated(keep="last")].sort_index()
    _validate_prices(prices, tickers)
    return prices


def _download_yahoo(tickers: list[str], start: str, end: str | None) -> pd.DataFrame:
    """Yahoo adjusted closes, including distributions when the service is available."""
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("Yahoo returned no prices. It may be temporarily rate limited.")
    if isinstance(raw.columns, pd.MultiIndex):
        field = "Adj Close" if "Adj Close" in raw.columns.get_level_values(0) else "Close"
        prices = raw[field].copy()
    else:
        field = "Adj Close" if "Adj Close" in raw.columns else "Close"
        prices = raw[[field]].copy()
        prices.columns = tickers
    return prices.reindex(columns=tickers)


def _download_nasdaq(tickers: list[str], start: str, end: str | None) -> pd.DataFrame:
    """Nasdaq public historical closes (split-adjusted, distributions excluded).

    Nasdaq's public endpoint generally caps the returned history at about ten
    years. This limitation is surfaced in the methodology and generated report.
    """
    end_date = pd.Timestamp.today().date() if end is None else pd.Timestamp(end).date()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; qqq-qld-research/1.0)",
        "Accept": "application/json, text/plain, */*",
    }
    series: dict[str, pd.Series] = {}
    for ticker in tickers:
        url = f"https://api.nasdaq.com/api/quote/{ticker}/historical"
        response = requests.get(
            url,
            params={
                "assetclass": "etf",
                "fromdate": start,
                "todate": str(end_date),
                "limit": 5000,
            },
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rows = ((payload.get("data") or {}).get("tradesTable") or {}).get("rows") or []
        if not rows:
            raise RuntimeError(f"Nasdaq returned no rows for {ticker}")
        frame = pd.DataFrame(rows)
        dates = pd.to_datetime(frame["date"], errors="coerce")
        closes = pd.to_numeric(
            frame["close"]
            .astype(str)
            .str.replace("$", "", regex=False)
            .str.replace(",", "", regex=False),
            errors="coerce",
        )
        series[ticker] = pd.Series(closes.to_numpy(), index=dates, name=ticker)
    return pd.concat(series, axis=1).sort_index()


def _nasdaq_dividends(ticker: str) -> pd.Series:
    """Return Nasdaq cash distributions indexed by ex-dividend date."""
    url = f"https://api.nasdaq.com/api/quote/{ticker}/dividends"
    response = requests.get(
        url,
        params={"assetclass": "etf"},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; qqq-qld-research/1.0)",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=30,
    )
    response.raise_for_status()
    rows = (((response.json().get("data") or {}).get("dividends") or {}).get("rows")) or []
    if not rows:
        return pd.Series(dtype=float, name=ticker)
    frame = pd.DataFrame(rows)
    dates = pd.to_datetime(frame["exOrEffDate"], errors="coerce")
    amounts = pd.to_numeric(
        frame["amount"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False),
        errors="coerce",
    )
    return pd.Series(amounts.to_numpy(), index=dates, name=ticker).dropna()


def _download_hybrid(tickers: list[str], start: str, end: str | None) -> pd.DataFrame:
    """Build full QLD-era total-return histories from two auditable sources.

    TuringTrader's open backfill files provide a continuous, distribution-adjusted
    series through 2022-02-11. Nasdaq official split-adjusted closes extend it to
    the present. Nasdaq cash distributions are reinvested where available (QQQ).
    The overlapping histories are linked at the final TuringTrader observation.
    """
    backfills: dict[str, pd.Series] = {}
    for ticker in tickers:
        url = (
            "https://raw.githubusercontent.com/fbertram/TuringTrader/master/"
            f"Data/backfills/{ticker}.csv"
        )
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        frame = pd.read_csv(StringIO(response.text), parse_dates=["Date"])
        series = frame.set_index("Date")["Close"].astype(float).sort_index()
        backfills[ticker] = series.loc[pd.Timestamp(start) :]

    base = pd.concat(backfills, axis=1).dropna(how="any")
    official = _download_nasdaq(tickers, start, end)
    combined: dict[str, pd.Series] = {}

    for ticker in tickers:
        history = base[ticker]
        cutoff = history.index.max()
        market = official[ticker].dropna().sort_index()
        if cutoff not in market.index:
            raise RuntimeError(f"No Nasdaq overlap at splice date for {ticker}: {cutoff.date()}")
        market_returns = market.pct_change(fill_method=None)
        dividends = _nasdaq_dividends(ticker)
        for ex_date, amount in dividends.items():
            if ex_date > cutoff and ex_date in market_returns.index:
                previous = market.shift(1).loc[ex_date]
                market_returns.loc[ex_date] += float(amount) / float(previous)
        tail_returns = market_returns.loc[market_returns.index > cutoff]
        tail = float(history.iloc[-1]) * (1.0 + tail_returns).cumprod()
        combined[ticker] = pd.concat([history, tail])

    prices = pd.concat(combined, axis=1).dropna(how="any")
    if end is not None:
        prices = prices.loc[: pd.Timestamp(end)]
    return prices


def _validate_prices(prices: pd.DataFrame, tickers: list[str]) -> None:
    missing = set(tickers) - set(prices.columns)
    if missing:
        raise ValueError(f"Missing ticker columns: {sorted(missing)}")
    if len(prices) < 252:
        raise ValueError("Fewer than 252 common daily observations; sample is too short.")
    if prices.isna().any().any() or (prices <= 0).any().any():
        raise ValueError("Prices must be complete and strictly positive.")


def prices_to_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Convert adjusted closes to simple daily total returns."""
    return prices.pct_change(fill_method=None).dropna(how="any")
