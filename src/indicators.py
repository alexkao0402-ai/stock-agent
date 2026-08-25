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


def add_momentum(df: pd.DataFrame, periods: int = 126) -> pd.DataFrame:
    result = df.sort_values("date").copy()
    result["momentum_6m"] = result["close"].pct_change(periods=periods)
    return result


def add_relative_strength(
    stock_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    periods: int = 126,
) -> pd.DataFrame:
    """Align stock and benchmark on date and compare trailing returns only."""
    stock = stock_df.sort_values("date").copy()
    benchmark = benchmark_df[["date", "close"]].sort_values("date").copy()
    benchmark["benchmark_return_6m"] = benchmark["close"].pct_change(periods=periods)
    benchmark = benchmark.rename(columns={"close": "benchmark_close"})
    merged = stock.merge(benchmark, on="date", how="inner", validate="one_to_one")
    if "momentum_6m" not in merged:
        merged["momentum_6m"] = merged["close"].pct_change(periods=periods)
    merged["outperforms_benchmark"] = (
        merged["momentum_6m"] > merged["benchmark_return_6m"]
    )
    return merged
