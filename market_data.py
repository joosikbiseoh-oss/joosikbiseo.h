"""Daily public stock data for the hosted dashboard."""

import concurrent.futures
import datetime as dt
import json
import math
import urllib.error
import urllib.request

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


def fetch_market_quote(key, symbol, name):
    """Fetch a latest close and previous-close change for a market index."""
    row = {"key": key, "symbol": symbol, "name": name, "price": None,
           "price_date": None, "change": None, "change_pct": None}
    try:
        history = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)
        if not history.empty:
            close = history["Close"].dropna()
            if len(close):
                row["price"] = number(close.iloc[-1])
                row["price_date"] = str(close.index[-1].date())
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

# SEC's public companyfacts endpoint provides reported diluted EPS. When Yahoo's
# annual P/E history is too sparse, pair those annual EPS facts with the last
# available closing price on or before each fiscal year-end.
SEC_CIKS = {
    "AAPL": "0000320193", "MSFT": "0000789019", "NVDA": "0001045810",
    "GOOGL": "0001652044", "META": "0001326801", "TSLA": "0001318605",
    "AVGO": "0001730168", "AMD": "0000002488", "ORCL": "0001341439",
    "CRWD": "0001535527", "PLTR": "0001321655", "AMZN": "0001018724",
    "MU": "0000723125", "INTC": "0000050863", "ASML": "0000937966",
}


def sec_json(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "JoosikBiseoH public market dashboard/1.0", "Accept-Encoding": "gzip, deflate"}
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read())


def add_sec_pe_fallback(stock, ticker, row):
    """Fill sparse Yahoo P/E averages from SEC annual diluted EPS facts."""
    if row.get("pe_avg5y_n", 0) >= 3 or ticker not in SEC_CIKS:
        return
    try:
        facts = sec_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{SEC_CIKS[ticker]}.json")
        eps_facts = facts.get("facts", {}).get("us-gaap", {}).get("EarningsPerShareDiluted", {}).get("units", {})
        observations = next((items for unit, items in eps_facts.items() if unit.lower() in ("usd/shares", "usd / shares")), [])
        if not observations:
            return

        # Prefer the latest reported version of each annual fact. This also
        # picks up later restatements where the company reported them.
        annual = {}
        today = dt.date.today()
        for fact in observations:
            if fact.get("form") != "10-K" or not fact.get("end") or not fact.get("start"):
                continue
            end = dt.date.fromisoformat(fact["end"])
            start = dt.date.fromisoformat(fact["start"])
            if end > today or not 300 <= (end - start).days <= 400:
                continue
            filed = fact.get("filed", "")
            if end not in annual or filed > annual[end].get("filed", ""):
                annual[end] = fact
        periods = sorted(annual.items())[-5:]
        if not periods:
            return

        history = stock.history(period="6y", interval="1d", auto_adjust=False)
        if history.empty:
            return
        closes = {}
        for index, close in history["Close"].dropna().items():
            closes[index.date()] = number(close)

        ratios = []
        for end, fact in periods:
            eps = number(fact.get("val"))
            # Loss-making years do not have a meaningful positive P/E multiple.
            if eps is None or eps <= 0:
                continue
            eligible = [day for day in closes if day <= end and (end - day).days <= 7]
            if not eligible:
                continue
            close = closes[max(eligible)]
            if close is not None and close > 0:
                ratios.append(close / eps)
        if ratios:
            row["pe_avg5y"] = round(sum(ratios) / len(ratios), 4)
            row["pe_avg5y_n"] = len(ratios)
    except Exception:
        # Keep the existing Yahoo values if SEC data is unavailable.
        return


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
           "above50": None, "ordered": None,
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
        add_sec_pe_fallback(stock, ticker, row)
    except Exception as exc:
        row["error"] = str(exc)[:180]
    return row

