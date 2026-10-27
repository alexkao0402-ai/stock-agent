"""Pre-registered signal rules for the large-cap candidate study.

Every signal is formed from data available at the session close.  The portfolio
engine executes changes at the following session's open.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ordered(raw: pd.DataFrame) -> pd.DataFrame:
    out = raw.copy()
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def bollinger_mean_reversion(raw: pd.DataFrame) -> pd.DataFrame:
    """20-day, 2-sigma lower-band entry; mid-band or 10-session exit."""
    df = _ordered(raw)
    df["middle"] = df["close"].rolling(20, min_periods=20).mean()
    std = df["close"].rolling(20, min_periods=20).std(ddof=0)
    df["lower"] = df["middle"] - 2.0 * std
    df["entry_signal"] = df["close"] < df["lower"]
    df["exit_signal"] = df["close"] >= df["middle"]
    df["score"] = ((df["lower"] - df["close"]) / df["close"]).clip(lower=0)
    return df


def donchian_breakout(raw: pd.DataFrame) -> pd.DataFrame:
    """Close above the prior 55-session high; exit below prior 20-session low."""
    df = _ordered(raw)
    df["entry_level"] = df["high"].shift(1).rolling(55, min_periods=55).max()
    df["exit_level"] = df["low"].shift(1).rolling(20, min_periods=20).min()
    df["entry_signal"] = df["close"] > df["entry_level"]
    df["exit_signal"] = df["close"] < df["exit_level"]
    df["score"] = (df["close"] / df["entry_level"] - 1).replace([np.inf, -np.inf], np.nan)
    return df


def volatility_contraction_breakout(raw: pd.DataFrame) -> pd.DataFrame:
    """20-day breakout after range contraction; EMA20 or 40-session exit.

    Contraction is defined without future data: the 20-session mean true range
    as a fraction of close must be at or below its trailing 126-session 20th
    percentile.  The breakout level is the prior 20-session high.
    """
    df = _ordered(raw)
    previous_close = df["close"].shift(1)
    true_range = pd.concat(
        [df["high"] - df["low"], (df["high"] - previous_close).abs(), (df["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    df["range_ratio"] = true_range.rolling(20, min_periods=20).mean() / df["close"]
    df["contraction_threshold"] = df["range_ratio"].rolling(126, min_periods=126).quantile(0.20)
    df["breakout_level"] = df["high"].shift(1).rolling(20, min_periods=20).max()
    df["ema20"] = df["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    contracted = df["range_ratio"] <= df["contraction_threshold"]
    df["entry_signal"] = contracted & (df["close"] > df["breakout_level"])
    df["exit_signal"] = df["close"] < df["ema20"]
    df["score"] = (df["close"] / df["breakout_level"] - 1).replace([np.inf, -np.inf], np.nan)
    return df


PRICE_STRATEGIES = {
    "Bollinger Band Mean Reversion": (bollinger_mean_reversion, 10),
    "Donchian Breakout": (donchian_breakout, None),
    "Volatility Contraction Breakout": (volatility_contraction_breakout, 40),
}


def pead_availability(earnings_events: pd.DataFrame | None) -> dict:
    """Reject PEAD unless release timestamps and provenance are supplied."""
    required = {"symbol", "released_at", "reported_eps", "expected_eps", "source", "available_at"}
    missing = sorted(required.difference(earnings_events.columns)) if earnings_events is not None else sorted(required)
    return {
        "comparable": not missing and not earnings_events.empty,
        "missing_fields": missing,
        "reason": None if not missing and not earnings_events.empty else (
            "No point-in-time earnings event set with release timestamp, consensus provenance, "
            "and data-availability timestamp was provided. PEAD was not backtested."
        ),
    }
