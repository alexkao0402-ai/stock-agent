# regime_analysis.py
# 市場狀態分類：Risk-On / Risk-Off / Mixed
#
# 分類規則（清楚記錄，未依據任何歷史績效資料校準）：
#   Risk-On  : SPY收盤價 > SPY的200日均線  且  BTC收盤價 > BTC的200日均線
#   Risk-Off : SPY收盤價 <= SPY的200日均線 且  BTC收盤價 <= BTC的200日均線
#   Mixed    : 以上兩者皆不成立（SPY與BTC訊號不一致）
#
# 重要原則：每一天的狀態判斷，只使用「當天以及更早之前」的資料（200日均線本身即符合此原則），
# 絕不使用未來資訊。

import pandas as pd
from src.stock_data import get_long_history_stock_data, get_crypto_daily_data, clean_crypto_data


def build_regime_series(period="2y"):
    """
    建立一份「逐日市場狀態」的對照表，之後可以用日期查詢當天屬於哪種市場狀態。

    period: 要抓取的歷史長度

    回傳：一個 DataFrame，欄位為 date, spy_close, spy_ma200, spy_bullish, 
          btc_close, btc_ma200, btc_bullish, regime
    """

    spy_df = get_long_history_stock_data("SPY", period=period)
    raw_crypto = get_crypto_daily_data("BTC", "USD")
    btc_df = clean_crypto_data(raw_crypto)

    # 計算SPY自己的200日均線與多空判斷
    spy_df = spy_df.copy()
    spy_df["spy_ma200"] = spy_df["close"].rolling(window=200).mean()
    spy_df["spy_bullish"] = spy_df["close"] > spy_df["spy_ma200"]
    spy_df = spy_df.rename(columns={"close": "spy_close"})

    # 計算BTC自己的200日均線與多空判斷
    btc_df = btc_df.copy()
    btc_df["btc_ma200"] = btc_df["close"].rolling(window=200).mean()
    btc_df["btc_bullish"] = btc_df["close"] > btc_df["btc_ma200"]
    btc_df = btc_df.rename(columns={"close": "btc_close"})

    # 用日期合併兩者（SPY交易日跟BTC交易日不完全相同，用left join以SPY交易日為主）
    merged = pd.merge(
        spy_df[["date", "spy_close", "spy_ma200", "spy_bullish"]],
        btc_df[["date", "btc_close", "btc_ma200", "btc_bullish"]],
        on="date",
        how="left"
    )

    def classify(row):
        # 如果任一均線還沒有足夠天數算出來（NaN），無法判斷，歸類為Mixed（保守處理，不假裝知道答案）
        if pd.isna(row["spy_bullish"]) or pd.isna(row["btc_bullish"]):
            return "Mixed"
        if row["spy_bullish"] and row["btc_bullish"]:
            return "Risk-On"
        if (not row["spy_bullish"]) and (not row["btc_bullish"]):
            return "Risk-Off"
        return "Mixed"

    merged["regime"] = merged.apply(classify, axis=1)

    return merged


if __name__ == "__main__":
    regime_df = build_regime_series()

    print("市場狀態分布統計：")
    print(regime_df["regime"].value_counts())

    print("\n最後20天的市場狀態：")
    print(regime_df[["date", "spy_close", "spy_bullish", "btc_close", "btc_bullish", "regime"]].tail(20).to_string(index=False))