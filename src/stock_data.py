import os
import time
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

from src.cache_utils import load_from_cache, save_to_cache

load_dotenv()
api_key = os.getenv("ALPHAVANTAGE_API_KEY")
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"


class DataProviderError(RuntimeError):
    pass


def _request_json(params: dict[str, Any], timeout: int = 15, retries: int = 2):
    """Centralized Alpha Vantage request with timeout/retry/error handling."""
    if not api_key:
        raise DataProviderError("ALPHAVANTAGE_API_KEY is not configured.")

    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()

            if "Note" in data:
                raise DataProviderError(f"Alpha Vantage rate limit: {data['Note']}")
            if "Information" in data and not any(
                key in data
                for key in ("Time Series (Daily)", "Time Series (Digital Currency Daily)", "feed", "Symbol")
            ):
                raise DataProviderError(data["Information"])
            if "Error Message" in data:
                raise DataProviderError(data["Error Message"])

            return data
        except (requests.RequestException, ValueError, DataProviderError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))

    raise DataProviderError(str(last_error))


def get_daily_stock_data(symbol, outputsize="compact"):
    cache_key = f"{symbol}_daily_price_{outputsize}"
    cached_data = load_from_cache(cache_key, max_age_hours=20)
    if cached_data is not None:
        return cached_data

    try:
        data = _request_json({
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": outputsize,
            "apikey": api_key,
        })
    except DataProviderError:
        return {}

    if "Time Series (Daily)" in data:
        save_to_cache(cache_key, data)
    return data


def clean_stock_data(raw_data):
    daily_data = raw_data["Time Series (Daily)"]
    df = pd.DataFrame.from_dict(daily_data, orient="index")
    df.columns = ["open", "high", "low", "close", "volume"]
    df = df.astype({
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": int,
    })
    df.index.name = "date"
    return df.reset_index().sort_values("date").reset_index(drop=True)


def get_news_sentiment(symbol, limit=20):
    cache_key = f"{symbol}_news"
    cached_data = load_from_cache(cache_key, max_age_hours=4)
    if cached_data is not None:
        return cached_data

    try:
        data = _request_json({
            "function": "NEWS_SENTIMENT",
            "tickers": symbol,
            "limit": limit,
            "apikey": api_key,
        })
    except DataProviderError:
        return []

    if "feed" not in data:
        return []

    news_list = [
        {
            "title": item.get("title"),
            "time_published": item.get("time_published"),
            "summary": item.get("summary"),
            "overall_sentiment_label": item.get("overall_sentiment_label"),
            "source": item.get("source"),
            "url": item.get("url"),
        }
        for item in data["feed"]
    ]
    if news_list:
        save_to_cache(cache_key, news_list)
    return news_list


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_company_overview(symbol):
    cache_key = f"{symbol}_overview"
    cached_data = load_from_cache(cache_key, max_age_hours=72)
    if cached_data is not None:
        return cached_data

    try:
        data = _request_json({
            "function": "OVERVIEW",
            "symbol": symbol,
            "apikey": api_key,
        })
    except DataProviderError:
        return {}

    if not data or "Symbol" not in data:
        return {}

    gross_profit = _safe_float(data.get("GrossProfitTTM"))
    revenue = _safe_float(data.get("RevenueTTM"))
    gross_margin_pct = None
    if gross_profit is not None and revenue not in (None, 0):
        gross_margin_pct = round(gross_profit / revenue * 100, 2)

    overview = {
        "公司名稱": data.get("Name"),
        "產業別": data.get("Industry"),
        "市值": data.get("MarketCapitalization"),
        "本益比": data.get("PERatio"),
        "每股盈餘": data.get("EPS"),
        "毛利(TTM)": data.get("GrossProfitTTM"),
        "毛利率": gross_margin_pct,
        "營收(近12個月)": data.get("RevenueTTM"),
        "營業利益率": data.get("OperatingMarginTTM"),
        "股價淨值比": data.get("PriceToBookRatio"),
        "52週最高價": data.get("52WeekHigh"),
        "52週最低價": data.get("52WeekLow"),
        "公司簡介": data.get("Description"),
    }
    save_to_cache(cache_key, overview)
    return overview


def get_long_history_stock_data(symbol, period="2y"):
    cache_key = f"{symbol}_long_history_{period}_adjusted_v1"
    cached_data = load_from_cache(cache_key, max_age_hours=20)
    if cached_data is not None:
        return pd.DataFrame(cached_data)

    try:
        raw_df = yf.download(symbol, period=period, progress=False, auto_adjust=True)
    except Exception:
        return pd.DataFrame()

    if raw_df.empty:
        return pd.DataFrame()

    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = raw_df.columns.get_level_values(0)

    df = raw_df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)

    save_to_cache(cache_key, df.to_dict(orient="records"))
    return df


if __name__ == "__main__":
    raw = get_daily_stock_data("BTDR")
    if "Time Series (Daily)" in raw:
        print(clean_stock_data(raw).tail())
