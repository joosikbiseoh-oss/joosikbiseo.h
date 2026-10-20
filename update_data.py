"""Fetch the once-daily data published with the static site."""

import concurrent.futures
import datetime as dt
import json
import os
import tempfile
from pathlib import Path

import yfinance as yf

from market_data import TICKERS, fetch_market_snapshot, fetch_one
from nasdaq100 import NASDAQ100_COMPANIES

ROOT = Path(__file__).resolve().parent


def main():
    cache_dir = Path(tempfile.gettempdir()) / "stock-dashboard-yfinance"
    cache_dir.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache_dir))
    search_tickers = [ticker for ticker in NASDAQ100_COMPANIES if ticker not in TICKERS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(fetch_one, TICKERS))
        search_rows = list(pool.map(fetch_one, search_tickers))
    for ticker in [row["ticker"] for row in rows if row.get("error")]:
        rows[TICKERS.index(ticker)] = fetch_one(ticker)
    for ticker in [row["ticker"] for row in search_rows if row.get("error")]:
        search_rows[search_tickers.index(ticker)] = fetch_one(ticker)
    if not any(row.get("price") is not None for row in rows):
        raise RuntimeError("No stock prices were received; keeping the previous published data.")
    result = {
        "rows": rows,
        "search_rows": search_rows,
        **fetch_market_snapshot(),
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "state": "ready",
    }
    (ROOT / "data.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    priced = sum(row.get("price") is not None for row in rows)
    searchable_priced = sum(row.get("price") is not None for row in search_rows)
    print(f"Updated {priced}/{len(rows)} default and {searchable_priced}/{len(search_rows)} searchable stock prices plus market indexes")


if __name__ == "__main__":
    main()

