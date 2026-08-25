"""Long-only statistical mean reversion with a long-term trend filter."""

import pandas as pd

from src.indicators import add_moving_averages, add_zscore


def statistical_mean_reversion_signals(
    df: pd.DataFrame,
    z_window: int = 20,
    entry_z: float = -2.0,
    exit_z: float = 0.0,
    max_holding_days: int = 20,
) -> pd.DataFrame:
    """Enter on a large negative deviation and exit after reversion or risk failure."""
    result = add_zscore(add_moving_averages(df), window=z_window)
    z_col = f"zscore{z_window}"
    result["entry_signal"] = False
    result["exit_signal"] = False
    result["entry_reason"] = f"Close > MA200 and {z_col} < {entry_z:g}"
    result["exit_reason"] = f"{z_col} >= {exit_z:g}, Close < MA200, or {max_holding_days}-day limit"
    in_position = False
    holding_days = 0
    for i, row in result.iterrows():
        warm = pd.notna(row["ma200"]) and pd.notna(row[z_col])
        if not warm:
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
