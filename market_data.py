"""Daily public stock data for the hosted dashboard."""

import concurrent.futures
import math

import yfinance as yf

TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "TSLA", "AVGO", "AMD", "ORCL", "CRWD", "SPCX", "PLTR", "AMZN", "MU", "INTC", "ASML"]
MARKET_INDEXES = [
    ("sp500", "^GSPC", "S&P 500"),
    ("nasdaq", "^IXIC", "나스닥 종합"),
    ("dow", "^DJI", "다우존스"),
]
VIX_INDEX = ("vix", "^VIX", "VIX")
COMPANIES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOGL": "Alphabet",
    "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom", "AMD": "AMD",
    "ORCL": "Oracle", "CRWD": "CrowdStrike", "SPCX": "SpaceX", "PLTR": "Palantir",
    "AMZN": "Amazon",
    "MU": "Micron Technology", "INTC": "Intel", "ASML": "ASML",
}


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def chart_series(close):
    return [[str(index.date()), round(value, 4)] for index, raw in close.items()
            if (value := number(raw)) is not None]


def fetch_market_quote(key, symbol, name):
    """Fetch a latest close and previous-close change for a market index."""
    row = {"key": key, "symbol": symbol, "name": name, "price": None,
           "price_date": None, "change": None, "change_pct": None,
           "drawdown_pct": None, "chart": []}
    try:
        history = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=False)
        if not history.empty:
            close = history["Close"].dropna()
            row["chart"] = chart_series(close.tail(252))
            if len(close):
                row["price"] = number(close.iloc[-1])
                row["price_date"] = str(close.index[-1].date())
                peak = number(close.max())
                if row["price"] is not None and peak and peak > 0:
                    row["drawdown_pct"] = round(max(0, (1 - row["price"] / peak) * 100), 2)
            if len(close) >= 2:
                previous = number(close.iloc[-2])
                row["change"] = round(row["price"] - previous, 4) if row["price"] is not None and previous is not None else None
                row["change_pct"] = row["change"] / previous if row["change"] is not None and previous else None
    except Exception as exc:
        row["error"] = str(exc)[:180]
    return row


def fetch_market_snapshot():
    """Fetch the three U.S. market indexes and VIX for the header."""
    quotes = [*MARKET_INDEXES, VIX_INDEX]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda item: fetch_market_quote(*item), quotes))
    return {"indices": rows[:len(MARKET_INDEXES)], "vix": rows[-1]}


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
           "change": None, "change_pct": None, "market_cap": None,
           "chart": [], "drawdown_pct": None,
           "ordered": None,
           "pe": None, "forward_pe": None, "psr": None, "pbr": None, "fcf": None,
           "dividend_yield": None, "pe_avg5y": None, "pe_avg5y_n": 0,
           "forward_pe_avg5y": None, "forward_pe_avg5y_n": 0,
           "psr_avg5y": None, "psr_avg5y_n": 0,
           "pbr_avg5y": None, "pbr_avg5y_n": 0}
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(period="max", interval="1d", auto_adjust=False)
        if not history.empty:
            close = history["Close"].dropna()
            row["chart"] = chart_series(close.tail(252))
            row["price"] = number(close.iloc[-1])
            row["price_date"] = str(close.index[-1].date())
            peak = number(close.max())
            if row["price"] is not None and peak and peak > 0:
                row["drawdown_pct"] = round(max(0, (1 - row["price"] / peak) * 100), 2)
            if len(close) >= 2:
                previous_close = number(close.iloc[-2])
                row["change"] = round(row["price"] - previous_close, 4)
                row["change_pct"] = row["change"] / previous_close if previous_close else None
            averages = {n: number(close.tail(n).mean()) if len(close) >= n else None
                        for n in (20, 60, 120, 200)}
            if all(averages[n] is not None for n in (20, 60, 120, 200)):
                row["ordered"] = averages[20] > averages[60] > averages[120] > averages[200]
        info = stock.info or {}
        market_cap = number(info.get("marketCap"))
        row["market_cap"] = round(market_cap / 1_000_000_000, 2) if market_cap is not None else None
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

