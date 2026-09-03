"""Read-only projection of the append-only V12 paper-trading ledger.

This module never instantiates :class:`AppendOnlyLedger`, because its
constructor initializes a database.  The dashboard opens an existing SQLite
file in ``mode=ro`` and converts immutable events into display-only state.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd


DEFAULT_LEDGER_PATH = Path("paper_ledger") / "v12_events.sqlite3"
FROZEN_VERSION = "V12-FROZEN-2026-08-28"
HISTORICAL_SHARPE = 0.64074


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_content(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "portfolio_id": row["portfolio_id"],
        "event_type": row["event_type"],
        "strategy_version": row["strategy_version"],
        "signal_timestamp": row["signal_timestamp"],
        "execution_rule": row["execution_rule"],
        "data_asof": row["data_asof"],
        "ticker": row["ticker"],
        "action": row["action"],
        "expected_price": row["expected_price"],
        "fill_price": row["fill_price"],
        "quantity": row["quantity"],
        "cost": row["cost"],
        "reason": row["reason"],
        "payload": row.get("payload") or {},
    }


def read_ledger_events(path: str | Path = DEFAULT_LEDGER_PATH) -> list[dict[str, Any]]:
    """Read ledger events without creating or modifying the SQLite file."""
    ledger_path = Path(path)
    if not ledger_path.is_file():
        return []
    uri = f"file:{ledger_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='event_log'"
        ).fetchone()
        if table is None:
            raise RuntimeError("ledger is missing the event_log table")
        rows = connection.execute("SELECT * FROM event_log ORDER BY sequence").fetchall()
    finally:
        connection.close()
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("ledger payload is not valid JSON") from exc
        output.append(item)
    return output


def verify_event_chain(events: list[dict[str, Any]]) -> bool:
    """Verify content hashes and the previous-event chain without writing."""
    previous = "GENESIS"
    for row in events:
        content_hash = hashlib.sha256(
            _canonical(_event_content(row)).encode("utf-8")
        ).hexdigest()
        if content_hash != row.get("content_hash"):
            raise RuntimeError("ledger content hash mismatch")
        if row.get("previous_event_hash") != previous:
            raise RuntimeError("ledger hash chain is broken")
        expected = hashlib.sha256(
            f"{previous}|{content_hash}|{row['created_at']}".encode("utf-8")
        ).hexdigest()
        if expected != row.get("event_hash"):
            raise RuntimeError("ledger event hash mismatch")
        previous = expected
    return True


def _portfolio_events(events: list[dict[str, Any]], portfolio_id: str, event_type: str) -> list[dict[str, Any]]:
    return [
        row for row in events
        if row.get("portfolio_id") == portfolio_id and row.get("event_type") == event_type
    ]


def _initial_capital(events: list[dict[str, Any]], portfolio_id: str) -> float | None:
    rows = _portfolio_events(events, portfolio_id, "INITIALIZE")
    if not rows:
        return None
    try:
        return float(rows[-1]["payload"]["initial_capital"])
    except (KeyError, TypeError, ValueError):
        return None


def _snapshots(events: list[dict[str, Any]], portfolio_id: str) -> list[dict[str, Any]]:
    return [
        row for row in events
        if row.get("portfolio_id") == portfolio_id
        and row.get("event_type") in {"PORTFOLIO_SNAPSHOT", "VALUATION_SNAPSHOT"}
    ]


def _equity_value(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    try:
        value = float(row["payload"]["portfolio_equity"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _total_return(events: list[dict[str, Any]], portfolio_id: str) -> float | None:
    capital = _initial_capital(events, portfolio_id)
    rows = _snapshots(events, portfolio_id)
    equity = _equity_value(rows[-1]) if rows else None
    if not capital or equity is None:
        return None
    return equity / capital - 1.0


def _max_drawdown(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return worst


def _rolling_sharpe(values: list[float], periods: int = 252) -> float | None:
    if len(values) < periods + 1:
        return None
    returns = pd.Series(values, dtype=float).pct_change().dropna().tail(periods)
    if len(returns) < periods or float(returns.std(ddof=1)) == 0.0:
        return None
    return float(returns.mean() / returns.std(ddof=1) * math.sqrt(252))


def _curve(events: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    labels = {"V12_T1": "V12", "SPY_T1": "SPY", "QQQ_T1": "QQQ"}
    for portfolio_id, label in labels.items():
        for event in _snapshots(events, portfolio_id):
            value = _equity_value(event)
            if value is None:
                continue
            payload = event.get("payload") or {}
            rows.append({
                "date": str(
                    payload.get("valuation_date")
                    or payload.get("execution_date")
                    or event.get("data_asof", "")
                )[:10],
                "series": label,
                "value": value,
            })
    return pd.DataFrame(rows, columns=["date", "series", "value"])


def _latest_signal(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = _portfolio_events(events, "V12_T1", "SIGNAL")
    return rows[-1] if rows else None


def _execution_status(events: list[dict[str, Any]], signal: dict[str, Any] | None, today: date) -> tuple[str, bool, str | None]:
    if signal is None:
        return "尚未產生", False, None
    signal_date = str((signal.get("payload") or {}).get("signal_date", ""))
    matching_orders = [
        row for row in _portfolio_events(events, "V12_T1", "ORDER")
        if str((row.get("payload") or {}).get("signal_date", signal_date)) == signal_date
    ]
    execution_dates = sorted({
        str((row.get("payload") or {}).get("execution_date", ""))
        for row in matching_orders
        if (row.get("payload") or {}).get("execution_date")
    })
    scheduled = execution_dates[0] if execution_dates else None
    completed = any(
        str((row.get("payload") or {}).get("execution_date", "")) == scheduled
        for row in _snapshots(events, "V12_T1")
    ) if scheduled else False
    if completed:
        return "已執行", False, scheduled
    if scheduled:
        try:
            overdue = today > date.fromisoformat(scheduled)
        except ValueError:
            overdue = True
        return ("逾期未執行" if overdue else "等待 T+1 開盤"), overdue, scheduled
    return "等待訂單資料", True, None


def build_dashboard_snapshot(
    path: str | Path = DEFAULT_LEDGER_PATH,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Build the read-only view consumed by Streamlit."""
    current_day = today or datetime.now(timezone.utc).date()
    try:
        events = read_ledger_events(path)
        verify_event_chain(events)
        integrity_error = None
    except Exception as exc:
        events = []
        integrity_error = str(exc)

    signal = _latest_signal(events)
    execution_status, overdue, execution_date = _execution_status(events, signal, current_day)
    v12_snapshots = _snapshots(events, "V12_T1")
    formal_v12_snapshots = _portfolio_events(events, "V12_T1", "PORTFOLIO_SNAPSHOT")
    v12_values = [value for row in v12_snapshots if (value := _equity_value(row)) is not None]
    latest_snapshot = v12_snapshots[-1] if v12_snapshots else None
    portfolio_value = _equity_value(latest_snapshot)
    v12_return = _total_return(events, "V12_T1")
    spy_return = _total_return(events, "SPY_T1")
    qqq_return = _total_return(events, "QQQ_T1")
    drawdown = _max_drawdown(v12_values)
    rolling_sharpe = _rolling_sharpe(v12_values)
    t2_return = _total_return(events, "V12_T2")

    payload = (signal or {}).get("payload") or {}
    v7 = list(payload.get("v7_selected") or [])
    v8 = list(payload.get("v8_selected") or [])
    agreement = len(set(v7) & set(v8)) if signal else None
    positions = ((latest_snapshot or {}).get("payload") or {}).get("positions") or {}
    target_weights = dict(payload.get("portfolio_target_weights") or payload.get("v12_target_weights") or {})
    holdings = [
        {
            "ticker": ticker,
            "shares": float(values.get("shares", 0.0)),
            "average_cost": float(values.get("average_cost", 0.0)),
            "target_weight": target_weights.get(ticker),
        }
        for ticker, values in sorted(positions.items())
    ]
    cash = None
    if latest_snapshot:
        try:
            cash = float(latest_snapshot["payload"]["cash"])
        except (KeyError, TypeError, ValueError):
            cash = None

    statistical_warnings: list[str] = []
    if not events:
        statistical_warnings.append("尚未產生第一筆正式 Forward Signal")
    elif rolling_sharpe is None:
        statistical_warnings.append("Forward 樣本不足，尚不能計算 12 個月 Rolling Sharpe")
    elif rolling_sharpe < 0.0:
        statistical_warnings.append("Rolling Sharpe 低於 0，需觀察但不改動 Frozen V12")
    if drawdown is not None and drawdown <= -0.20:
        statistical_warnings.append("Forward drawdown 已超過 20%，需研究但不自動停用策略")

    blocked = bool(integrity_error or overdue)
    if blocked:
        health_status = "ERROR"
        health_label = "系統異常"
    elif statistical_warnings:
        health_status = "WATCH"
        health_label = "觀察"
    else:
        health_status = "NORMAL"
        health_label = "正常"

    last_data_asof = str(events[-1]["data_asof"]) if events else None
    return {
        "frozen_version": FROZEN_VERSION,
        "events": events,
        "formal_forward_rows": len(formal_v12_snapshots),
        "curve": _curve(events),
        "portfolio_value": portfolio_value,
        "cumulative_return": v12_return,
        "excess_vs_spy": None if v12_return is None or spy_return is None else v12_return - spy_return,
        "excess_vs_qqq": None if v12_return is None or qqq_return is None else v12_return - qqq_return,
        "max_drawdown": drawdown,
        "cash": cash,
        "holdings": holdings,
        "latest_signal": signal,
        "signal_date": payload.get("signal_date"),
        "market_regime": payload.get("market_regime"),
        "v7_selected": v7,
        "v8_selected": v8,
        "agreement_count": agreement,
        "target_weights": target_weights,
        "execution_status": execution_status,
        "execution_date": execution_date,
        "rolling_sharpe": rolling_sharpe,
        "sharpe_deviation": None if rolling_sharpe is None else rolling_sharpe - HISTORICAL_SHARPE,
        "t1_return": v12_return,
        "t2_return": t2_return,
        "t1_t2_spread": None if v12_return is None or t2_return is None else v12_return - t2_return,
        "health_status": health_status,
        "health_label": health_label,
        "trading_blocked": blocked,
        "integrity_error": integrity_error,
        "warnings": statistical_warnings,
        "last_data_asof": last_data_asof,
    }
