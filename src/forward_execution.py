"""Forward fill processing for the separated V12 T+1 and T+2 paper accounts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.paper_accounting import (
    PaperOrder,
    PortfolioState,
    apply_dividend,
    apply_fills,
    apply_split,
    apply_ticker_change,
    build_order_plan,
)
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id
from src.trading_calendar import next_session, session_close, session_open
from src.v12_live_signal import FROZEN_VERSION


def portfolio_state_from_ledger(ledger: AppendOnlyLedger, portfolio_id: str) -> PortfolioState:
    ledger.verify_integrity()
    rows = ledger.events(portfolio_id)
    initial = [row for row in rows if row["event_type"] == "INITIALIZE"]
    if len(initial) != 1:
        raise RuntimeError(f"unknown portfolio state for {portfolio_id}: expected one initialization")
    state = PortfolioState(float(initial[0]["payload"]["initial_capital"]))
    for row in rows:
        if row["event_type"] == "FILL":
            order = PaperOrder(
                sequence=int(row["payload"].get("sequence", 0)),
                ticker=row["ticker"],
                side=row["action"],
                shares=float(row["quantity"]),
                expected_price=float(row["expected_price"]),
                estimated_fill_price=float(row["fill_price"]),
                estimated_notional=float(row["quantity"]) * float(row["fill_price"]),
                estimated_commission=float(row["cost"] or 0.0),
                estimated_slippage_cost=float(row["payload"].get("slippage_cost", 0.0)),
                reason=row["reason"],
            )
            state = apply_fills(state, (order,))
        elif row["event_type"] == "DIVIDEND":
            state = apply_dividend(state, row["ticker"], float(row["payload"]["amount_per_share"]))
        elif row["event_type"] == "SPLIT":
            state = apply_split(state, row["ticker"], float(row["payload"]["ratio"]))
        elif row["event_type"] == "TICKER_CHANGE":
            state = apply_ticker_change(state, row["ticker"], str(row["payload"]["new_ticker"]))
    return state


def execute_target_weights(
    ledger: AppendOnlyLedger,
    *,
    portfolio_id: str,
    signal_date: str,
    execution_rule: str,
    target_weights: dict[str, float],
    raw_open_prices: dict[str, float],
    execution_date: str,
    recorded_at: datetime | None = None,
    fractional_shares: bool = True,
    _fail_after_inserts: int | None = None,
) -> dict[str, Any]:
    """Simulate a scheduled open and append all fills plus one snapshot atomically."""
    if execution_rule not in {"T+1_OPEN", "T+2_OPEN"}:
        raise ValueError("execution rule must be T+1_OPEN or T+2_OPEN")
    delay = 1 if execution_rule == "T+1_OPEN" else 2
    expected_date = next_session(signal_date, delay).isoformat()
    if execution_date != expected_date:
        raise ValueError(f"wrong execution session: expected {expected_date}")
    now = recorded_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("recorded_at must be timezone-aware")
    if now.astimezone(timezone.utc) < session_open(execution_date).astimezone(timezone.utc):
        raise ValueError("fill cannot be recorded before the scheduled market open")

    state = portfolio_state_from_ledger(ledger, portfolio_id)
    plan = build_order_plan(
        state,
        raw_open_prices,
        target_weights,
        fractional_shares=fractional_shares,
    )
    final = apply_fills(state, plan.orders)
    marks = {ticker: float(raw_open_prices[ticker]) for ticker in final.positions}
    equity = final.equity(marks)
    recorded_text = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    signal_timestamp = session_open(execution_date).isoformat()
    events: list[LedgerEvent] = []
    for order in plan.orders:
        events.append(
            LedgerEvent(
                event_id=deterministic_event_id(
                    FROZEN_VERSION, signal_date, execution_rule, portfolio_id,
                    order.ticker, order.side, "FILL",
                ),
                portfolio_id=portfolio_id,
                event_type="FILL",
                strategy_version=FROZEN_VERSION,
                signal_timestamp=signal_timestamp,
                execution_rule=execution_rule,
                data_asof=f"{execution_date}T09:30:00 America/New_York",
                ticker=order.ticker,
                action=order.side,
                expected_price=order.expected_price,
                fill_price=order.estimated_fill_price,
                quantity=order.shares,
                cost=order.estimated_commission,
                reason=order.reason,
                payload={
                    "sequence": order.sequence,
                    "slippage_cost": order.estimated_slippage_cost,
                    "signal_date": signal_date,
                    "execution_date": execution_date,
                },
                created_at=recorded_text,
            )
        )
    events.append(
        LedgerEvent(
            event_id=deterministic_event_id(
                FROZEN_VERSION, signal_date, execution_rule, portfolio_id, "SNAPSHOT"
            ),
            portfolio_id=portfolio_id,
            event_type="PORTFOLIO_SNAPSHOT",
            strategy_version=FROZEN_VERSION,
            signal_timestamp=signal_timestamp,
            execution_rule=execution_rule,
            data_asof=f"{execution_date}T09:30:00 America/New_York",
            reason="Post-fill accounting reconciliation",
            payload={
                "execution_date": execution_date,
                "cash": final.cash,
                "market_value": equity - final.cash,
                "portfolio_equity": equity,
                "realized_pnl": final.realized_pnl,
                "unrealized_pnl": final.unrealized_pnl(marks),
                "dividends": final.dividends,
                "transaction_costs": final.transaction_costs,
                "positions": {
                    ticker: {"shares": position.shares, "average_cost": position.average_cost}
                    for ticker, position in sorted(final.positions.items())
                },
                "reconciliation": "portfolio_equity = cash + market_value",
            },
            created_at=recorded_text,
        )
    )
    ledger_result = ledger.append_batch(events, _fail_after_inserts=_fail_after_inserts)
    return {
        "status": "EXECUTED" if ledger_result["created"] else "ALREADY_PROCESSED",
        "portfolio_id": portfolio_id,
        "execution_date": execution_date,
        "orders": [order.to_dict() for order in plan.orders],
        "snapshot": events[-1].payload,
        "ledger_result": ledger_result,
    }


def due_portfolio_targets(ledger: AppendOnlyLedger, execution_date: str) -> list[dict[str, Any]]:
    """Return unprocessed portfolio targets scheduled for this NYSE session."""
    rows = ledger.events()
    completed = {
        (row["portfolio_id"], row["payload"].get("execution_date"))
        for row in rows
        if row["event_type"] == "PORTFOLIO_SNAPSHOT"
    }
    due = []
    for row in rows:
        if row["event_type"] != "SIGNAL":
            continue
        signal_date = str(row["payload"].get("signal_date"))
        delay = 1 if row["execution_rule"] == "T+1_OPEN" else 2
        scheduled = next_session(signal_date, delay).isoformat()
        if scheduled != execution_date or (row["portfolio_id"], scheduled) in completed:
            continue
        due.append(
            {
                "portfolio_id": row["portfolio_id"],
                "signal_date": signal_date,
                "execution_rule": row["execution_rule"],
                "target_weights": dict(row["payload"]["portfolio_target_weights"]),
            }
        )
    return due


def execute_due_portfolios(
    ledger: AppendOnlyLedger,
    *,
    execution_date: str,
    price_fetcher,
    recorded_at: datetime | None = None,
    fractional_shares: bool = True,
) -> list[dict[str, Any]]:
    """Process every due V12/SPY/QQQ account after the session close; retries are safe."""
    now = recorded_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("recorded_at must be timezone-aware")
    if now.astimezone(timezone.utc) < session_close(execution_date).astimezone(timezone.utc):
        raise ValueError("daily open data is not finalized until the execution session closes")
    due = due_portfolio_targets(ledger, execution_date)
    results = []
    for item in due:
        state = portfolio_state_from_ledger(ledger, item["portfolio_id"])
        required = set(state.positions) | set(item["target_weights"])
        prices = price_fetcher(sorted(required), execution_date) if required else {}
        results.append(
            execute_target_weights(
                ledger,
                portfolio_id=item["portfolio_id"],
                signal_date=item["signal_date"],
                execution_rule=item["execution_rule"],
                target_weights=item["target_weights"],
                raw_open_prices=prices,
                execution_date=execution_date,
                recorded_at=now,
                fractional_shares=fractional_shares,
            )
        )
    return results
