"""Daily, read-only market valuation events for V12 paper portfolios.

This module does not create signals or orders.  It marks the existing immutable
positions at a completed session close and appends one reconciled valuation
event per active portfolio.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Callable

from src.forward_execution import portfolio_state_from_ledger
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id
from src.trading_calendar import session_close
from src.v12_live_signal import FROZEN_VERSION


ObservationFetcher = Callable[[list[str], str], dict[str, dict[str, float]]]


def _active_portfolios(ledger: AppendOnlyLedger) -> list[str]:
    return sorted({
        row["portfolio_id"]
        for row in ledger.events()
        if row["event_type"] == "INITIALIZE"
    })


def record_daily_valuations(
    ledger: AppendOnlyLedger,
    *,
    valuation_date: str,
    observation_fetcher: ObservationFetcher,
    recorded_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Append one idempotent close valuation for every active paper account.

    Corporate actions deliberately fail closed.  They must be recorded as
    explicit DIVIDEND/SPLIT ledger events before the daily valuation continues.
    """
    ledger.verify_integrity()
    now = recorded_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("recorded_at must be timezone-aware")
    close_at = session_close(valuation_date)
    if now.astimezone(timezone.utc) < close_at.astimezone(timezone.utc):
        raise ValueError("daily close valuation cannot run before the session closes")

    states = {
        portfolio_id: portfolio_state_from_ledger(ledger, portfolio_id)
        for portfolio_id in _active_portfolios(ledger)
    }
    tickers = sorted({ticker for state in states.values() for ticker in state.positions})
    if not tickers:
        return []
    observations = observation_fetcher(tickers, valuation_date)
    missing = sorted(set(tickers) - set(observations))
    if missing:
        raise RuntimeError(f"missing close observations for: {', '.join(missing)}")

    marks: dict[str, float] = {}
    for ticker in tickers:
        item = observations[ticker]
        close = float(item.get("close", 0.0))
        dividend = float(item.get("dividend", 0.0))
        split = float(item.get("split", 0.0))
        if not math.isfinite(close) or close <= 0:
            raise RuntimeError(f"invalid raw close for {ticker} on {valuation_date}")
        if dividend != 0.0 or split != 0.0:
            raise RuntimeError(
                f"corporate action requires reviewed ledger event for {ticker} "
                f"on {valuation_date}"
            )
        marks[ticker] = close

    existing = ledger.events()
    latest_valuation_dates = [
        str((row.get("payload") or {}).get("valuation_date") or "")
        for row in existing
        if row["event_type"] == "VALUATION_SNAPSHOT"
    ]
    if latest_valuation_dates and valuation_date < max(latest_valuation_dates):
        raise RuntimeError("backfilled daily valuation is prohibited")

    recorded_text = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    events: list[LedgerEvent] = []
    summaries: list[dict[str, Any]] = []
    for portfolio_id, state in states.items():
        if not state.positions:
            continue
        portfolio_marks = {ticker: marks[ticker] for ticker in state.positions}
        equity = state.equity(portfolio_marks)
        market_value = equity - state.cash
        payload = {
            "valuation_date": valuation_date,
            "cash": state.cash,
            "market_value": market_value,
            "portfolio_equity": equity,
            "realized_pnl": state.realized_pnl,
            "unrealized_pnl": state.unrealized_pnl(portfolio_marks),
            "dividends": state.dividends,
            "transaction_costs": state.transaction_costs,
            "positions": {
                ticker: {
                    "shares": position.shares,
                    "average_cost": position.average_cost,
                    "mark": portfolio_marks[ticker],
                }
                for ticker, position in sorted(state.positions.items())
            },
            "reconciliation": "portfolio_equity = cash + market_value",
        }
        events.append(LedgerEvent(
            event_id=deterministic_event_id(
                FROZEN_VERSION, valuation_date, portfolio_id, "CLOSE_VALUATION"
            ),
            portfolio_id=portfolio_id,
            event_type="VALUATION_SNAPSHOT",
            strategy_version=FROZEN_VERSION,
            signal_timestamp=close_at.isoformat(),
            execution_rule="T+1_OPEN" if portfolio_id.endswith("T1") else "T+2_OPEN",
            data_asof=f"{valuation_date}T{close_at.strftime('%H:%M:%S')} America/New_York",
            reason="Daily close mark-to-market; no signal or order mutation",
            payload=payload,
            created_at=recorded_text,
        ))
        summaries.append({
            "portfolio_id": portfolio_id,
            "valuation_date": valuation_date,
            "portfolio_equity": equity,
        })

    result = ledger.append_batch(events)
    if result["created"] == 0:
        return []
    if result["created"] != len(events):
        raise RuntimeError("partial daily valuation batch detected")
    ledger.verify_integrity()
    return summaries
