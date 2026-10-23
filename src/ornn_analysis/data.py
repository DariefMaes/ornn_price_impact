"""Download data from the three sources (Ornn, Census, Yahoo Finance) and cache it locally for a day.

Every loader returns a pd.Series indexed by date (oldest first).
"""
import io
import time
from urllib.parse import quote

import pandas as pd
import requests
import yfinance as yf

from .config import CACHE_DIR, env

ORNN_API = "https://api.ornnai.com/api/gpu/{gpu}"


def _cached(name: str, fetch) -> pd.Series:
    """Reuse a download from the last 24 hours; otherwise fetch and save it."""
    path = CACHE_DIR / f"{name.replace(' ', '_').replace('/', '_')}.parquet"
    if path.exists() and time.time() - path.stat().st_mtime < 24 * 3600:
        return pd.read_parquet(path).iloc[:, 0]
    s = fetch()
    s.name = name
    path.parent.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(path)
    return s


def _clean(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    s.index = pd.to_datetime(s.index, utc=True).tz_convert(None).normalize()
    s = s.dropna().sort_index()
    return s[~s.index.duplicated(keep="last")]


# ---------------------------------------------------------------- Ornn

def _ornn_get(path: str, params: dict) -> list[dict]:
    resp = requests.get(path, headers={"Authorization": f"Bearer {env('ORNN_API_KEY')}"}, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()["data"]


def _ornn_history(gpu: str, start: str, granularity: str, chunk_days: int) -> pd.DataFrame:
    """The API returns at most 500 points per request, so long ranges are fetched in chunks."""
    rows = []
    for chunk_start in pd.date_range(start, pd.Timestamp.today(), freq=f"{chunk_days}D"):
        rows += _ornn_get(ORNN_API.format(gpu=quote(gpu)) + "/history-simple", {
            "startDate": chunk_start.strftime("%Y-%m-%d"),
            "endDate": (chunk_start + pd.Timedelta(days=chunk_days - 1)).strftime("%Y-%m-%d"),
            "granularity": granularity, "limit": 500})
    return pd.DataFrame(rows)


def load_ornn(gpu: str, start: str = "2024-01-01") -> pd.Series:
    """Daily Ornn price index in $/GPU-hour."""
    return _cached(f"ornn_{gpu}", lambda: _clean(
        _ornn_history(gpu, start, "daily", 90).set_index("timestamp")["index_value"]))


def load_ornn_hourly(gpu: str, start: str = "2024-05-28") -> pd.Series:
    """Hourly Ornn price index (UTC). 20-day chunks = 480 points, under the 500 limit."""
    def fetch():
        s = _ornn_history(gpu, start, "hourly", 20).set_index("timestamp")["index_value"]
        s.index = pd.to_datetime(s.index, utc=True).tz_convert(None).floor("h")
        s = pd.to_numeric(s).sort_index()
        return s[~s.index.duplicated(keep="last")]
    return _cached(f"ornn_hourly_{gpu}", fetch)


def load_ornn_utilization(gpu: str, start: str = "2024-01-01") -> pd.Series:
    """Daily share of Ornn's tracked capacity that is rented (0 to 1)."""
    def fetch():
        rows = _ornn_get(ORNN_API.format(gpu=quote(gpu)) + "/volume-metrics", {
            "startDate": start, "endDate": pd.Timestamp.today().strftime("%Y-%m-%d"),
            "granularity": "daily", "limit": 10000})
        return _clean(pd.DataFrame(rows).set_index("recorded_at")["utilization_ratio"])
    return _cached(f"ornn_util_{gpu}", fetch)


def load_ornn_memory(memory_id: str) -> pd.Series:
    """Daily Ornn memory spot price in $ (e.g. mem_ddr5_16gb). List of ids: GET /api/memory-types."""
    def fetch():
        rows = _ornn_get(f"https://api.ornnai.com/api/memory/{quote(memory_id)}/history", {"limit": 10000})
        return _clean(pd.DataFrame(rows).set_index("date")["price"])
    return _cached(f"ornn_memory_{memory_id}", fetch)


# ---------------------------------------------------------------- Census

def load_census_construction(column: str = "Data center") -> pd.Series:
    """Monthly US private construction spending (Census C30), $ millions, seasonally adjusted
    annual rate: the value of construction work done in each month (not cumulative).
    Source: https://www.census.gov/construction/c30/xls/privsatime.xlsx
    Latest months are preliminary/revised ('p'/'r' in the source) and get revised."""
    def fetch():
        resp = requests.get("https://www.census.gov/construction/c30/xls/privsatime.xlsx", timeout=60)
        resp.raise_for_status()
        raw = pd.read_excel(io.BytesIO(resp.content), header=None)
        header_row = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Date"][0]
        df = raw.iloc[header_row + 1:].copy()
        df.columns = [str(c).strip() for c in raw.iloc[header_row]]
        df = df[df["Date"].astype(str).str.match(r"^[A-Z][a-z]{2}-\d{2}")]
        dates = pd.to_datetime(df["Date"].astype(str).str[:6], format="%b-%y")
        return _clean(pd.Series(df[column].values, index=dates))
    return _cached(f"census_{column}", fetch)


# ---------------------------------------------------------------- Yahoo Finance

def load_yahoo(ticker: str) -> pd.Series:
    """Daily closing price of a stock, index, future or yield (e.g. ^TNX = 10-year yield in %)."""
    def fetch():
        close = yf.download(ticker, start="2023-01-01", auto_adjust=True, progress=False)["Close"]
        return _clean(close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close)
    return _cached(f"yahoo_{ticker}", fetch)


def load_yahoo_hourly(ticker: str) -> pd.Series:
    """Hourly closes (UTC) for the last ~730 days, the most Yahoo provides at this resolution."""
    def fetch():
        close = yf.download(ticker, period="730d", interval="1h", auto_adjust=True, progress=False)["Close"]
        close = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
        close.index = close.index.tz_convert("UTC").tz_localize(None).floor("h")
        return close[~close.index.duplicated(keep="last")].dropna()
    return _cached(f"yahoo_hourly_{ticker}", fetch)


LOADERS = {"ornn": load_ornn, "census": load_census_construction, "yahoo": load_yahoo}
