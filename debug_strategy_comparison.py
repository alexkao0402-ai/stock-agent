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
    run_backtest_v1_with_takeprofit_v2,
    run_backtest_v1_with_trailing_exit,
    calculate_buy_and_hold,
    calculate_performance_metrics,
    calculate_risk_metrics
)


SYMBOLS = [
    "BTDR",
    "SPY",
    "QQQ",
    "AAPL",
    "NVDA",
    "MARA",
    "IREN"
]


def prepare_data(symbol, crypto_df):

    stock_df = get_long_history_stock_data(
        symbol,
        period="2y"
    )

    if stock_df.empty or len(stock_df) < 200:
        return None

    df = add_trend_filter(stock_df)
    df = add_momentum(df)
    df = add_relative_strength(
        df,
        crypto_df
    )
    df = add_entry_exit_signals(df)

    return df


def calculate_strategy_metrics(
    symbol,
    strategy_name,
    result,
    df
):

    metrics = calculate_performance_metrics(
        result["trades"],
        result["initial_capital"],
        result["final_value"],
        df
    )

    risk = calculate_risk_metrics(
        result["equity_curve"]
    )

    return {
        "symbol": symbol,
        "strategy": strategy_name,
        "return": result["total_return_pct"],
        "cagr": metrics["cagr_pct"],
        "volatility": risk["annualized_volatility_pct"],
        "sharpe": risk["sharpe_ratio"],
        "sortino": risk["sortino_ratio"],
        "max_dd": risk["max_drawdown_pct"],
        "win_rate": metrics["win_rate_pct"],
        "profit_factor": metrics["profit_factor"],
        "trades": metrics["number_of_completed_trades"]
    }


def main():

    print("=" * 100)
    print("V1.2 STRATEGY COMPARISON")
    print("=" * 100)

    # ==========================================
    # BTC benchmark
    # ==========================================

    raw_crypto = get_crypto_daily_data(
        "BTC",
        "USD"
    )

    crypto_df = clean_crypto_data(
        raw_crypto
    )

    results = []

    # ==========================================
    # Analyze each stock
    # ==========================================

    for symbol in SYMBOLS:

        print(f"\nAnalyzing {symbol}...")

        df = prepare_data(
            symbol,
            crypto_df
        )

        if df is None:

            print(
                f"{symbol}: insufficient data"
            )

            continue

        # ======================================
        # V1
        # ======================================

        v1 = run_backtest_v1_with_equity_curve(
            df
        )

        results.append(
            calculate_strategy_metrics(
                symbol,
                "V1",
                v1,
                df
            )
        )

        # ======================================
        # TP25
        # ======================================

        tp25 = run_backtest_v1_with_takeprofit_v2(
            df,
            take_profit_pct=25.0
        )

        # 如果 TP25 暫時沒有 equity_curve，
        # 先只記錄基本績效。

        tp25_metrics = calculate_performance_metrics(
            tp25["trades"],
            tp25["initial_capital"],
            tp25["final_value"],
            df
        )

        results.append({
            "symbol": symbol,
            "strategy": "TP25",
            "return": tp25["total_return_pct"],
            "cagr": tp25_metrics["cagr_pct"],
            "volatility": None,
            "sharpe": None,
            "sortino": None,
            "max_dd": None,
            "win_rate": tp25_metrics["win_rate_pct"],
            "profit_factor": tp25_metrics["profit_factor"],
            "trades": tp25_metrics["number_of_completed_trades"]
        })

        # ======================================
        # Trail20
        # ======================================

        trail20 = run_backtest_v1_with_trailing_exit(
            df,
            trailing_pct=20.0
        )

        trail_metrics = calculate_performance_metrics(
            trail20["trades"],
            trail20["initial_capital"],
            trail20["final_value"],
            df
        )

        results.append({
            "symbol": symbol,
            "strategy": "Trail20",
            "return": trail20["total_return_pct"],
            "cagr": trail_metrics["cagr_pct"],
            "volatility": None,
            "sharpe": None,
            "sortino": None,
            "max_dd": None,
            "win_rate": trail_metrics["win_rate_pct"],
            "profit_factor": trail_metrics["profit_factor"],
            "trades": trail_metrics["number_of_completed_trades"]
        })

        # ======================================
        # Buy & Hold
        # ======================================

        bh = calculate_buy_and_hold(df)

        results.append({
            "symbol": symbol,
            "strategy": "Buy & Hold",
            "return": bh["total_return_pct"],
            "cagr": None,
            "volatility": None,
            "sharpe": None,
            "sortino": None,
            "max_dd": None,
            "win_rate": None,
            "profit_factor": None,
            "trades": 0
        })

    # ==========================================
    # Print final table
    # ==========================================

    print("\n")
    print("=" * 120)
    print("FINAL STRATEGY COMPARISON")
    print("=" * 120)

    print(
        f"{'Stock':<8}"
        f"{'Strategy':<12}"
        f"{'Return':>10}"
        f"{'CAGR':>10}"
        f"{'Vol':>10}"
        f"{'Sharpe':>10}"
        f"{'Sortino':>10}"
        f"{'MaxDD':>10}"
        f"{'WinRate':>10}"
        f"{'PF':>10}"
        f"{'Trades':>8}"
    )

    print("-" * 120)

    for r in results:

        def fmt(value):

            if value is None:
                return "N/A"

            return str(value)

        print(
            f"{r['symbol']:<8}"
            f"{r['strategy']:<12}"
            f"{fmt(r['return']):>10}"
            f"{fmt(r['cagr']):>10}"
            f"{fmt(r['volatility']):>10}"
            f"{fmt(r['sharpe']):>10}"
            f"{fmt(r['sortino']):>10}"
            f"{fmt(r['max_dd']):>10}"
            f"{fmt(r['win_rate']):>10}"
            f"{fmt(r['profit_factor']):>10}"
            f"{fmt(r['trades']):>8}"
        )


if __name__ == "__main__":
    main()