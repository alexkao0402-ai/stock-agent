# strategy_v1.py
# Strategy V1：趨勢 + 動能 + 相對強弱
# 重要原則：所有計算只使用歷史資料，絕不使用未來資訊（避免 look-ahead bias）

import pandas as pd


def add_trend_filter(df, window=200):
    """
    新增「趨勢過濾」欄位：判斷收盤價是否高於200日均線。

    df: 股價 DataFrame（必須包含 close 欄位，按日期由舊到新排序）
    window: 均線天數，預設200天

    回傳：新增了 ma200, is_bullish_regime 兩欄的 DataFrame
    """
    df = df.copy()
    df["ma200"] = df["close"].rolling(window=window).mean()
    df["is_bullish_regime"] = df["close"] > df["ma200"]
    return df


def add_momentum(df, months=6, trading_days_per_month=21):
    """
    新增「動能」欄位：計算過去N個月的報酬率。

    df: 股價 DataFrame（必須包含 close 欄位）
    months: 要看幾個月的動能，預設6個月
    trading_days_per_month: 一個月大約有幾個交易日，預設21天（業界常用估計值）

    回傳：新增了 momentum_pct 欄位的 DataFrame
    """
    df = df.copy()
    window_days = months * trading_days_per_month

    # pct_change(periods=N) 計算「現在的值，相對於N天前的值，變化了百分之多少」
    # 這個計算方式，天生只會用到「過去」的資料，不會用到未來
    df["momentum_pct"] = df["close"].pct_change(periods=window_days) * 100
    return df


def add_relative_strength(stock_df, benchmark_df, months=6, trading_days_per_month=21):
    """
    新增「相對強弱」欄位：比較股票的N個月報酬率，是否贏過基準（例如BTC）的N個月報酬率。

    stock_df: 已經跑過 add_momentum() 的股票 DataFrame（必須包含 date, momentum_pct 欄位）
    benchmark_df: 基準的股價 DataFrame（例如 BTC，必須包含 date, close 欄位）
    months, trading_days_per_month: 跟 add_momentum() 使用同樣的參數，確保計算基礎一致

    回傳：新增了 benchmark_momentum_pct, outperforms_benchmark 兩欄的 DataFrame
    """
    df = stock_df.copy()
    window_days = months * trading_days_per_month

    # 先計算基準（例如BTC）自己的動能
    benchmark_df = benchmark_df.copy()
    benchmark_df["benchmark_momentum_pct"] = benchmark_df["close"].pct_change(periods=window_days) * 100

    # 用「日期」把股票資料跟基準資料對齊合併
    # 這一步很重要：股票的交易日跟加密貨幣的交易日不完全一樣（加密貨幣是全年無休，股票有休市日）
    # 用 merge 可以確保我們是拿「同一天」的兩邊資料做比較，而不是隨便對齊
    merged = pd.merge(
        df[["date", "momentum_pct"]],
        benchmark_df[["date", "benchmark_momentum_pct"]],
        on="date",
        how="left"  # 以股票的交易日為主，如果那天剛好沒有對應的BTC資料，就先留空
    )

    df = df.merge(merged[["date", "benchmark_momentum_pct"]], on="date", how="left")
    df["outperforms_benchmark"] = df["momentum_pct"] > df["benchmark_momentum_pct"]

    return df

if __name__ == "__main__":
    from src.stock_data import get_long_history_stock_data, get_crypto_daily_data, clean_crypto_data

    # 改用 yfinance 抓取BTDR的長期歷史股價（2年，足夠算 MA200）
    stock_df = get_long_history_stock_data("BTDR", period="2y")

    # BTC 資料維持用 Alpha Vantage（這個資料源本身就給完整歷史，不受影響）
    raw_crypto = get_crypto_daily_data("BTC", "USD")
    crypto_df = clean_crypto_data(raw_crypto)

    print(f"BTDR資料筆數：{len(stock_df)}，時間範圍：{stock_df['date'].iloc[0]} ~ {stock_df['date'].iloc[-1]}")
    print(f"BTC資料筆數：{len(crypto_df)}")

    stock_df = add_trend_filter(stock_df)
    stock_df = add_momentum(stock_df)
    stock_df = add_relative_strength(stock_df, crypto_df)

    print("\n最後15天的三因子數據：")
    print(stock_df[["date", "close", "ma200", "is_bullish_regime", "momentum_pct", "benchmark_momentum_pct", "outperforms_benchmark"]].tail(15))