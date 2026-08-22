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

def run_backtest(df, initial_capital=10000):
    """
    模擬「照著 buy/sell 訊號操作」，計算整體績效。

    df: 已經跑過 add_signals() 的 DataFrame（必須包含 close, signal 欄位）
    initial_capital: 一開始的模擬本金，預設 10000（美元）

    回傳：一個字典，包含交易紀錄清單與整體績效指標
    """

    cash = initial_capital       # 目前手上的現金
    shares = 0                   # 目前持有的股數
    trades = []                  # 記錄每一次買賣的清單

    for _, row in df.iterrows():
        # 這裡故意用「for 迴圈逐行處理」，而不是用 pandas 的向量化寫法
        # 是為了讓「模擬買賣」這個邏輯，跟真實交易情境更接近、更容易理解與除錯
        # 每一次迴圈，都只根據「這一天」的資料做判斷，天生不會用到未來資訊

        if row["signal"] == "buy" and cash > 0:
            # 用目前手上所有現金，用當天收盤價買進股票
            shares = cash / row["close"]
            cash = 0
            trades.append({
                "date": row["date"],
                "action": "buy",
                "price": row["close"],
                "shares": shares
            })

        elif row["signal"] == "sell" and shares > 0:
            # 把手上所有股票，用當天收盤價全部賣出換成現金
            cash = shares * row["close"]
            trades.append({
                "date": row["date"],
                "action": "sell",
                "price": row["close"],
                "shares": shares
            })
            shares = 0

    # 迴圈跑完後，如果手上還有股票沒賣掉，用資料最後一天的收盤價，計算這些股票值多少錢
    final_price = df["close"].iloc[-1]
    final_value = cash + (shares * final_price)

    total_return_pct = round((final_value - initial_capital) / initial_capital * 100, 2)

    result = {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": total_return_pct,
        "number_of_trades": len(trades),
        "trades": trades,
        "still_holding_shares": shares > 0
    }

    return result

if __name__ == "__main__":
    from src.stock_data import get_daily_stock_data, clean_stock_data

    raw = get_daily_stock_data("BTDR")
    df = clean_stock_data(raw)

    df_with_ma = add_moving_averages(df)
    df_with_signals = add_signals(df_with_ma)

    signal_rows = df_with_signals[df_with_signals["signal"].notna()]
    print("===== 訊號 =====")
    print(signal_rows[["date", "close", "ma_short", "ma_long", "signal"]])

    print("\n===== 回測結果 =====")
    result = run_backtest(df_with_signals)
    print(f"本金：${result['initial_capital']}")
    print(f"最終價值：${result['final_value']}")
    print(f"總報酬率：{result['total_return_pct']}%")
    print(f"交易次數：{result['number_of_trades']}")
    print(f"目前是否持股：{result['still_holding_shares']}")