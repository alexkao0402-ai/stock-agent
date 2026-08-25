"""Momentum and relative-strength signals using SPY as benchmark."""

import pandas as pd

from src.indicators import add_momentum, add_moving_averages, add_relative_strength


def momentum_relative_strength_signals(stock_df: pd.DataFrame, spy_df: pd.DataFrame) -> pd.DataFrame:
    stock = add_momentum(add_moving_averages(stock_df))
    spy = add_moving_averages(spy_df)
    result = add_relative_strength(stock, spy)
    # Compute SPY's MA200 on the complete SPY history before date alignment.
    # Recomputing it after the inner join could silently change the window when
    # the stock has missing trading dates.
    result = result.merge(
        spy[["date", "ma200"]].rename(columns={"ma200": "spy_ma200"}),
        on="date",
        how="inner",
        validate="one_to_one",
    )
    warm = result[["ma200", "momentum_6m", "benchmark_return_6m", "spy_ma200"]].notna().all(axis=1)
    result["entry_signal"] = (
        warm
        & (result["close"] > result["ma200"])
        & (result["momentum_6m"] > 0)
        & result["outperforms_benchmark"]
        & (result["benchmark_close"] > result["spy_ma200"])
    )
    result["exit_signal"] = warm & (
        (result["close"] < result["ma200"]) | ~result["outperforms_benchmark"]
    )
    result["entry_reason"] = "Positive trend and momentum, outperforming SPY in a SPY bull market"
    result["exit_reason"] = "Close < MA200 or no longer outperforming SPY"
    return result
