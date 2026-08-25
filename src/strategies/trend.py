"""Long-only large-cap trend-following signals."""

import pandas as pd

from src.indicators import add_moving_averages


def trend_following_signals(df: pd.DataFrame) -> pd.DataFrame:
    result = add_moving_averages(df)
    warm = result[["ma50", "ma200"]].notna().all(axis=1)
    result["entry_signal"] = warm & (result["close"] > result["ma200"]) & (result["ma50"] > result["ma200"])
    result["exit_signal"] = warm & (result["close"] < result["ma200"])
    result["entry_reason"] = "Close > MA200 and MA50 > MA200"
    result["exit_reason"] = "Close < MA200"
    return result
