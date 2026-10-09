# ablation_study.py
# 消融研究：測試 Strategy V1 的各個組成因子，分別對績效的影響
# A: Buy & Hold
# B: 只有 MA200 趨勢過濾
# C: MA200 + 6個月動能
# D: MA200 + 6個月動能 + 相對強弱（完整版 Strategy V1）

import pandas as pd
from src.stock_data import get_long_history_stock_data, get_crypto_daily_data, clean_crypto_data
from src.strategy_v1 import (
    add_trend_filter, add_momentum, add_relative_strength,
    run_backtest_v1, calculate_buy_and_hold, calculate_performance_metrics
)


def add_entry_exit_signals_custom(df, use_momentum=True, use_relative_strength=True):
    """
    跟 strategy_v1.py 裡的 add_entry_exit_signals() 邏輯相同，
    但可以選擇性地「關閉」動能或相對強弱條件，用來做消融研究。

    df: 已經跑過對應前置計算的 DataFrame
    use_momentum: 是否要求 momentum_pct > 0 才能進場
    use_relative_strength: 是否要求 outperforms_benchmark 才能進場
    """
    df = df.copy()

    # 趨勢過濾永遠是基礎條件（規格書明定：策略只允許在多頭趨勢時進場）
    entry_condition = df["is_bullish_regime"] == True

    if use_momentum:
        entry_condition = entry_condition & (df["momentum_pct"] > 0)

    if use_relative_strength:
        entry_condition = entry_condition & (df["outperforms_benchmark"] == True)

    # 出場條件跟進場條件對稱：任何一個有加入的條件失效，就出場
    exit_condition = df["is_bullish_regime"] == False
    if use_momentum:
        exit_condition = exit_condition | (df["momentum_pct"] <= 0)
    if use_relative_strength:
        exit_condition = exit_condition | (df["outperforms_benchmark"] == False)

    entry_condition_yesterday = entry_condition.shift(1)
    exit_condition_yesterday = exit_condition.shift(1)

    new_buy_signal = (entry_condition == True) & (entry_condition_yesterday == False)
    new_sell_signal = (exit_condition == True) & (exit_condition_yesterday == False)

    df["signal"] = None
    df.loc[new_buy_signal, "signal"] = "buy"
    df.loc[new_sell_signal, "signal"] = "sell"

    df["execution_price"] = df["open"].shift(-1)

    return df


def run_ablation_study(symbol="BTDR", period="2y"):
    """
    對同一支股票、同一份資料，跑過A/B/C/D四種版本的策略，方便直接比較。
    """

    print(f"===== 消融研究：{symbol} =====\n")

    stock_df = get_long_history_stock_data(symbol, period=period)
    raw_crypto = get_crypto_daily_data("BTC", "USD")
    crypto_df = clean_crypto_data(raw_crypto)

    # 先把所有需要的欄位一次算好，四個版本都基於同一份已計算好因子的資料，確保公平比較
    base_df = add_trend_filter(stock_df)
    base_df = add_momentum(base_df)
    base_df = add_relative_strength(base_df, crypto_df)

    results = {}

    # ---------- A: Buy & Hold ----------
    bh = calculate_buy_and_hold(base_df)
    results["A_buy_and_hold"] = {
        "description": "Buy & Hold",
        "total_return_pct": bh["total_return_pct"],
        "number_of_trades": 0
    }

    # ---------- B: 只有 MA200 趨勢過濾 ----------
    df_b = add_entry_exit_signals_custom(base_df, use_momentum=False, use_relative_strength=False)
    result_b = run_backtest_v1(df_b)
    metrics_b = calculate_performance_metrics(result_b["trades"], result_b["initial_capital"], result_b["final_value"], df_b)
    results["B_trend_only"] = {
        "description": "MA200 only",
        "total_return_pct": result_b["total_return_pct"],
        "number_of_trades": metrics_b["number_of_completed_trades"],
        "win_rate_pct": metrics_b["win_rate_pct"]
    }

    # ---------- C: MA200 + 動能 ----------
    df_c = add_entry_exit_signals_custom(base_df, use_momentum=True, use_relative_strength=False)
    result_c = run_backtest_v1(df_c)
    metrics_c = calculate_performance_metrics(result_c["trades"], result_c["initial_capital"], result_c["final_value"], df_c)
    results["C_trend_momentum"] = {
        "description": "MA200 + 6M Momentum",
        "total_return_pct": result_c["total_return_pct"],
        "number_of_trades": metrics_c["number_of_completed_trades"],
        "win_rate_pct": metrics_c["win_rate_pct"]
    }

    # ---------- D: 完整版（MA200 + 動能 + 相對強弱）----------
    df_d = add_entry_exit_signals_custom(base_df, use_momentum=True, use_relative_strength=True)
    result_d = run_backtest_v1(df_d)
    metrics_d = calculate_performance_metrics(result_d["trades"], result_d["initial_capital"], result_d["final_value"], df_d)
    results["D_full_v1"] = {
        "description": "MA200 + Momentum + Relative Strength (V1)",
        "total_return_pct": result_d["total_return_pct"],
        "number_of_trades": metrics_d["number_of_completed_trades"],
        "win_rate_pct": metrics_d["win_rate_pct"]
    }

    return results

def test_multiple_assets(symbols, period="2y"):
    """
    用完全相同、未經調整的 Strategy V1，測試多個資產，觀察策略在不同資產上的表現差異。
    不針對任何個別資產優化參數。

    symbols: 股票代號清單，例如 ["SPY", "QQQ", "AAPL"]
    period: 抓取的歷史長度

    回傳：一個字典，key是股票代號，value是該資產的完整回測結果
    """

    raw_crypto = get_crypto_daily_data("BTC", "USD")
    crypto_df = clean_crypto_data(raw_crypto)

    results = {}

    for symbol in symbols:
        try:
            stock_df = get_long_history_stock_data(symbol, period=period)

            if stock_df.empty or len(stock_df) < 200:
                results[symbol] = {"error": "資料不足200天，無法計算MA200"}
                continue

            df = add_trend_filter(stock_df)
            df = add_momentum(df)
            df = add_relative_strength(df, crypto_df)
            df = add_entry_exit_signals_custom(df, use_momentum=True, use_relative_strength=True)

            backtest_result = run_backtest_v1(df)
            bh_result = calculate_buy_and_hold(df)
            metrics = calculate_performance_metrics(
                backtest_result["trades"], backtest_result["initial_capital"],
                backtest_result["final_value"], df
            )

            results[symbol] = {
                "strategy_return_pct": backtest_result["total_return_pct"],
                "buy_hold_return_pct": bh_result["total_return_pct"],
                "outperformed_bh": backtest_result["total_return_pct"] > bh_result["total_return_pct"],
                "number_of_trades": metrics["number_of_completed_trades"],
                "win_rate_pct": metrics["win_rate_pct"],
                "cagr_pct": metrics["cagr_pct"]
            }
        except Exception as e:
            # 如果某支股票抓取或計算過程中出錯（例如代號不存在），記錄錯誤但不中斷整個測試
            results[symbol] = {"error": str(e)}

    return results


if __name__ == "__main__":
    results = run_ablation_study("BTDR")

    print(f"{'版本':<15}{'說明':<45}{'總報酬率':<12}{'交易次數':<10}{'勝率'}")
    print("-" * 95)
    for key, r in results.items():
        win_rate = r.get("win_rate_pct", "N/A")
        print(f"{key:<15}{r['description']:<45}{r['total_return_pct']:<12}{r['number_of_trades']:<10}{win_rate}")

    print("\n\n===== Step F: 多資產測試（未調整任何參數）=====\n")
    assets = ["SPY", "QQQ", "AAPL", "NVDA", "MARA", "IREN"]
    multi_results = test_multiple_assets(assets)

    print(f"{'股票':<8}{'策略報酬率':<14}{'B&H報酬率':<14}{'策略是否勝出':<14}{'交易次數':<10}{'勝率':<10}{'CAGR'}")
    print("-" * 90)
    for symbol, r in multi_results.items():
        if "error" in r:
            print(f"{symbol:<8}錯誤：{r['error']}")
        else:
            print(f"{symbol:<8}{r['strategy_return_pct']:<14}{r['buy_hold_return_pct']:<14}{str(r['outperformed_bh']):<14}{r['number_of_trades']:<10}{r['win_rate_pct']:<10}{r['cagr_pct']}")