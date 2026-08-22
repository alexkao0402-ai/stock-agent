# stock_data.py
# 這個檔案負責處理「跟股票資料有關」的功能

import os
import requests
import pandas as pd
from dotenv import load_dotenv
from src.cache_utils import save_to_cache, load_from_cache

load_dotenv()
api_key = os.getenv("ALPHAVANTAGE_API_KEY")


def get_daily_stock_data(symbol):
    """
    向 Alpha Vantage 要某支股票的每日歷史價格資料。
    優先使用快取，快取不存在或過期時才真正呼叫 API。

    symbol: 股票代號，例如 "BTDR"
    回傳：API 回應的原始資料（Python 字典格式）
    """

    cache_key = f"{symbol}_daily_price"

    # 股價一天只會確定一次收盤價，快取設定 20 小時內有效，足夠涵蓋一整個交易日
    cached_data = load_from_cache(cache_key, max_age_hours=20)
    if cached_data is not None:
        return cached_data

    # 快取不存在或已過期，才真正呼叫 API
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": api_key
    }
    response = requests.get(url, params=params)
    data = response.json()

    # 只有在成功拿到真正的股價資料時，才存進快取
    # 避免把「額度用完」這種錯誤訊息也快取起來，之後一直讀到錯誤內容
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
    symbol: 股票代號，例如 "BTDR"
    limit: 最多抓幾則新聞，預設 20 則
    回傳：一個 list，每一項是一則新聞的重點資訊（字典格式）
    """
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

    return news_list


def get_company_overview(symbol):
    """
    向 Alpha Vantage 要某支股票的公司基本面總覽資料。
    symbol: 股票代號，例如 "BTDR"
    回傳：一個字典，包含市值、本益比、營收等重要指標
    """
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

    return overview


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