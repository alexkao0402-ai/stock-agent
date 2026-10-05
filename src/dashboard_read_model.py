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

from src.trading_calendar import last_session_of_month, next_session


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
        return "Not generated", False, None
    signal_date = str((signal.get("payload") or {}).get("signal_date", ""))
    matching_orders = [
        row for row in _portfolio_events(events, "V12_T1", "ORDER")
        if str(
            (row.get("payload") or {}).get("signal_date")
            or row.get("signal_timestamp", "")[:10]
        ) == signal_date
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
        return "Executed", False, scheduled
    if scheduled:
        try:
            overdue = today > date.fromisoformat(scheduled)
        except ValueError:
            overdue = True
        return ("Overdue" if overdue else "Waiting for T+1 open"), overdue, scheduled
    return "Waiting for order data", True, None


def _latest_rebalance(events: list[dict[str, Any]], signal: dict[str, Any] | None) -> list[dict[str, Any]]:
    if signal is None:
        return []
    signal_payload = signal.get("payload") or {}
    signal_date = str(signal_payload.get("signal_date") or "")
    target_weights = dict(
        signal_payload.get("portfolio_target_weights")
        or signal_payload.get("v12_target_weights")
        or {}
    )
    matching_fills = []
    for event in _portfolio_events(events, "V12_T1", "FILL"):
        payload = event.get("payload") or {}
        event_signal_date = str(
            payload.get("signal_date") or event.get("signal_timestamp", "")[:10]
        )
        if event_signal_date != signal_date:
            continue
        matching_fills.append(event)
    matching_fills.sort(key=lambda row: int((row.get("payload") or {}).get("sequence") or 0))
    if not matching_fills:
        return []

    first_fill_sequence = min(int(row.get("sequence") or 0) for row in matching_fills)
    prior_snapshots = [
        row for row in _snapshots(events, "V12_T1")
        if int(row.get("sequence") or 0) < first_fill_sequence
    ]
    prior_positions = ((prior_snapshots[-1] if prior_snapshots else {}).get("payload") or {}).get("positions") or {}
    running_shares = {
        str(ticker): float(values.get("shares") or 0.0)
        for ticker, values in prior_positions.items()
    }

    rows = []
    for event in matching_fills:
        payload = event.get("payload") or {}
        action = str(event.get("action") or "").upper()
        ticker = str(event.get("ticker") or "")
        quantity = abs(float(event.get("quantity") or 0.0))
        fill_price = float(event.get("fill_price") or 0.0)
        fee = float(event.get("cost") or 0.0)
        before_shares = float(running_shares.get(ticker, 0.0))
        after_shares = before_shares + quantity if action == "BUY" else max(before_shares - quantity, 0.0)
        running_shares[ticker] = after_shares
        target_weight = target_weights.get(ticker)
        is_trim = action == "SELL" and float(target_weight or 0.0) > 0.0
        average_cost = float((prior_positions.get(ticker) or {}).get("average_cost") or 0.0)
        realized_pnl = None
        if action == "SELL" and average_cost > 0.0:
            realized_pnl = quantity * fill_price - fee - quantity * average_cost
        if action == "SELL" and is_trim:
            reason = f"Trimmed to {float(target_weight):.0%} target"
        elif action == "SELL":
            reason = "Exited — no longer selected"
        elif before_shares <= 1e-9:
            reason = f"New position — {float(target_weight or 0.0):.0%} target"
        else:
            reason = f"Topped up to {float(target_weight or 0.0):.0%} target"
        rows.append({
            "sequence": int(payload.get("sequence") or 0),
            "execution_date": payload.get("execution_date"),
            "action": action,
            "ticker": ticker,
            "shares": quantity,
            "before_shares": before_shares,
            "after_shares": after_shares,
            "fill_price": fill_price,
            "trade_value": quantity * fill_price,
            "fee": fee,
            "slippage_cost": float(payload.get("slippage_cost") or 0.0),
            "realized_pnl": realized_pnl,
            "is_trim": is_trim,
            "target_weight": target_weight,
            "reason": reason,
        })
    return sorted(rows, key=lambda row: row["sequence"])


def _next_rebalance_dates(signal_date: str | None) -> tuple[str | None, str | None]:
    if not signal_date:
        return None, None
    try:
        current = date.fromisoformat(str(signal_date))
    except ValueError:
        return None, None
    if current.month == 12:
        year, month = current.year + 1, 1
    else:
        year, month = current.year, current.month + 1
    next_signal = last_session_of_month(year, month)
    return next_signal.isoformat(), next_session(next_signal).isoformat()


def _selection_explanations(
    target_weights: dict[str, Any],
    v7_selected: list[str],
    v8_selected: list[str],
) -> list[dict[str, Any]]:
    """Explain frozen selections using only evidence saved with the signal."""
    v7 = set(v7_selected)
    v8 = set(v8_selected)
    rows: list[dict[str, Any]] = []
    for ticker, raw_weight in sorted(
        target_weights.items(), key=lambda item: (-float(item[1]), item[0])
    ):
        weight = float(raw_weight)
        if ticker in v7 and ticker in v8:
            support = "V7 + V8"
            reason = "Selected by both frozen momentum components; consensus receives the larger allocation."
        elif ticker in v7:
            support = "V7"
            reason = "Selected by the frozen 12–1 momentum component."
        elif ticker in v8:
            support = "V8"
            reason = "Selected by the frozen 3–1 / 6–1 / 12–1 composite momentum component."
        else:
            support = "Portfolio rule"
            reason = "Included by the saved Frozen V12 target portfolio."
        rows.append({
            "ticker": ticker,
            "target_weight": weight,
            "support": support,
            "reason": reason,
        })
    return rows


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
    latest_trades = _latest_rebalance(events, signal)
    latest_buy_value = sum(row["trade_value"] for row in latest_trades if row["action"] == "BUY")
    latest_sell_value = sum(row["trade_value"] for row in latest_trades if row["action"] == "SELL")
    latest_trade_fees = sum(row["fee"] for row in latest_trades)
    latest_trade_slippage = sum(row["slippage_cost"] for row in latest_trades)
    latest_execution_equity = None
    if latest_trades:
        latest_execution_date = latest_trades[0].get("execution_date")
        execution_snapshots = [
            row for row in _portfolio_events(events, "V12_T1", "PORTFOLIO_SNAPSHOT")
            if str((row.get("payload") or {}).get("execution_date") or "") == str(latest_execution_date or "")
        ]
        latest_execution_equity = _equity_value(execution_snapshots[-1]) if execution_snapshots else None
    latest_turnover = None
    if latest_execution_equity and latest_execution_equity > 0.0:
        latest_turnover = max(latest_buy_value, latest_sell_value) / latest_execution_equity
    next_signal_date, next_execution_date = _next_rebalance_dates(payload.get("signal_date"))
    holdings = []
    for ticker, values in sorted(positions.items()):
        shares = float(values.get("shares", 0.0))
        average_cost = float(values.get("average_cost", 0.0))
        mark_value = values.get("mark")
        mark = None if mark_value is None else float(mark_value)
        market_value = None if mark is None else shares * mark
        unrealized_pnl = (
            None if mark is None else shares * (mark - average_cost)
        )
        current_weight = (
            None
            if market_value is None or not portfolio_value
            else market_value / portfolio_value
        )
        holdings.append({
            "ticker": ticker,
            "shares": shares,
            "average_cost": average_cost,
            "mark": mark,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "current_weight": current_weight,
            "target_weight": target_weights.get(ticker),
        })
    cash = None
    if latest_snapshot:
        try:
            cash = float(latest_snapshot["payload"]["cash"])
        except (KeyError, TypeError, ValueError):
            cash = None
    latest_payload = (latest_snapshot or {}).get("payload") or {}
    try:
        realized_pnl = float(latest_payload["realized_pnl"])
    except (KeyError, TypeError, ValueError):
        realized_pnl = None
    try:
        unrealized_pnl = float(latest_payload["unrealized_pnl"])
    except (KeyError, TypeError, ValueError):
        unrealized_pnl = None
    try:
        cumulative_transaction_costs = float(latest_payload["transaction_costs"])
    except (KeyError, TypeError, ValueError):
        cumulative_transaction_costs = None
    latest_valuation_date = str(
        latest_payload.get("valuation_date")
        or latest_payload.get("execution_date")
        or ""
    ) or None

    statistical_warnings: list[str] = []
    if not events:
        statistical_warnings.append("The first official Forward Signal has not been generated")
    elif rolling_sharpe is None:
        statistical_warnings.append("Insufficient Forward history to calculate 12-month Rolling Sharpe")
    elif rolling_sharpe < 0.0:
        statistical_warnings.append("Rolling Sharpe is below 0; monitor without changing Frozen V12")
    if drawdown is not None and drawdown <= -0.20:
        statistical_warnings.append("Forward drawdown exceeded 20%; review without automatically disabling the strategy")

    blocked = bool(integrity_error or overdue)
    if blocked:
        health_status = "ERROR"
        health_label = "System Error"
    elif statistical_warnings:
        health_status = "WATCH"
        health_label = "Watch"
    else:
        health_status = "NORMAL"
        health_label = "Normal"

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
        "selection_explanations": _selection_explanations(
            target_weights, v7, v8
        ),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "cumulative_transaction_costs": cumulative_transaction_costs,
        "latest_valuation_date": latest_valuation_date,
        "latest_signal": signal,
        "signal_date": payload.get("signal_date"),
        "market_regime": payload.get("market_regime"),
        "v7_selected": v7,
        "v8_selected": v8,
        "agreement_count": agreement,
        "target_weights": target_weights,
        "latest_trades": latest_trades,
        "latest_buy_value": latest_buy_value,
        "latest_sell_value": latest_sell_value,
        "latest_trade_fees": latest_trade_fees,
        "latest_trade_slippage": latest_trade_slippage,
        "latest_transaction_costs": latest_trade_fees + latest_trade_slippage,
        "latest_turnover": latest_turnover,
        "latest_rebalance_equity": latest_execution_equity,
        "next_signal_date": next_signal_date,
        "next_execution_date": next_execution_date,
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
        "last_event_created_at": str(events[-1]["created_at"]) if events else None,
        "ledger_event_count": len(events),
        "ledger_verified": bool(events) and integrity_error is None,
    }
