# compare_strategies.py
# 統一比較 Strategy V1 各版本 vs Buy & Hold，在單一股票上的完整績效表現

import pandas as pd
from src.regime_analysis import build_regime_series
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

def analyze_performance_by_regime(symbol, period="2y"):
    """
    針對單一股票，把 Strategy V1（原版）的每一筆完整交易，
    依照「進場當天的市場狀態」分類，統計各狀態下的績效表現。

    回傳：一個 DataFrame，欄位為 Stock, Strategy, Regime, Return, Trades（該狀態下的交易筆數與平均報酬）
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

    v1_result = run_backtest_v1_with_equity_curve(df)
    v1_perf = calculate_performance_metrics(v1_result["trades"], v1_result["initial_capital"], v1_result["final_value"], df)
    completed_trades = v1_perf["completed_trades"]

    if not completed_trades:
        return pd.DataFrame([{"Stock": symbol, "Strategy": "V1", "Regime": "N/A", "Return_avg_pct": None, "Trades": 0}])

    # 取得市場狀態對照表
    regime_df = build_regime_series(period=period)
    regime_lookup = dict(zip(regime_df["date"], regime_df["regime"]))

    # 幫每一筆交易，找出「進場當天」屬於哪個市場狀態
    for trade in completed_trades:
        trade["entry_regime"] = regime_lookup.get(trade["entry_date"], "Unknown")

    # 依狀態分組統計
    rows = []
    for regime_name in ["Risk-On", "Risk-Off", "Mixed"]:
        regime_trades = [t for t in completed_trades if t["entry_regime"] == regime_name]
        if regime_trades:
            avg_return = round(sum(t["return_pct"] for t in regime_trades) / len(regime_trades), 2)
            win_count = len([t for t in regime_trades if t["return_pct"] > 0])
            win_rate = round(win_count / len(regime_trades) * 100, 2)
        else:
            avg_return = None
            win_rate = None

        rows.append({
            "Stock": symbol,
            "Strategy": "V1",
            "Regime": regime_name,
            "Trades": len(regime_trades),
            "AvgReturn_pct": avg_return,
            "WinRate_pct": win_rate
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    result_df = compare_all_strategies("BTDR")
    print(result_df.to_string(index=False))

    print("\n\n===== 跨市場狀態績效分析 =====\n")
    regime_result = analyze_performance_by_regime("BTDR")
    print(regime_result.to_string(index=False))