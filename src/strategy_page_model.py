"""Normalize signed V12 and E3 displays for matching website components."""
from copy import deepcopy
import pandas as pd

from src.dashboard_ui import activity_event_rows, freshness_status, latest_curve_date, selection_rows
from src.e3_dashboard import freshness


def v12_model(state):
    model = deepcopy(state)
    model.update(name="V12", benchmark="QQQ", benchmarks=("V12", "SPY", "QQQ"),
                 available=not bool(state.get("integrity_error")),
                 publication=state.get("snapshot_generated_at") or state.get("last_event_created_at"),
                 valuation_date=latest_curve_date(state), positions=state.get("holdings") or [],
                 selections=selection_rows(state), event_rows=activity_event_rows(state),
                 trades=state.get("latest_trades") or [], trade_scope="Latest published V12 rebalance",
                 history=[], warnings=list(state.get("warnings") or []),
                 signal_summary=" · ".join(f"{s} {w:.0%}" for s, w in (state.get("target_weights") or {}).items()) or "No saved allocation",
                 next_plan=[], details_available=True)
    freshness_code, message = freshness_status(state)
    model["freshness_message"] = message
    model["delayed"] = freshness_code != "CURRENT"
    return model


def e3_model(view):
    base = {"name": "E3", "benchmark": "EW", "benchmarks": ("E3", "SPY", "EW", "CSM"),
            "available": view is not None, "positions": [], "selections": [], "event_rows": [],
            "trades": [], "latest_trades": [], "history": [], "curve": pd.DataFrame(),
            "warnings": [], "next_plan": [], "details_available": False,
            "formal_forward_rows": 0, "publication": None, "valuation_date": None,
            "signal_date": None, "execution_date": None, "execution_status": "Unavailable",
            "portfolio_value": None, "cash": None, "cumulative_return": None,
            "excess_vs_spy": None, "excess_vs_qqq": None, "max_drawdown": None,
            "realized_pnl": None, "unrealized_pnl": None, "cumulative_transaction_costs": None,
            "dividends_receivable": None, "dividends_received": None,
            "rolling_sharpe": None, "ledger_verified": False, "ledger_event_count": None,
            "signal_summary": "No recorded signal", "delayed": False, "freshness_message": "Unavailable"}
    if view is None:
        return base
    account = view["accounts"]["E3"]
    details = view.get("details") or {}
    pending = view.get("pending") or {}
    plan = pending.get("plans", {}).get("E3", {})
    history = details.get("signal_history", [])
    entries, exits = plan.get("entries", []), plan.get("exits", [])
    value = account["return_pct"]
    spy = view["accounts"]["SPY"]["return_pct"]
    ew = view["accounts"]["EW"]["return_pct"]
    trades = details.get("transactions", [])
    latest_day = max((t["execution_date"] for t in trades), default=None)
    latest_trades = [t for t in trades if t["execution_date"] == latest_day]
    base.update(portfolio_value=account["equity"], cash=account["cash"],
                cumulative_return=value / 100 if value is not None else None,
                excess_vs_spy=(value - spy) / 100 if value is not None and spy is not None else None,
                excess_vs_qqq=(value - ew) / 100 if value is not None and ew is not None else None,
                curve=pd.DataFrame(view["curve"]), formal_forward_rows=view["forward_sessions"],
                publication=view["published_at"], valuation_date=view["last_close"],
                positions=details.get("holdings", [{"ticker": s, **p} for s, p in account["positions"].items()]), trades=trades, latest_trades=latest_trades,
                trade_scope="All recorded E3 paper fills", history=history,
                details_available=details.get("version") == 1,
                signal_date=pending.get("signal_date"), execution_date=pending.get("execution_date"),
                execution_status="Planned" if entries or exits else ("No trades planned" if pending else "Waiting for first close"),
                signal_summary=("Buy " + ", ".join(entries) if entries else "No new entries") + (" · Sell " + ", ".join(exits) if exits else ""),
                next_plan=[{"Action": side, "Ticker": s, "Execution": pending.get("execution_date"),
                            "Decision saved": pending.get("recorded_at")}
                           for side, symbols in (("BUY", entries), ("SELL", exits)) for s in symbols],
                next_signal_date=view["first_signal_session"] if not view["last_close"] else None,
                next_execution_date=view["first_possible_fill_session"] if not view["last_close"] else pending.get("execution_date"),
                ledger_verified=view["ledger_integrity"], ledger_event_count=view["ledger_events"],
                source_commit=view.get("source_commit"), freeze_sha256=view["freeze_sha256"],
                rules=view["rules"], status=view["status"],
                dividends_receivable=account["dividend_receivable"], dividends_received=details.get("dividends_received"),
                max_drawdown=details.get("max_drawdown"), rolling_sharpe=details.get("rolling_sharpe"),
                realized_pnl=details.get("realized_pnl"), unrealized_pnl=details.get("unrealized_pnl"),
                cumulative_transaction_costs=details.get("transaction_costs"), exposure=details.get("exposure"),
                closed_trades=details.get("closed_trades"), win_rate=details.get("win_rate"),
                event_rows=activity_event_rows({"events": details.get("events", [])}))
    base["selections"] = [{"ticker": p["ticker"], "target_weight": p["current_weight"],
                           "support": f"Entry signal {p['signal_date']} · held {p['held_sessions']}/10 sessions",
                           "reason": p["reason"]} for p in base["positions"] if "current_weight" in p]
    warning = freshness(view)
    base["delayed"] = warning is not None
    base["freshness_message"] = warning or "Current for the recorded-session publication schedule."
    return base
