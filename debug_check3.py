from src.stock_data import get_long_history_stock_data, get_crypto_daily_data, clean_crypto_data
from src.strategy_v1 import (
    add_trend_filter, add_momentum, add_relative_strength,
    add_entry_exit_signals, run_backtest_v1, run_backtest_v1_with_takeprofit,
    calculate_buy_and_hold
)

symbols = ["BTDR", "SPY", "QQQ", "AAPL", "NVDA", "MARA", "IREN"]

raw_crypto = get_crypto_daily_data('BTC', 'USD')
crypto_df = clean_crypto_data(raw_crypto)

print(f"{'股票':<8}{'原V1報酬率':<14}{'V1.1(含停利)報酬率':<20}{'B&H報酬率':<14}{'是否改善'}")
print("-" * 80)

for symbol in symbols:
    stock_df = get_long_history_stock_data(symbol, period="2y")
    if stock_df.empty or len(stock_df) < 200:
        print(f"{symbol:<8}資料不足")
        continue

    df = add_trend_filter(stock_df)
    df = add_momentum(df)
    df = add_relative_strength(df, crypto_df)
    df = add_entry_exit_signals(df)

    original = run_backtest_v1(df)
    with_tp = run_backtest_v1_with_takeprofit(df, take_profit_pct=25.0)
    bh = calculate_buy_and_hold(df)

    improved = with_tp["total_return_pct"] > original["total_return_pct"]
    print(f"{symbol:<8}{original['total_return_pct']:<14}{with_tp['total_return_pct']:<20}{bh['total_return_pct']:<14}{improved}")