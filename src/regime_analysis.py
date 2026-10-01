"""Equity-market regime derived only from trailing SPY data."""

from __future__ import annotations

import pandas as pd

from src.stock_data import get_long_history_stock_data


def classify_spy_regime(spy_df: pd.DataFrame) -> pd.DataFrame:
    result = spy_df[["date", "close"]].sort_values("date").copy()
    result["spy_ma200"] = result["close"].rolling(200, min_periods=200).mean()
    result = result.rename(columns={"close": "spy_close"})
    result["regime"] = pd.NA
    ready = result["spy_ma200"].notna()
    result.loc[ready & (result["spy_close"] > result["spy_ma200"]), "regime"] = "Bull Market"
    result.loc[ready & (result["spy_close"] <= result["spy_ma200"]), "regime"] = "Bear Market"
    return result


def build_regime_series(period: str = "5y") -> pd.DataFrame:
    return classify_spy_regime(get_long_history_stock_data("SPY", period=period))
