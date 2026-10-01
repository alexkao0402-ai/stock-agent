"""
Strategy V1: trend + momentum + relative strength.

Strategy rules are intentionally unchanged.
Execution/backtesting is delegated to backtest_engine.py.
"""

import pandas as pd

from src.backtest_engine import (
    BacktestConfig,
    calculate_buy_and_hold,
    run_backtest,
)
from src.metrics import (
    build_comparison_row,
    build_trade_diagnostics,
    calculate_max_drawdown,
    calculate_performance_metrics,
    calculate_risk_metrics,
)


def add_trend_filter(df, window=200):
    df = df.copy()
    df["ma200"] = df["close"].rolling(window=window).mean()
    df["is_bullish_regime"] = df["close"] > df["ma200"]
    return df


def add_momentum(df, months=6, trading_days_per_month=21):
    df = df.copy()
    window_days = months * trading_days_per_month
    df["momentum_pct"] = df["close"].pct_change(periods=window_days) * 100
    return df


def add_relative_strength(stock_df, benchmark_df, months=6, trading_days_per_month=21):
    df = stock_df.copy()
    window_days = months * trading_days_per_month
    benchmark_df = benchmark_df.copy()
    benchmark_df["benchmark_momentum_pct"] = benchmark_df["close"].pct_change(periods=window_days) * 100
    benchmark_slice = benchmark_df[["date", "benchmark_momentum_pct"]].drop_duplicates("date")
    df = df.merge(benchmark_slice, on="date", how="left")
    df["outperforms_benchmark"] = df["momentum_pct"] > df["benchmark_momentum_pct"]
    return df


def add_entry_exit_signals(df):
    """Generate Strategy V1 signals using only information available at day T close."""
    df = df.copy()
    entry_condition = (
        (df["is_bullish_regime"] == True)
        & (df["momentum_pct"] > 0)
        & (df["outperforms_benchmark"] == True)
    )
    exit_condition = (
        (df["is_bullish_regime"] == False)
        | (df["outperforms_benchmark"] == False)
    )
    previous_entry_condition = entry_condition.shift(1).fillna(False).astype(bool)
    previous_exit_condition = exit_condition.shift(1).fillna(False).astype(bool)
    new_buy_signal = entry_condition & (~previous_entry_condition)
    new_sell_signal = exit_condition & (~previous_exit_condition)
    df["signal"] = None
    df.loc[new_buy_signal, "signal"] = "buy"
    df.loc[new_sell_signal, "signal"] = "sell"
    # Display/backward-compatibility only. The engine does not consume this field.
    df["execution_price"] = df["open"].shift(-1)
    return df


def _config(initial_capital, transaction_cost_pct, slippage_pct, exit_mode,
            take_profit_pct=25.0, trailing_pct=20.0):
    return BacktestConfig(
        initial_capital=initial_capital,
        transaction_cost_pct=transaction_cost_pct,
        slippage_pct=slippage_pct,
        exit_mode=exit_mode,
        take_profit_pct=take_profit_pct,
        trailing_pct=trailing_pct,
    )


def run_backtest_v1(df, initial_capital=10000, transaction_cost_pct=0.001, slippage_pct=0.0005):
    return run_backtest(df, _config(initial_capital, transaction_cost_pct, slippage_pct, "signal_only"))


def run_backtest_v1_with_equity_curve(df, initial_capital=10000, transaction_cost_pct=0.001, slippage_pct=0.0005):
    return run_backtest_v1(
        df,
        initial_capital=initial_capital,
        transaction_cost_pct=transaction_cost_pct,
        slippage_pct=slippage_pct,
    )


def run_backtest_v1_with_takeprofit_v2(
    df,
    initial_capital=10000,
    transaction_cost_pct=0.001,
    slippage_pct=0.0005,
    take_profit_pct=25.0,
):
    return run_backtest(
        df,
        _config(
            initial_capital,
            transaction_cost_pct,
            slippage_pct,
            "take_profit",
            take_profit_pct=take_profit_pct,
        ),
    )


def run_backtest_v1_with_trailing_exit(
    df,
    initial_capital=10000,
    transaction_cost_pct=0.001,
    slippage_pct=0.0005,
    trailing_pct=20.0,
):
    return run_backtest(
        df,
        _config(
            initial_capital,
            transaction_cost_pct,
            slippage_pct,
            "trailing",
            trailing_pct=trailing_pct,
        ),
    )
