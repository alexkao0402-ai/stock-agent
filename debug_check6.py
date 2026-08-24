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
    run_backtest_v1,
    run_backtest_v1_with_takeprofit_v2,
    run_backtest_v1_with_trailing_exit,
    calculate_buy_and_hold
)


def calculate_max_drawdown(df, result):
    """
    Calculate maximum drawdown using the trade strategy's
    daily portfolio value.

    This function reconstructs portfolio value from trades.
    """

    initial_capital = result["initial_capital"]

    cash = initial_capital
    shares = 0

    trades = {
        trade["date"]: trade
        for trade in result["trades"]
    }

    equity = []

    for _, row in df.iterrows():

        date = row["date"]
        price = row["close"]

        if date in trades:

            trade = trades[date]

            if trade["action"] == "buy":
                shares = trade["shares"]
                cash = 0

            elif trade["action"] == "sell":
                cash = (
                    trade["shares"]
                    * trade["execution_price"]
                )
                shares = 0

        portfolio_value = cash + shares * price

        equity.append(portfolio_value)

    if not equity:
        return 0

    peak = equity[0]
    max_drawdown = 0

    for value in equity:

        if value > peak:
            peak = value

        drawdown = (
            value - peak
        ) / peak

        if drawdown < max_drawdown:
            max_drawdown = drawdown

    return round(max_drawdown * 100, 2)


symbols = [
    "BTDR",
    "SPY",
    "QQQ",
    "AAPL",
    "NVDA",
    "MARA",
    "IREN"
]

raw_crypto = get_crypto_daily_data("BTC", "USD")
crypto_df = clean_crypto_data(raw_crypto)


print(
    f"{'Stock':<8}"
    f"{'V1 DD':<12}"
    f"{'TP25 DD':<12}"
    f"{'Trail20 DD':<14}"
)

print("-" * 55)


for symbol in symbols:

    stock_df = get_long_history_stock_data(
        symbol,
        period="2y"
    )

    if stock_df.empty or len(stock_df) < 200:
        continue

    df = add_trend_filter(stock_df)
    df = add_momentum(df)
    df = add_relative_strength(df, crypto_df)
    df = add_entry_exit_signals(df)

    v1 = run_backtest_v1(df)

    tp = run_backtest_v1_with_takeprofit_v2(
        df,
        take_profit_pct=25
    )

    trail = run_backtest_v1_with_trailing_exit(
        df,
        trailing_pct=20
    )

    v1_dd = calculate_max_drawdown(df, v1)
    tp_dd = calculate_max_drawdown(df, tp)
    trail_dd = calculate_max_drawdown(df, trail)

    print(
        f"{symbol:<8}"
        f"{v1_dd:<12}"
        f"{tp_dd:<12}"
        f"{trail_dd:<14}"
    )