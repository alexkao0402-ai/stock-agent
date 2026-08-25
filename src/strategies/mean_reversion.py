"""Trend-filtered mean-reversion signals."""

import pandas as pd

from src.indicators import add_moving_averages, add_rsi


def mean_reversion_signals(df: pd.DataFrame, max_holding_days: int = 20) -> pd.DataFrame:
    result = add_rsi(add_moving_averages(df))
    result["entry_signal"] = False
    result["exit_signal"] = False
    result["entry_reason"] = "Close > MA200 and RSI14 < 30"
    result["exit_reason"] = "RSI14 > 50, Close > MA20, or maximum holding period reached"
    in_position = False
    holding_days = 0
    for i, row in result.iterrows():
        warm = pd.notna(row["ma20"]) and pd.notna(row["ma200"]) and pd.notna(row["rsi14"])
        if not warm:
            continue
        if not in_position and row["close"] > row["ma200"] and row["rsi14"] < 30:
            result.at[i, "entry_signal"] = True
            in_position = True  # execution occurs next session; counting begins there
            holding_days = 0
        elif in_position:
            holding_days += 1
            if row["rsi14"] > 50 or row["close"] > row["ma20"] or holding_days >= max_holding_days:
                result.at[i, "exit_signal"] = True
                in_position = False
                holding_days = 0
    return result
