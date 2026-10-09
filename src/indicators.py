"""Shared, backward-looking indicators for strategy research."""

from __future__ import annotations

import pandas as pd


def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    result = df.sort_values("date").copy()
    for window in (20, 50, 200):
        result[f"ma{window}"] = result["close"].rolling(window, min_periods=window).mean()
    return result


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    result = df.sort_values("date").copy()
    delta = result["close"].diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    result[f"rsi{period}"] = 100 - (100 / (1 + rs))
    result.loc[(avg_loss == 0) & (avg_gain > 0), f"rsi{period}"] = 100.0
    return result


def add_momentum(df: pd.DataFrame, periods: int = 20) -> pd.DataFrame:
    result = df.sort_values("date").copy()
    result[f"return_{periods}d"] = result["close"].pct_change(periods=periods)
    return result


def add_zscore(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Add a trailing price Z-score using only observations available that day."""
    result = df.sort_values("date").copy()
    rolling = result["close"].rolling(window, min_periods=window)
    mean = rolling.mean()
    std = rolling.std(ddof=0).replace(0, float("nan"))
    result[f"zscore{window}"] = (result["close"] - mean) / std
    return result


def add_relative_strength(
    stock_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    periods: int = 20,
) -> pd.DataFrame:
    """Align stock and benchmark on date and compare trailing returns only."""
    stock = stock_df.sort_values("date").copy()
    benchmark = benchmark_df[["date", "close"]].sort_values("date").copy()
    benchmark[f"benchmark_return_{periods}d"] = benchmark["close"].pct_change(periods=periods)
    benchmark = benchmark.rename(columns={"close": "benchmark_close"})
    merged = stock.merge(benchmark, on="date", how="inner", validate="one_to_one")
    stock_return_col = f"return_{periods}d"
    benchmark_return_col = f"benchmark_return_{periods}d"
    if stock_return_col not in merged:
        merged[stock_return_col] = merged["close"].pct_change(periods=periods)
    merged["outperforms_benchmark"] = (
        merged[stock_return_col] > merged[benchmark_return_col]
    )
    merged[f"relative_strength_{periods}d"] = merged[stock_return_col] - merged[benchmark_return_col]
    return merged
