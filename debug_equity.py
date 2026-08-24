from src.stock_data import (
    get_long_history_stock_data,
    get_crypto_daily_data,
    clean_crypto_data
)

from src.strategy_v1 import (
    add_trend_filter,
    add_momentum,
    add_relative_strength,
    add_entry_exit_signals,
    run_backtest_v1_with_equity_curve,
    calculate_max_drawdown,
    calculate_risk_metrics
)


# ==========================================
# 1. 取得 BTDR
# ==========================================

stock_df = get_long_history_stock_data(
    "BTDR",
    period="2y"
)

raw_crypto = get_crypto_daily_data(
    "BTC",
    "USD"
)

crypto_df = clean_crypto_data(
    raw_crypto
)


# ==========================================
# 2. 建立 Strategy V1
# ==========================================

df = add_trend_filter(stock_df)

df = add_momentum(df)

df = add_relative_strength(
    df,
    crypto_df
)

df = add_entry_exit_signals(df)


# ==========================================
# 3. 回測
# ==========================================

result = run_backtest_v1_with_equity_curve(df)


# ==========================================
# 4. Max Drawdown
# ==========================================

dd = calculate_max_drawdown(
    result["equity_curve"]
)

risk = calculate_risk_metrics(
    result["equity_curve"]
)

print("\n===== Risk Metrics =====")

print(
    f"Annualized Volatility: "
    f"{risk['annualized_volatility_pct']}%"
)

print(
    f"Sharpe Ratio: "
    f"{risk['sharpe_ratio']}"
)

print(
    f"Sortino Ratio: "
    f"{risk['sortino_ratio']}"
)

print(
    f"Maximum Drawdown: "
    f"{risk['max_drawdown_pct']}%"
)


# ==========================================
# 5. 印出結果
# ==========================================

print("\n===== Equity Curve Test =====")

print(
    f"Initial Capital: "
    f"${result['initial_capital']}"
)

print(
    f"Final Value: "
    f"${result['final_value']}"
)

print(
    f"Total Return: "
    f"{result['total_return_pct']}%"
)

print(
    f"Trades: "
    f"{result['number_of_trades']}"
)

print(
    f"Max Drawdown: "
    f"{dd['max_drawdown_pct']}%"
)

print(
    f"Peak Date: "
    f"{dd['peak_date']}"
)

print(
    f"Trough Date: "
    f"{dd['trough_date']}"
)


# ==========================================
# 6. 檢查 Equity Curve
# ==========================================

print("\n===== Equity Curve =====")

print(
    result["equity_curve"].tail(10)
)