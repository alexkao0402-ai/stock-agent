"""Momentum and relative-strength signals using SPY as benchmark."""

import pandas as pd

from src.indicators import add_momentum, add_moving_averages, add_relative_strength


def momentum_relative_strength_signals(stock_df: pd.DataFrame, spy_df: pd.DataFrame, max_holding_days: int = 20) -> pd.DataFrame:
    stock = add_momentum(add_moving_averages(stock_df), periods=20)
    spy = add_moving_averages(spy_df)
    result = add_relative_strength(stock, spy, periods=20)
    # Compute SPY's MA200 on the complete SPY history before date alignment.
    # Recomputing it after the inner join could silently change the window when
    # the stock has missing trading dates.
    result = result.merge(
        spy[["date", "ma200"]].rename(columns={"ma200": "spy_ma200"}),
        on="date",
        how="inner",
        validate="one_to_one",
    )
    warm = result[["ma200", "return_20d", "benchmark_return_20d", "spy_ma200"]].notna().all(axis=1)
    result["entry_signal"] = False
    result["exit_signal"] = False
    result["signal"] = None
    result["entry_reason"] = "Close > MA200, SPY favorable, positive 20D return, and outperforming SPY"
    result["exit_reason"] = "20D relative strength no longer beats SPY or 20-day holding limit"
    in_position = False
    holding_days = 0
    for i, row in result.iterrows():
        if not warm.loc[i]:
            continue
        entry = (
            row["close"] > row["ma200"]
            and row["benchmark_close"] > row["spy_ma200"]
            and row["return_20d"] > 0
            and row["return_20d"] > row["benchmark_return_20d"]
        )
        if not in_position and entry:
            result.at[i, "entry_signal"] = True
            result.at[i, "signal"] = "buy"
            in_position = True
            holding_days = 0
        elif in_position:
            holding_days += 1
            if row["return_20d"] <= row["benchmark_return_20d"] or holding_days >= max_holding_days:
                result.at[i, "exit_signal"] = True
                result.at[i, "signal"] = "sell"
                in_position = False
                holding_days = 0
    return result
