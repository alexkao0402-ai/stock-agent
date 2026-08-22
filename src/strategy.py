# strategy.py
# 這個檔案負責處理「規則型交易策略」的邏輯
# 重要原則：這裡的所有計算都只使用「歷史資料」，絕對不能用到未來的資訊（避免 look-ahead bias）

import pandas as pd


def add_moving_averages(df, short_window=10, long_window=30):
    """
    在股價表格上，新增「短期移動平均線」與「長期移動平均線」兩個欄位。

    df: clean_stock_data() 產生的 pandas DataFrame（必須包含 date, close 欄位，且按日期由舊到新排序）
    short_window: 短期均線要計算幾天的平均，預設 10 天
    long_window: 長期均線要計算幾天的平均，預設 30 天

    回傳：新增了 ma_short, ma_long 兩欄的 DataFrame
    """

    # 複製一份資料，避免直接修改到原本傳進來的 df（這是好習慣，避免意外的副作用）
    df = df.copy()

    # rolling(window=N) 的意思是：「取每一列，往前數 N 天（含自己）的資料」
    # .mean() 則是計算這 N 天收盤價的平均值
    # 這個計算方式，天生就只會用到「當天以及更早之前」的資料，不會用到未來，這正是我們要的安全特性
    df["ma_short"] = df["close"].rolling(window=short_window).mean()
    df["ma_long"] = df["close"].rolling(window=long_window).mean()

    return df

if __name__ == "__main__":
    from src.stock_data import get_daily_stock_data, clean_stock_data

    raw = get_daily_stock_data("BTDR")
    df = clean_stock_data(raw)

    df_with_ma = add_moving_averages(df)

    print(df_with_ma[["date", "close", "ma_short", "ma_long"]].tail(15))