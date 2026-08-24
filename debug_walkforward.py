from src.stock_data import get_long_history_stock_data, get_crypto_daily_data, clean_crypto_data
from src.strategy_v1 import (
    add_trend_filter, add_momentum, add_relative_strength,
    add_entry_exit_signals, run_backtest_v1_with_equity_curve
)
from src.walk_forward import run_walk_forward_analysis

stock_df = get_long_history_stock_data("BTDR", period="2y")
raw_crypto = get_crypto_daily_data("BTC", "USD")
crypto_df = clean_crypto_data(raw_crypto)

df = add_trend_filter(stock_df)
df = add_momentum(df)
df = add_relative_strength(df, crypto_df)
df = add_entry_exit_signals(df)

result = run_backtest_v1_with_equity_curve(df)

wf_result = run_walk_forward_analysis("BTDR", result["equity_curve"], df, window_months=6)
print(wf_result.to_string(index=False))