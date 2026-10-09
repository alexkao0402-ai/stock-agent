"""Frozen V12 signal calculation from an immutable live input bundle."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.live_large_cap_data import LiveDataError


FROZEN_VERSION = "V12-FROZEN-2026-08-28"
TOP_N = 2
LIVE_SIGNAL_DIR = Path("live_forward_signals")


def _value_at_shift(close: pd.Series, shift: int) -> float:
    if len(close) <= shift:
        return float("nan")
    value = close.iloc[-(shift + 1)]
    return float(value) if pd.notna(value) else float("nan")


def _stock_indicators(frame: pd.DataFrame, signal_date: str) -> dict[str, Any]:
    frame = frame[pd.to_datetime(frame["trade_date"]) <= pd.Timestamp(signal_date)].copy()
    frame = frame.sort_values("trade_date")
    close = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    latest_date = str(frame["trade_date"].iloc[-1]) if len(frame) else ""
    current = float(close.iloc[-1]) if len(close) and pd.notna(close.iloc[-1]) else float("nan")
    ma200 = float(close.rolling(200, min_periods=200).mean().iloc[-1]) if len(close) else float("nan")
    skip = _value_at_shift(close, 21)

    def momentum(lookback: int) -> float:
        base = _value_at_shift(close, lookback)
        if not np.isfinite(skip) or not np.isfinite(base) or base == 0:
            return float("nan")
        return skip / base - 1.0

    return {
        "exact_month_end_price": latest_date == signal_date,
        "adjusted_close": current,
        "ma200": ma200,
        "above_ma200": bool(np.isfinite(current) and np.isfinite(ma200) and current > ma200),
        "momentum_3_1": momentum(63),
        "momentum_6_1": momentum(126),
        "momentum_12_1": momentum(252),
        "history_rows": int(len(close)),
    }


def _version_selection(signals: pd.DataFrame, version: str, spy_bull: bool) -> pd.DataFrame:
    output = signals.copy()
    if version == "V7":
        output["candidate_score"] = output["momentum_12_1"]
        required = output["momentum_12_1"].notna()
    elif version == "V8":
        rank_columns = []
        for column in ["momentum_3_1", "momentum_6_1", "momentum_12_1"]:
            rank_column = f"{column}_rank"
            output[rank_column] = output[column].rank(
                method="average", ascending=True, pct=True
            )
            rank_columns.append(rank_column)
        output["candidate_score"] = output[rank_columns].mean(axis=1, skipna=False)
        required = output[rank_columns].notna().all(axis=1)
    else:
        raise ValueError(f"Unsupported frozen version component: {version}")
    output["candidate_rank"] = output["candidate_score"].rank(
        method="first", ascending=False
    )
    output["eligible"] = output["exact_month_end_price"] & output["above_ma200"] & required
    output["selected"] = False
    if spy_bull:
        selected = output[output["eligible"]].nsmallest(TOP_N, "candidate_rank").index
        output.loc[selected, "selected"] = True
    return output


def _consensus_weights(v7: set[str], v8: set[str]) -> tuple[dict[str, float], str]:
    if not v7 and not v8:
        return {}, "Cash"
    common = v7 & v8
    union = v7 | v8
    if v7 == v8:
        return {ticker: 1.0 / len(union) for ticker in union}, "Same 2"
    if len(common) == 1 and len(union) == 3:
        shared = next(iter(common))
        return (
            {ticker: 0.50 if ticker == shared else 0.25 for ticker in union},
            "1 shared / 3 holdings",
        )
    return (
        {ticker: 1.0 / len(union) for ticker in union},
        f"Union / {len(union)} holdings",
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    return value


def compute_frozen_v12_signal(universe: pd.DataFrame, prices: pd.DataFrame) -> dict[str, Any]:
    """Apply the frozen V7/V8 consensus rules using signal-date data only."""
    required_universe = {
        "signal_date", "stable_company_id", "stable_security_id", "ticker",
        "company_market_cap", "market_cap_rank",
    }
    required_prices = {"ticker", "trade_date", "adjusted_close"}
    if not required_universe.issubset(universe.columns):
        raise LiveDataError(
            f"Universe is missing {sorted(required_universe - set(universe.columns))}"
        )
    if not required_prices.issubset(prices.columns):
        raise LiveDataError(f"Prices are missing {sorted(required_prices - set(prices.columns))}")
    signal_dates = pd.to_datetime(universe["signal_date"], errors="raise").dt.normalize().unique()
    if len(signal_dates) != 1:
        raise LiveDataError("A V12 live bundle must contain exactly one signal date")
    signal_date = pd.Timestamp(signal_dates[0]).date().isoformat()
    universe = universe.sort_values("market_cap_rank").reset_index(drop=True)
    expected_ranks = list(range(1, len(universe) + 1))
    if len(universe) != 10 or universe["market_cap_rank"].astype(int).tolist() != expected_ranks:
        raise LiveDataError("Frozen V12 requires exactly ten companies ranked 1 through 10")

    spy = _stock_indicators(prices[prices["ticker"].eq("SPY")], signal_date)
    spy_bull = bool(spy["exact_month_end_price"] and spy["above_ma200"])
    rows = []
    for item in universe.itertuples(index=False):
        indicators = _stock_indicators(prices[prices["ticker"].eq(item.ticker)], signal_date)
        rows.append(
            {
                "ticker": item.ticker,
                "stable_company_id": item.stable_company_id,
                "stable_security_id": item.stable_security_id,
                "market_cap_rank": int(item.market_cap_rank),
                **indicators,
            }
        )
    signals = pd.DataFrame(rows)
    v7 = _version_selection(signals, "V7", spy_bull)
    v8 = _version_selection(signals, "V8", spy_bull)
    v7_selected = set(v7.loc[v7["selected"], "ticker"].astype(str))
    v8_selected = set(v8.loc[v8["selected"], "ticker"].astype(str))
    weights, consensus_type = _consensus_weights(v7_selected, v8_selected)
    if weights and not np.isclose(sum(weights.values()), 1.0, atol=1e-12):
        raise AssertionError("Frozen V12 target weights do not sum to one")

    details = []
    v8_indexed = v8.set_index("ticker")
    v7_indexed = v7.set_index("ticker")
    for row in rows:
        ticker = row["ticker"]
        details.append(
            {
                **{key: _json_value(value) for key, value in row.items()},
                "v7_rank": _json_value(v7_indexed.loc[ticker, "candidate_rank"]),
                "v7_selected": bool(v7_indexed.loc[ticker, "selected"]),
                "v8_rank": _json_value(v8_indexed.loc[ticker, "candidate_rank"]),
                "v8_selected": bool(v8_indexed.loc[ticker, "selected"]),
                "target_weight": float(weights.get(ticker, 0.0)),
            }
        )
    return {
        "schema_version": 1,
        "frozen_version": FROZEN_VERSION,
        "signal_date": signal_date,
        "decision_timestamp": "T_CLOSE",
        "execution_policy": {"official": "T+1_OPEN", "challenger": "T+2_OPEN"},
        "status": "AWAITING_T1_T2_EXECUTION" if weights else "CASH_NO_ORDERS",
        "spy_bull": spy_bull,
        "spy_adjusted_close": _json_value(spy["adjusted_close"]),
        "spy_ma200": _json_value(spy["ma200"]),
        "v7_selected": sorted(v7_selected),
        "v8_selected": sorted(v8_selected),
        "consensus_type": consensus_type,
        "target_weights": dict(sorted(weights.items())),
        "universe_details": details,
        "strategy_rule_change": False,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_immutable_v12_signal(
    input_root: str | Path,
    *,
    output_directory: str | Path = LIVE_SIGNAL_DIR,
) -> tuple[Path, bool, dict[str, Any]]:
    """Read a hashed input bundle and write one immutable frozen V12 signal."""
    input_root = Path(input_root)
    input_manifest = input_root / "manifest.json"
    if not input_manifest.exists():
        raise LiveDataError("Live input manifest is missing")
    manifest = json.loads(input_manifest.read_text(encoding="utf-8"))
    for filename, expected_hash in manifest.get("files", {}).items():
        path = input_root / filename
        if not path.exists() or _sha256(path) != expected_hash:
            raise LiveDataError(f"Live input hash mismatch: {filename}")

    universe = pd.read_csv(input_root / "monthly_universe.csv")
    prices = pd.read_csv(input_root / "daily_prices.csv")
    signal = compute_frozen_v12_signal(universe, prices)
    signal["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    signal["source_manifest_sha256"] = _sha256(input_manifest)

    signal_date = signal["signal_date"]
    root = Path(output_directory) / signal_date
    signal_path = root / "v12_signal.json"
    if signal_path.exists():
        existing = json.loads(signal_path.read_text(encoding="utf-8"))
        return signal_path, False, existing
    root.mkdir(parents=True, exist_ok=True)
    temporary = signal_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(signal, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(signal_path)
    return signal_path, True, signal
