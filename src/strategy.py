# strategy.py
# 這個檔案負責處理「規則型交易策略」的邏輯
# 重要原則：這裡的所有計算都只使用「歷史資料」，絕對不能用到未來的資訊（避免 look-ahead bias）

import pandas as pd


def add_moving_averages(df, short_window=10, long_window=30):
    """
    在股價表格上，新增「短期移動平均線」與「長期移動平均線」兩個欄位。
    """
    df = df.copy()
    df["ma_short"] = df["close"].rolling(window=short_window).mean()
    df["ma_long"] = df["close"].rolling(window=long_window).mean()
    return df


def add_signals(df):
    """
    根據短期/長期均線的交叉情況，標記出「買進」與「賣出」訊號。
    """
    df = df.copy()

    is_above_today = df["ma_short"] > df["ma_long"]
    is_above_yesterday = is_above_today.shift(1)

    golden_cross = (is_above_yesterday == False) & (is_above_today == True)
    death_cross = (is_above_yesterday == True) & (is_above_today == False)

    df["signal"] = None
    df.loc[golden_cross, "signal"] = "buy"
    df.loc[death_cross, "signal"] = "sell"

    return df


if __name__ == "__main__":
    from src.stock_data import get_daily_stock_data, clean_stock_data

    raw = get_daily_stock_data("BTDR")
    df = clean_stock_data(raw)

    df_with_ma = add_moving_averages(df)
    df_with_signals = add_signals(df_with_ma)

    signal_rows = df_with_signals[df_with_signals["signal"].notna()]
    print(signal_rows[["date", "close", "ma_short", "ma_long", "signal"]])