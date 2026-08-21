# stock_data.py
# 這個檔案負責處理「跟股票資料有關」的功能
# 這一步：把 API 拿回來的原始 JSON 資料，整理成乾淨的 pandas 表格

import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ALPHAVANTAGE_API_KEY")


def get_daily_stock_data(symbol):
    """
    向 Alpha Vantage 要某支股票的每日歷史價格資料。
    symbol: 股票代號，例如 "BTDR"
    回傳：API 回應的原始資料（Python 字典格式）
    """
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": api_key
    }
    response = requests.get(url, params=params)
    data = response.json()
    return data


def clean_stock_data(raw_data):
    """
    把 API 回傳的原始 JSON 資料，轉換成乾淨的 pandas 表格（DataFrame）。
    raw_data: get_daily_stock_data() 回傳的字典
    回傳：一個 pandas DataFrame，欄位為 date, open, high, low, close, volume
    """

    # 只取出我們真正需要的那一大包：「Time Series (Daily)」
    daily_data = raw_data["Time Series (Daily)"]

    # pd.DataFrame.from_dict() 可以直接把「字典包字典」的結構轉成表格
    # orient="index" 代表：外層的 key（日期）要變成表格的「row（列）」
    df = pd.DataFrame.from_dict(daily_data, orient="index")

    # 這時候欄位名稱還是 API 給的原始名稱，例如 "1. open"、"2. high"
    # 我們把它們改成更乾淨好用的名稱
    df.columns = ["open", "high", "low", "close", "volume"]

    # 目前資料裡的數字其實是「文字」格式（例如 "8.9900"），要轉成真正的數字
    # astype(float) 把整欄轉成浮點數；volume 轉成整數比較合理
    df = df.astype({
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": int
    })

    # 目前「日期」是表格的 index（列名稱），不是欄位，我們把它變成一個獨立欄位
    df.index.name = "date"
    df = df.reset_index()

    # API 回傳的資料是「最新日期在最上面」，我們把它反過來，讓「最舊日期在最上面」
    # 這樣之後畫圖、分析時間趨勢會比較直覺
    df = df.sort_values("date").reset_index(drop=True)

    return df


if __name__ == "__main__":
    raw = get_daily_stock_data("BTDR")
    df = clean_stock_data(raw)

    # 印出表格的前 5 筆和後 5 筆，快速檢查資料長什麼樣子
    print(df.head())
    print("...")
    print(df.tail())

    # 印出這張表格的基本資訊：總共幾列、每欄的資料型態
    print("\n資料筆數與型態：")
    print(df.info())