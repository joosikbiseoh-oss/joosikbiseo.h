"""Daily public stock data for the hosted dashboard."""

import math

import yfinance as yf

TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "TSLA", "AVGO", "AMD", "ORCL", "CRWD", "SPCX", "PLTR"]
COMPANIES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOGL": "Alphabet",
    "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom", "AMD": "AMD",
    "ORCL": "Oracle", "CRWD": "CrowdStrike", "SPCX": "SpaceX", "PLTR": "Palantir",
}


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


VALUATION_HISTORY = {
    "pe": "Trailing P/E",
    "forward_pe": "Forward P/E",
    "psr": "Price/Sales",
    "pbr": "Price/Book",
}


def add_valuation_averages(stock, row):
    """Add averages of Yahoo's available annual valuation history (up to five years)."""
    try:
        measures = stock.get_valuation_measures(freq="yearly", periods=5)
        if measures is None or measures.empty:
            return
        for key, label in VALUATION_HISTORY.items():
            values = []
            if label in measures.index:
                for column in measures.columns:
                    if str(column).lower() == "current":
                        continue
                    value = number(measures.loc[label, column])
                    if value is not None and value > 0:
                        values.append(value)
            row[f"{key}_avg5y"] = round(sum(values) / len(values), 4) if values else None
            row[f"{key}_avg5y_n"] = len(values)
    except Exception:
        # Current data remains useful if historical valuation history is unavailable.
        return


def fetch_one(ticker):
    row = {"ticker": ticker, "name": COMPANIES[ticker], "price": None, "price_date": None,
           "change": None, "change_pct": None, "above50": None, "ordered": None,
           "pe": None, "forward_pe": None, "psr": None, "pbr": None, "fcf": None,
           "dividend_yield": None, "pe_avg5y": None, "pe_avg5y_n": 0,
           "forward_pe_avg5y": None, "forward_pe_avg5y_n": 0,
           "psr_avg5y": None, "psr_avg5y_n": 0,
           "pbr_avg5y": None, "pbr_avg5y_n": 0}
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(period="1y", interval="1d", auto_adjust=False)
        if not history.empty:
            close = history["Close"].dropna()
            row["price"] = number(close.iloc[-1])
            row["price_date"] = str(close.index[-1].date())
            if len(close) >= 2:
                previous_close = number(close.iloc[-2])
                row["change"] = round(row["price"] - previous_close, 4)
                row["change_pct"] = row["change"] / previous_close if previous_close else None
            averages = {n: number(close.tail(n).mean()) if len(close) >= n else None
                        for n in (20, 50, 60, 120, 200)}
            if averages[50] is not None and row["price"] is not None:
                row["above50"] = row["price"] > averages[50]
            if all(averages[n] is not None for n in (20, 60, 120, 200)):
                row["ordered"] = averages[20] > averages[60] > averages[120] > averages[200]
        info = stock.info or {}
        row["pe"] = number(info.get("trailingPE"))
        row["forward_pe"] = number(info.get("forwardPE"))
        row["psr"] = number(info.get("priceToSalesTrailing12Months"))
        row["pbr"] = number(info.get("priceToBook"))
        fcf = number(info.get("freeCashflow"))
        row["fcf"] = round(fcf / 1_000_000_000, 2) if fcf is not None else None
        row["dividend_yield"] = number(info.get("trailingAnnualDividendYield"))
        if row["dividend_yield"] is None:
            row["dividend_yield"] = number(info.get("dividendYield"))
        add_valuation_averages(stock, row)
    except Exception as exc:
        row["error"] = str(exc)[:180]
    return row

