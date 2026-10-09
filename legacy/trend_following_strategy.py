"""Archived MA50/MA200 trend strategy; not part of the active swing system."""

import pandas as pd

from src.indicators import add_moving_averages


def trend_following_signals(df: pd.DataFrame) -> pd.DataFrame:
    result = add_moving_averages(df)
    warm = result[["ma50", "ma200"]].notna().all(axis=1)
    result["entry_signal"] = warm & (result["close"] > result["ma200"]) & (result["ma50"] > result["ma200"])
    result["exit_signal"] = warm & (result["close"] < result["ma200"])
    return result
