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

def add_entry_exit_signals(df):
    """
    根據三因子條件，產生進場/出場訊號，並標記「實際執行交易的價格」。
    重要：訊號在第t天算出，但實際成交價使用第t+1天（隔天）的開盤價，避免look-ahead bias。

    df: 已經跑過 add_trend_filter(), add_momentum(), add_relative_strength() 的 DataFrame

    回傳：新增了 signal, execution_price 欄位的 DataFrame
    signal 欄位的值："buy" / "sell" / None
    execution_price：這個訊號實際會用哪一天、哪個價格成交（如果是最後一天發出訊號、沒有隔天資料可用，則為 None）
    """
    df = df.copy()

    # 進場條件：三個條件同時成立
    entry_condition = (
        df["is_bullish_regime"] == True
    ) & (
        df["momentum_pct"] > 0
    ) & (
        df["outperforms_benchmark"] == True
    )

    # 出場條件：只要「不在多頭趨勢」或「不再贏過基準」，任一成立就出場
    exit_condition = (
        df["is_bullish_regime"] == False
    ) | (
        df["outperforms_benchmark"] == False
    )

    # 用「今天符合條件、昨天不符合」來判斷「訊號第一次成立」，避免同一個持續成立的狀態每天都重複發訊號
    entry_condition_yesterday = entry_condition.shift(1)
    exit_condition_yesterday = exit_condition.shift(1)

    new_buy_signal = (entry_condition == True) & (entry_condition_yesterday == False)
    new_sell_signal = (exit_condition == True) & (exit_condition_yesterday == False)

    df["signal"] = None
    df.loc[new_buy_signal, "signal"] = "buy"
    df.loc[new_sell_signal, "signal"] = "sell"

    # 核心邏輯：把「隔天的開盤價」，對應回「今天這一列」
    # .shift(-1) 代表「把整欄資料往上移一格」，這樣「今天這一列」對應到的，就是「明天的值」
    # 這樣一來，df.loc[某一天, "execution_price"] 存的就是「這個訊號真正會拿去成交的價格」
    df["execution_price"] = df["open"].shift(-1)

    return df

def run_backtest_v1(df, initial_capital=10000, transaction_cost_pct=0.001, slippage_pct=0.0005):
    """
    模擬照著 Strategy V1 的訊號進行買賣，並且扣除交易成本與滑價，計算真實績效。

    df: 已經跑過 add_entry_exit_signals() 的 DataFrame
    initial_capital: 起始模擬本金，預設 10000
    transaction_cost_pct: 每筆交易的手續費比例，預設 0.1%（0.001）
    slippage_pct: 每筆交易的滑價比例，預設 0.05%（0.0005）
                  滑價代表「實際成交價，通常會比你想要的價格差一點點」，這是真實交易中常見的現象

    回傳：一個字典，包含完整交易紀錄與績效指標
    """

    cash = initial_capital
    shares = 0
    trades = []

    for _, row in df.iterrows():
        # 如果這一天沒有 execution_price（例如是資料的最後一天，沒有隔天可以成交），就跳過
        if pd.isna(row["execution_price"]):
            continue

        if row["signal"] == "buy" and cash > 0:
            raw_price = row["execution_price"]
            # 買進時，滑價讓你「買貴一點」（用比預期價格更高的價格成交，模擬真實市場的不利影響）
            actual_price = raw_price * (1 + slippage_pct)

            # 先扣除手續費，剩下的錢才拿去買股票
            cash_after_fee = cash * (1 - transaction_cost_pct)
            shares = cash_after_fee / actual_price
            cash = 0

            trades.append({
                "date": row["date"],
                "action": "buy",
                "signal_date": row["date"],
                "execution_price": actual_price,
                "shares": shares,
                "reason": "三因子條件成立：趨勢多頭 + 正動能 + 優於BTC"
            })

        elif row["signal"] == "sell" and shares > 0:
            raw_price = row["execution_price"]
            # 賣出時，滑價讓你「賣便宜一點」（同樣模擬不利影響）
            actual_price = raw_price * (1 - slippage_pct)

            gross_cash = shares * actual_price
            # 賣出所得，也要扣一次手續費
            cash = gross_cash * (1 - transaction_cost_pct)

            trades.append({
                "date": row["date"],
                "action": "sell",
                "signal_date": row["date"],
                "execution_price": actual_price,
                "shares": shares,
                "reason": "趨勢轉空頭 或 不再優於BTC"
            })
            shares = 0

    final_price = df["close"].iloc[-1]
    final_value = cash + (shares * final_price)
    total_return_pct = round((final_value - initial_capital) / initial_capital * 100, 2)

    result = {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": total_return_pct,
        "number_of_trades": len(trades),
        "transaction_cost_pct": transaction_cost_pct,
        "slippage_pct": slippage_pct,
        "trades": trades,
        "still_holding_shares": shares > 0
    }

    return result

def calculate_buy_and_hold(df, initial_capital=10000):
    """
    計算「從資料第一天就買進，一路持有到最後一天」的績效，作為比較基準。

    df: 股價 DataFrame（必須包含 close 欄位，按日期排序）
    initial_capital: 起始模擬本金，預設 10000

    回傳：一個字典，包含最終價值與總報酬率
    """
    first_price = df["close"].iloc[0]
    last_price = df["close"].iloc[-1]

    shares = initial_capital / first_price
    final_value = shares * last_price
    total_return_pct = round((final_value - initial_capital) / initial_capital * 100, 2)

    return {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": total_return_pct,
        "start_date": df["date"].iloc[0],
        "end_date": df["date"].iloc[-1],
        "start_price": first_price,
        "end_price": last_price
    }

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

    stock_df = add_entry_exit_signals(stock_df)

    print("\n所有觸發過的訊號：")
    signal_rows = stock_df[stock_df["signal"].notna()]
    print(signal_rows[["date", "close", "signal", "execution_price"]])

    print("\n===== Strategy V1 回測結果（含交易成本與滑價）=====")
    backtest_result = run_backtest_v1(stock_df)
    print(f"本金：${backtest_result['initial_capital']}")
    print(f"最終價值：${backtest_result['final_value']}")
    print(f"總報酬率：{backtest_result['total_return_pct']}%")
    print(f"交易次數：{backtest_result['number_of_trades']}")
    print(f"手續費率：{backtest_result['transaction_cost_pct']*100}%，滑價率：{backtest_result['slippage_pct']*100}%")

    print("\n===== Buy & Hold 基準比較 =====")
    bh_result = calculate_buy_and_hold(stock_df)
    print(f"從 {bh_result['start_date']}（${bh_result['start_price']}）持有到 {bh_result['end_date']}（${bh_result['end_price']}）")
    print(f"Buy & Hold 最終價值：${bh_result['final_value']}")
    print(f"Buy & Hold 總報酬率：{bh_result['total_return_pct']}%")

    print(f"\nStrategy V1 總報酬率：{backtest_result['total_return_pct']}%")
    print(f"Buy & Hold 總報酬率：{bh_result['total_return_pct']}%")
    if backtest_result['total_return_pct'] > bh_result['total_return_pct']:
        print("結論：Strategy V1 表現優於 Buy & Hold")
    else:
        print("結論：Strategy V1 表現劣於 Buy & Hold")