"""Archived Z-score ablation candidate; not a primary V1 swing strategy."""

import pandas as pd

from src.indicators import add_moving_averages, add_zscore


def statistical_mean_reversion_signals(df: pd.DataFrame, z_window=20, entry_z=-2.0, exit_z=0.0, max_holding_days=20):
    result = add_zscore(add_moving_averages(df), window=z_window)
    z_col = f"zscore{z_window}"
    result["entry_signal"] = False
    result["exit_signal"] = False
    in_position = False
    holding_days = 0
    for i, row in result.iterrows():
        if pd.isna(row["ma200"]) or pd.isna(row[z_col]):
            continue
        if not in_position and row["close"] > row["ma200"] and row[z_col] < entry_z:
            result.at[i, "entry_signal"] = True
            in_position = True
            holding_days = 0
        elif in_position:
            holding_days += 1
            if row[z_col] >= exit_z or row["close"] < row["ma200"] or holding_days >= max_holding_days:
                result.at[i, "exit_signal"] = True
                in_position = False
                holding_days = 0
    return result
