"""Daily, read-only market valuation events for V12 paper portfolios.

This module does not create signals or orders.  It marks the existing immutable
positions at a completed session close and appends one reconciled valuation
event per active portfolio.
"""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict, replace
import math
from typing import Any, Callable

from src.forward_execution import portfolio_state_from_ledger
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id
from src.trading_calendar import session_close
from src.v12_live_signal import FROZEN_VERSION
from src.forward_dividends import load_reviews, prepare_dividends, receivable


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
    reviewed_dividends: dict | None = None,
) -> list[dict[str, Any]]:
    """Append one idempotent close valuation for every active paper account.

    Reviewed cash dividends and valuations commit atomically. Unreviewed
    dividends and all unsupported splits still fail closed.
    """
    ledger.verify_integrity()
    now = recorded_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("recorded_at must be timezone-aware")
    close_at = session_close(valuation_date)
    if now.astimezone(timezone.utc) < close_at.astimezone(timezone.utc):
        raise ValueError("daily close valuation cannot run before the session closes")

    existing = ledger.events()
    reviews = load_reviews(now) if reviewed_dividends is None else reviewed_dividends

    states = {
        portfolio_id: portfolio_state_from_ledger(ledger, portfolio_id)
        for portfolio_id in _active_portfolios(ledger)
    }
    tickers = sorted({ticker for state in states.values() for ticker in state.positions})
    # Include reviewed ex-date securities even if sold at today's open.
    tickers = sorted(set(tickers) | {r['ticker'] for r in reviews.values() if r['ex_date'] == valuation_date})
    if not tickers and not any(r['event_type'] == 'DIVIDEND_ENTITLEMENT' for r in existing):
        return []
    observations = observation_fetcher(tickers, valuation_date) if tickers else {}
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
        if not math.isfinite(dividend) or not math.isfinite(split):
            raise RuntimeError('invalid corporate action observation')
        marks[ticker] = close

    action_events = prepare_dividends(existing, valuation_date, observations, reviews, now)
    projected_rows = existing + [asdict(event) for event in action_events]
    latest_valuation_dates = [
        str((row.get("payload") or {}).get("valuation_date") or "")
        for row in existing
        if row["event_type"] == "VALUATION_SNAPSHOT"
    ]
    if latest_valuation_dates and valuation_date < max(latest_valuation_dates):
        raise RuntimeError("backfilled daily valuation is prohibited")

    recorded_text = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    events: list[LedgerEvent] = list(action_events)
    summaries: list[dict[str, Any]] = []
    for portfolio_id, state in states.items():
        if not state.positions and not any(r['event_type'] == 'DIVIDEND_ENTITLEMENT' and r['portfolio_id'] == portfolio_id for r in projected_rows):
            continue
        payment = sum(float(e.payload['amount']) for e in action_events
                      if e.portfolio_id == portfolio_id and e.event_type == 'DIVIDEND_PAYMENT')
        state = replace(state, cash=state.cash + payment, dividends=state.dividends + payment)
        dividends_receivable = receivable(projected_rows, portfolio_id)
        portfolio_marks = {ticker: marks[ticker] for ticker in state.positions}
        equity = state.equity(portfolio_marks) + dividends_receivable
        market_value = equity - state.cash - dividends_receivable
        payload = {
            "valuation_date": valuation_date,
            "cash": state.cash,
            "market_value": market_value,
            "portfolio_equity": equity,
            "realized_pnl": state.realized_pnl,
            "unrealized_pnl": state.unrealized_pnl(portfolio_marks),
            "dividends": state.dividends,
            "dividends_receivable": dividends_receivable,
            "transaction_costs": state.transaction_costs,
            "positions": {
                ticker: {
                    "shares": position.shares,
                    "average_cost": position.average_cost,
                    "mark": portfolio_marks[ticker],
                }
                for ticker, position in sorted(state.positions.items())
            },
            "reconciliation": "portfolio_equity = cash + market_value + dividends_receivable",
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

    known = {r['event_id'] for r in existing}
    overlaps = [e.event_id in known for e in events]
    if any(overlaps) and not all(overlaps):
        raise RuntimeError('Partial pre-existing dividend/valuation batch; manual review required')
    result = ledger.append_batch(events)
    if result["created"] == 0:
        return []
    if result["created"] != len(events):
        raise RuntimeError("partial daily valuation batch detected")
    ledger.verify_integrity()
    return summaries
