# compare_strategies.py
# 統一比較 Strategy V1 各版本 vs Buy & Hold，在單一股票上的完整績效表現

import pandas as pd
from src.stock_data import get_long_history_stock_data, get_crypto_daily_data, clean_crypto_data
from src.strategy_v1 import (
    add_trend_filter, add_momentum, add_relative_strength, add_entry_exit_signals,
    run_backtest_v1_with_equity_curve, run_backtest_v1_with_takeprofit_v2, run_backtest_v1_with_trailing_exit,
    calculate_risk_metrics, calculate_buy_and_hold, calculate_performance_metrics,
    build_comparison_row
)


def compare_all_strategies(symbol, period="2y"):
    """
    對單一股票，跑過V1、V1+停利、V1+移動停損、Buy&Hold四種版本，
    產出統一格式的比較表格。
    """

    stock_df = get_long_history_stock_data(symbol, period=period)
    if stock_df.empty or len(stock_df) < 200:
        return None

    raw_crypto = get_crypto_daily_data("BTC", "USD")
    crypto_df = clean_crypto_data(raw_crypto)

    df = add_trend_filter(stock_df)
    df = add_momentum(df)
    df = add_relative_strength(df, crypto_df)
    df = add_entry_exit_signals(df)

    rows = []

    # ---------- V1 原版（含逐日權益曲線）----------
    v1_result = run_backtest_v1_with_equity_curve(df)
    v1_risk = calculate_risk_metrics(v1_result["equity_curve"])
    v1_perf = calculate_performance_metrics(v1_result["trades"], v1_result["initial_capital"], v1_result["final_value"], df)
    rows.append(build_comparison_row(symbol, "V1", v1_result, v1_risk, v1_perf))

    # ---------- V1 + 停利25% ----------
    # 注意：這個函式目前不產生逐日equity_curve，我們只能用完整結果
    # 這是一個已知的限制，之後可以考慮把equity_curve邏輯也加進這個函式，但這超出目前Task3範圍
    tp_result = run_backtest_v1_with_takeprofit_v2(df, take_profit_pct=25.0)
    tp_perf = calculate_performance_metrics(tp_result["trades"], tp_result["initial_capital"], tp_result["final_value"], df)
    rows.append(build_comparison_row(symbol, "V1+TakeProfit25", tp_result, None, tp_perf))

    # ---------- V1 + 移動停損20% ----------
    trail_result = run_backtest_v1_with_trailing_exit(df, trailing_pct=20.0)
    trail_perf = calculate_performance_metrics(trail_result["trades"], trail_result["initial_capital"], trail_result["final_value"], df)
    rows.append(build_comparison_row(symbol, "V1+Trailing20", trail_result, None, trail_perf))

    # ---------- Buy & Hold ----------
    bh_result = calculate_buy_and_hold(df)
    rows.append(build_comparison_row(symbol, "Buy&Hold", bh_result, None, None))

    return pd.DataFrame(rows)


if __name__ == "__main__":
    result_df = compare_all_strategies("BTDR")
    print(result_df.to_string(index=False))