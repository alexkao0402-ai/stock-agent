# stock_data.py
# 這個檔案負責處理「跟股票資料有關」的功能

import os
import requests
import pandas as pd
from dotenv import load_dotenv
from src.cache_utils import save_to_cache, load_from_cache

load_dotenv()
api_key = os.getenv("ALPHAVANTAGE_API_KEY")


def get_daily_stock_data(symbol, outputsize="compact"):
    """
    向 Alpha Vantage 要某支股票的每日歷史價格資料。
    優先使用快取，快取不存在或過期時才真正呼叫 API。

    symbol: 股票代號，例如 "BTDR"
    outputsize: "compact"（最近100天，預設）或 "full"（完整歷史，通常20年）
                Strategy V1 需要算 MA200，必須用 "full" 才有足夠天數
    回傳：API 回應的原始資料（Python 字典格式）
    """

    # 快取的 key 要包含 outputsize，因為 compact 和 full 是不同的資料量，不能共用同一份快取
    cache_key = f"{symbol}_daily_price_{outputsize}"

    cached_data = load_from_cache(cache_key, max_age_hours=20)
    if cached_data is not None:
        return cached_data

    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": outputsize,
        "apikey": api_key
    }
    response = requests.get(url, params=params)
    data = response.json()

    if "Time Series (Daily)" in data:
        save_to_cache(cache_key, data)

    return data


def clean_stock_data(raw_data):
    """
    把 API 回傳的原始 JSON 資料，轉換成乾淨的 pandas 表格（DataFrame）。
    raw_data: get_daily_stock_data() 回傳的字典
    回傳：一個 pandas DataFrame，欄位為 date, open, high, low, close, volume
    """
    daily_data = raw_data["Time Series (Daily)"]
    df = pd.DataFrame.from_dict(daily_data, orient="index")
    df.columns = ["open", "high", "low", "close", "volume"]
    df = df.astype({
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": int
    })
    df.index.name = "date"
    df = df.reset_index()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def get_news_sentiment(symbol, limit=20):
    """
    向 Alpha Vantage 要某支股票最近的相關新聞，附帶情緒分析分數。
    優先使用快取，快取不存在或過期時才真正呼叫 API。

    symbol: 股票代號，例如 "BTDR"
    limit: 最多抓幾則新聞，預設 20 則
    回傳：一個 list，每一項是一則新聞的重點資訊（字典格式）
    """

    cache_key = f"{symbol}_news"

    # 新聞變化比股價快，快取設定4小時內有效
    cached_data = load_from_cache(cache_key, max_age_hours=4)
    if cached_data is not None:
        return cached_data

    url = "https://www.alphavantage.co/query"
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": symbol,
        "limit": limit,
        "apikey": api_key
    }
    response = requests.get(url, params=params)
    data = response.json()

    if "feed" not in data:
        return []

    news_list = []
    for item in data["feed"]:
        news_list.append({
            "title": item.get("title"),
            "time_published": item.get("time_published"),
            "summary": item.get("summary"),
            "overall_sentiment_label": item.get("overall_sentiment_label"),
            "source": item.get("source")
        })

    # 只有成功整理出新聞清單時才存進快取
    if news_list:
        save_to_cache(cache_key, news_list)

    return news_list


def get_company_overview(symbol):
    """
    向 Alpha Vantage 要某支股票的公司基本面總覽資料。
    優先使用快取，快取不存在或過期時才真正呼叫 API。

    symbol: 股票代號，例如 "BTDR"
    回傳：一個字典，包含市值、本益比、營收等重要指標
    """

    cache_key = f"{symbol}_overview"

    # 基本面資料通常一季才更新一次，快取設定72小時（3天）內有效
    cached_data = load_from_cache(cache_key, max_age_hours=72)
    if cached_data is not None:
        return cached_data

    url = "https://www.alphavantage.co/query"
    params = {
        "function": "OVERVIEW",
        "symbol": symbol,
        "apikey": api_key
    }
    response = requests.get(url, params=params)
    data = response.json()

    if not data or "Symbol" not in data:
        return {}

    overview = {
        "公司名稱": data.get("Name"),
        "產業別": data.get("Industry"),
        "市值": data.get("MarketCapitalization"),
        "本益比": data.get("PERatio"),
        "每股盈餘": data.get("EPS"),
        "毛利率": data.get("GrossProfitTTM"),
        "營收(近12個月)": data.get("RevenueTTM"),
        "營業利益率": data.get("OperatingMarginTTM"),
        "股價淨值比": data.get("PriceToBookRatio"),
        "52週最高價": data.get("52WeekHigh"),
        "52週最低價": data.get("52WeekLow"),
        "公司簡介": data.get("Description")
    }

    # 只有成功拿到有效資料時才存進快取
    save_to_cache(cache_key, overview)

    return overview

def get_crypto_daily_data(symbol="BTC", market="USD"):
    """
    向 Alpha Vantage 要某個加密貨幣的每日價格資料。
    優先使用快取，快取不存在或過期時才真正呼叫 API。

    symbol: 加密貨幣代號，例如 "BTC"
    market: 報價幣別，例如 "USD"
    回傳：API 回應的原始資料（Python 字典格式）
    """

    cache_key = f"{symbol}_{market}_crypto_daily"

    cached_data = load_from_cache(cache_key, max_age_hours=20)
    if cached_data is not None:
        return cached_data

    url = "https://www.alphavantage.co/query"
    params = {
        "function": "DIGITAL_CURRENCY_DAILY",
        "symbol": symbol,
        "market": market,
        "apikey": api_key
    }
    response = requests.get(url, params=params)
    data = response.json()

    # 確認真實測試過後，成功時的資料會包含這個 key
    if "Time Series (Digital Currency Daily)" in data:
        save_to_cache(cache_key, data)

    return data

if __name__ == "__main__":
    raw = get_daily_stock_data("BTDR")
    df = clean_stock_data(raw)
    print(df.head())
    print("...")
    print(df.tail())
    print("\n資料筆數與型態：")
    print(df.info())

    print("\n\n===== 新聞資料測試 =====")
    news = get_news_sentiment("BTDR", limit=5)
    print(f"抓到 {len(news)} 則新聞\n")
    for n in news:
        print(f"標題：{n['title']}")
        print(f"時間：{n['time_published']}")
        print(f"情緒：{n['overall_sentiment_label']}")
        print(f"來源：{n['source']}")
        print("---")

    print("\n\n===== 公司基本面測試 =====")
    overview = get_company_overview("BTDR")
    for key, value in overview.items():
        if key == "公司簡介":
            print(f"{key}：{str(value)[:100]}...")
        else:
            print(f"{key}：{value}")

def clean_crypto_data(raw_data):
    """
    把 get_crypto_daily_data() 回傳的原始 JSON，轉換成乾淨的 pandas 表格。
    raw_data: get_crypto_daily_data() 回傳的字典
    回傳：一個 pandas DataFrame，欄位為 date, open, high, low, close, volume
    """
    daily_data = raw_data["Time Series (Digital Currency Daily)"]
    df = pd.DataFrame.from_dict(daily_data, orient="index")
    df.columns = ["open", "high", "low", "close", "volume"]
    df = df.astype({
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": float  # 加密貨幣成交量常是小數（例如 124.21 顆比特幣），不能用 int
    })
    df.index.name = "date"
    df = df.reset_index()
    df = df.sort_values("date").reset_index(drop=True)
    return df