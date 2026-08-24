# walk_forward.py
# 滾動視窗穩健性測試：把回測期間切成多個較短的子區間，
# 檢視固定規則策略在各子區間的表現是否穩定一致，
# 而非僅依賴單一整段期間的總和結果。
#
# 重要：這裡沒有「重新校準參數」的動作（V1所有參數皆為固定值，未經優化），
# 純粹是切割既有的逐日權益曲線，觀察不同時間窗口下的表現差異。

import pandas as pd


def split_into_windows(equity_df, window_months=6):
    """
    把一份逐日權益曲線，依照日期切成連續、不重疊的時間窗口。

    equity_df: 包含 date, portfolio_value 欄位的 DataFrame（由舊到新排序）
    window_months: 每個窗口涵蓋幾個月，預設6個月

    回傳：一個 list，每個元素是一個窗口的 DataFrame 切片
    """
    df = equity_df.copy()
    df["date_dt"] = pd.to_datetime(df["date"])

    start_date = df["date_dt"].iloc[0]
    end_date = df["date_dt"].iloc[-1]

    windows = []
    window_start = start_date

    while window_start < end_date:
        window_end = window_start + pd.DateOffset(months=window_months)
        window_df = df[(df["date_dt"] >= window_start) & (df["date_dt"] < window_end)]
        if len(window_df) > 5:  # 避免產生資料筆數過少、沒有意義的窗口
            windows.append(window_df)
        window_start = window_end

    return windows


def compute_window_return(window_df):
    """
    計算一個窗口切片內，權益曲線從頭到尾的報酬率。
    這代表「如果只看這一段期間，策略的帳戶價值變化了多少百分比」。
    """
    if len(window_df) < 2:
        return None
    start_value = window_df["portfolio_value"].iloc[0]
    end_value = window_df["portfolio_value"].iloc[-1]
    return round((end_value - start_value) / start_value * 100, 2)


def compute_window_buy_hold_return(price_df, window_start_date, window_end_date):
    """
    計算同一個窗口期間，Buy & Hold（單純持有股票）的報酬率，作為比較基準。

    price_df: 包含 date, close 欄位的原始股價 DataFrame
    window_start_date, window_end_date: 窗口的起訖日期（字串格式 YYYY-MM-DD）
    """
    window_prices = price_df[(price_df["date"] >= window_start_date) & (price_df["date"] < window_end_date)]
    if len(window_prices) < 2:
        return None
    start_price = window_prices["close"].iloc[0]
    end_price = window_prices["close"].iloc[-1]
    return round((end_price - start_price) / start_price * 100, 2)


def run_walk_forward_analysis(symbol, strategy_equity_df, price_df, window_months=6):
    """
    對單一策略的權益曲線，跑完整的滾動視窗分析，並跟Buy&Hold逐窗口比較。

    symbol: 股票代號
    strategy_equity_df: 策略的逐日權益曲線（例如 run_backtest_v1_with_equity_curve 的輸出）
    price_df: 原始股價資料，用來計算各窗口的Buy&Hold報酬
    window_months: 每個窗口涵蓋幾個月

    回傳：一個 DataFrame，每一列代表一個時間窗口的比較結果
    """
    windows = split_into_windows(strategy_equity_df, window_months=window_months)

    rows = []
    for i, window_df in enumerate(windows):
        window_start = window_df["date"].iloc[0]
        window_end = window_df["date"].iloc[-1]

        strategy_return = compute_window_return(window_df)
        bh_return = compute_window_buy_hold_return(price_df, window_start, window_end)

        rows.append({
            "Stock": symbol,
            "Window": f"#{i+1}",
            "Start": window_start,
            "End": window_end,
            "Strategy_Return_pct": strategy_return,
            "BuyHold_Return_pct": bh_return,
            "Strategy_Beat_BH": (strategy_return is not None and bh_return is not None and strategy_return > bh_return)
        })

    return pd.DataFrame(rows)