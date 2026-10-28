"""Prospectively planned, isolated F1/E3 paper experiment; no broker interfaces."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from src.candidate_strategies import bollinger_mean_reversion_variant
from src.cross_sectional import latest_cross_sectional_ranking
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id
from src.trading_calendar import NEW_YORK, holiday_dates, is_session, next_session, previous_session, session_close, session_open

UNIVERSE = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT")
SYMBOLS = (*UNIVERSE, "SPY")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOME = ROOT / "paper_ledger" / "e3_forward"
CONTROL = "E3_FORWARD_CONTROL"
VERSION = "F1-E3-PAPER-V1"
COMMISSION = 0.001
SLIPPAGE = 0.0005
FROZEN_FILES = ("src/e3_forward.py", "src/candidate_strategies.py", "src/cross_sectional.py",
                "src/indicators.py", "src/trading_calendar.py", "src/paper_ledger.py", "scripts/run_e3_forward.py")
RULES = {
    "primary": "F1 + E3", "universe": list(UNIVERSE), "initial_capital_per_account": 10000,
    "entry": "close < lower BB(20,2 population SD) AND close > MA200",
    "spy_filter": False, "ma20_exit": False, "stop_loss": False,
    "holding_sessions": 10, "fill_rule": "T_CLOSE_SIGNAL_T_PLUS_1_OPEN",
    "max_e3_positions": 2, "entry_cap_fraction": 0.5,
    "ranking": "(lower_band - close) / lower_band descending; ticker ascending on ties",
    "commission": COMMISSION, "adverse_slippage": SLIPPAGE, "cash_interest": 0,
    "accounts": ["E3", "CSM", "SPY", "EW"],
    "csm_schedule": "first forward close, then each 20th observed close; top two eligible MA200-filtered stocks",
    "accounting": "raw-price fractional shares; dividends accrued as nonspendable receivables; splits applied from captured actions",
    "evidence": "after-close recorded model fills require a prior-close decision saved before that session's open",
    "missed_session_policy": "halt; do not invent signals or backfill trades",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(value):
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required")
    return result.to_pydatetime().astimezone(timezone.utc)


def code_hashes():
    # Git may change Windows line endings without changing the implementation.
    return {name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name in FROZEN_FILES}


def dependency_versions():
    try:
        quote_library = importlib.metadata.version("yfinance")
    except importlib.metadata.PackageNotFoundError:
        quote_library = "not installed"
    return {"python": sys.version.split()[0], "pandas": pd.__version__, "numpy": np.__version__, "yfinance": quote_library}


@lru_cache(maxsize=512)
def session_window(day, count=200):
    if not is_session(day) or count < 1:
        raise ValueError("A session date and positive history count are required")
    end = pd.Timestamp(day)
    start = end - pd.Timedelta(days=count * 3)
    holidays = holiday_dates(start.date(), end.date())
    sessions = [stamp.date().isoformat() for stamp in pd.bdate_range(start, end) if stamp.date() not in holidays]
    if len(sessions) < count:
        raise ValueError("Insufficient calendar history")
    return tuple(reversed(sessions[-count:]))


def first_new_session(frozen_at):
    now = stamp(frozen_at)
    day = now.astimezone(NEW_YORK).date()
    # Entire first counted session must start after the actual freeze timestamp.
    if not is_session(day) or session_open(day) <= now:
        day = next_session(day)
    return day.isoformat()


def initialize(home=DEFAULT_HOME, now=None):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    path = home / "freeze.json"
    if path.exists():
        freeze = read_freeze(home)
        now = stamp(freeze["frozen_at"])
    else:
        now = stamp(now or datetime.now(timezone.utc))
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
        freeze = {"version": VERSION, "frozen_at": now.isoformat(), "first_signal_session": first_new_session(now),
                  "source_base_commit": revision, "rules": RULES, "code_sha256": code_hashes(), "dependencies": dependency_versions()}
        freeze["content_sha256"] = digest(freeze)
        with path.open("x", encoding="utf-8") as out:
            out.write(json.dumps(freeze, indent=2))
    ledger = AppendOnlyLedger(home / "events.sqlite3")
    state = {"last_close": None, "processed_closes": 0, "pending": None,
             "accounts": {name: {"cash": 10000.0, "positions": {}, "dividend_receivable": 0.0} for name in RULES["accounts"]}}
    ledger.append_batch([event(freeze, "INITIALIZE", "initial", now, {"freeze": freeze, "state": state})])
    return freeze


def read_freeze(home=DEFAULT_HOME):
    freeze = json.loads((Path(home) / "freeze.json").read_text(encoding="utf-8"))
    content = {k: v for k, v in freeze.items() if k != "content_sha256"}
    if digest(content) != freeze["content_sha256"]:
        raise RuntimeError("Freeze manifest was modified")
    if freeze["rules"] != RULES or freeze["code_sha256"] != code_hashes():
        raise RuntimeError("Frozen rules or implementation changed; a new experiment needs an explicit new version")
    if freeze["dependencies"] != dependency_versions():
        raise RuntimeError("Frozen runtime dependencies changed")
    return freeze


def event(freeze, kind, key, now, payload, account=CONTROL, signal_at=None, **fields):
    return LedgerEvent(event_id=deterministic_event_id(VERSION, freeze["content_sha256"], kind, account, key),
                       portfolio_id=account, event_type=kind, strategy_version=VERSION,
                       signal_timestamp=stamp(signal_at or now).isoformat(), execution_rule="T+1_OPEN_PAPER_ONLY",
                       data_asof=payload.get("session", ""), payload=payload,
                       created_at=stamp(now).isoformat(), **fields)


def read_state(home, freeze=None):
    freeze = freeze or read_freeze(home)
    ledger = AppendOnlyLedger(Path(home) / "events.sqlite3")
    ledger.verify_integrity()
    records = ledger.events(CONTROL)
    initial = [r for r in records if r["event_type"] == "INITIALIZE"]
    if len(initial) != 1 or initial[0]["payload"]["freeze"] != freeze:
        raise RuntimeError("Initialization is missing or does not match the immutable freeze")
    for record in records:
        if record["event_type"] not in ("BASELINE_CAPTURED", "CLOSE_PROCESSED"):
            continue
        payload = record["payload"]
        checksum = payload["snapshot_sha256"]
        folder = Path(home) / "warmup" if record["event_type"] == "BASELINE_CAPTURED" else Path(home) / "inputs" / payload["session"]
        path = folder / f"{checksum}.json"
        if not path.exists() or digest(json.loads(path.read_text(encoding="utf-8"))) != checksum:
            raise RuntimeError("Stored source snapshot is missing or its hash changed")
    latest = [r for r in records if r["event_type"] in ("INITIALIZE", "CLOSE_PROCESSED")][-1]
    return ledger, deepcopy(latest["payload"]["state"])


def validate_snapshot(snapshot, day, observed_at):
    observed_at = stamp(observed_at)
    if stamp(snapshot["observed_at"]) > observed_at:
        raise ValueError("Snapshot claims a future availability timestamp")
    if stamp(snapshot["observed_at"]) < session_close(day) + timedelta(minutes=20):
        raise ValueError("Snapshot was captured before the completed-bar safety delay")
    if observed_at - stamp(snapshot["observed_at"]) > timedelta(minutes=10):
        raise ValueError("Snapshot capture is stale")
    if observed_at >= session_open(next_session(day)):
        raise ValueError("New signal cannot be created after its next-open deadline")
    if set(snapshot["prices"]) != set(SYMBOLS):
        raise ValueError("All ten stocks and SPY are required")
    frames, raw_today = {}, {}
    expected = session_window(day)
    for symbol in SYMBOLS:
        frame = pd.DataFrame(snapshot["prices"][symbol])
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        if frame["date"].duplicated().any() or (frame["date"] > day).any():
            raise ValueError("Duplicate or future bars in snapshot")
        frame = frame.sort_values("date").reset_index(drop=True)
        if frame.empty or frame["date"].iloc[-1] != day or not set(expected).issubset(frame["date"]):
            raise ValueError(f"Missing current or warmup sessions: {symbol}")
        for column in ("open", "high", "low", "close", "adj_close"):
            values = pd.to_numeric(frame[column], errors="raise")
            if not values.map(math.isfinite).all() or (values <= 0).any():
                raise ValueError(f"Invalid {column}: {symbol}")
        if (frame["low"] > frame[["open", "close"]].min(axis=1) + 1e-6).any() or (frame["high"] < frame[["open", "close"]].max(axis=1) - 1e-6).any():
            raise ValueError(f"Inconsistent raw OHLC: {symbol}")
        row = frame.iloc[-1].to_dict()
        if not math.isfinite(float(row["volume"])) or float(row["volume"]) <= 0:
            raise ValueError(f"Missing current-session traded volume: {symbol}")
        for key in ("dividend", "split"):
            if not math.isfinite(float(row[key])) or float(row[key]) < 0:
                raise ValueError(f"Invalid corporate action: {symbol}")
        raw_today[symbol] = row
        # Indicator data is adjusted as observed NOW, capped at the decision date.
        factor = frame["adj_close"] / frame["close"]
        for column in ("open", "high", "low", "close"):
            frame[column] = frame[column] * factor
        frames[symbol] = frame
    return frames, raw_today


def _fill(account, name, symbol, action, qty, raw_open, signal_date, day, fills):
    if qty <= 1e-10:
        return
    price = raw_open * (1 + SLIPPAGE if action == "BUY" else 1 - SLIPPAGE)
    notional = qty * price
    fee = notional * COMMISSION
    if action == "BUY":
        if notional + fee > account["cash"] + 1e-6:
            raise RuntimeError("Buy exceeds available cash")
        account["cash"] -= notional + fee
        position = account["positions"].setdefault(symbol, {"shares": 0.0, "entry_session": day, "held_sessions": 0})
        position["shares"] += qty
    else:
        position = account["positions"][symbol]
        if qty > position["shares"] + 1e-7:
            raise RuntimeError("Unfunded sell")
        position["shares"] -= qty
        account["cash"] += notional - fee
        if position["shares"] < 1e-8:
            del account["positions"][symbol]
    fills.append({"account": name, "symbol": symbol, "action": action, "shares": qty, "raw_open": raw_open,
                  "execution_price": price, "notional": notional, "commission": fee,
                  "signal_date": signal_date, "execution_date": day})


def process_open(state, day, raw, freeze):
    fills, actions = [], []
    pending = state["pending"]
    if pending is None:
        return fills, actions
    if pending["execution_date"] != day or pending["signal_date"] != previous_session(day).isoformat():
        raise RuntimeError("Pending decision does not match this next session")
    if stamp(pending["recorded_at"]) >= session_open(day) or stamp(pending["recorded_at"]) <= stamp(freeze["frozen_at"]):
        raise RuntimeError("A decision must be frozen prospectively before the execution open")
    for name, account in state["accounts"].items():
        for symbol, pos in account["positions"].items():
            dividend, split = float(raw[symbol]["dividend"]), float(raw[symbol]["split"])
            if dividend and split:
                raise RuntimeError("Simultaneous dividend/split requires an accounting review")
            if split and split != 1:
                pos["shares"] *= split
                actions.append({"account": name, "symbol": symbol, "action": "SPLIT", "ratio": split, "session": day})
            if dividend:
                amount = dividend * pos["shares"]
                account["dividend_receivable"] += amount
                actions.append({"account": name, "symbol": symbol, "action": "DIVIDEND_RECEIVABLE", "amount": amount,
                                "amount_per_share": dividend, "session": day, "cash_credited": False})
        plan = pending["plans"].get(name)
        if plan is None:
            continue
        def open_value():
            return account["cash"] + sum(p["shares"] * float(raw[s]["open"]) for s, p in account["positions"].items())
        def fill(symbol, side, qty):
            _fill(account, name, symbol, side, qty, float(raw[symbol]["open"]), pending["signal_date"], day, fills)
        if name == "E3":
            for symbol in plan["exits"]:
                fill(symbol, "SELL", account["positions"][symbol]["shares"])
            cap = open_value() / 2
            for symbol in plan["entries"]:
                if symbol in account["positions"] or len(account["positions"]) >= 2:
                    raise RuntimeError("E3 position limits violated")
                budget = min(cap, account["cash"] / (1 + COMMISSION))
                fill(symbol, "BUY", budget / (float(raw[symbol]["open"]) * (1 + SLIPPAGE)))
        elif name == "CSM":
            targets = plan["targets"]
            value_per_name = open_value() / len(targets) if targets else 0.0
            for symbol, pos in list(account["positions"].items()):
                desired_qty = value_per_name / float(raw[symbol]["open"]) if symbol in targets else 0.0
                fill(symbol, "SELL", max(pos["shares"] - desired_qty, 0.0))
            for symbol in targets:
                price = float(raw[symbol]["open"]) * (1 + SLIPPAGE)
                current_value = account["positions"].get(symbol, {}).get("shares", 0.0) * float(raw[symbol]["open"])
                qty = min(max(value_per_name - current_value, 0.0) / price, account["cash"] / (price * (1 + COMMISSION)))
                fill(symbol, "BUY", qty)
        else:
            targets = plan["targets"]
            budget = account["cash"] / (len(targets) * (1 + COMMISSION))
            for symbol in targets:
                fill(symbol, "BUY", budget / (float(raw[symbol]["open"]) * (1 + SLIPPAGE)))
        if account["cash"] < -1e-6:
            raise RuntimeError("Negative paper cash")
    for fill in fills:
        fill["decision_recorded_at"] = pending["recorded_at"]
    return fills, actions


def make_plans(state, day, frames, raw, now):
    eligible = []
    details = []
    for symbol in UNIVERSE:
        row = bollinger_mean_reversion_variant(frames[symbol], frames["SPY"], False, True, False).iloc[-1]
        detail = {"symbol": symbol, "adjusted_close": float(row["close"]), "lower_band": float(row["lower"]),
                  "ma200": float(row["stock_ma200"]), "entry_signal": bool(row["entry_signal"]), "score": float(row["score"])}
        details.append(detail)
        if detail["entry_signal"]:
            eligible.append(detail)
    eligible.sort(key=lambda item: (-item["score"], item["symbol"]))
    account = state["accounts"]["E3"]
    exits = sorted(s for s, pos in account["positions"].items() if pos["held_sessions"] >= 10)
    slots = 2 - (len(account["positions"]) - len(exits))
    entries = [d["symbol"] for d in eligible if d["symbol"] not in account["positions"] or d["symbol"] in exits][:slots]
    plans = {"E3": {"exits": exits, "entries": entries}}
    if state["processed_closes"] % 20 == 0:
        ranking = latest_cross_sectional_ranking({s: frames[s] for s in UNIVERSE}, frames["SPY"])
        plans["CSM"] = {"targets": ranking.loc[ranking["selected"], "symbol"].tolist()}
    if state["processed_closes"] == 0:
        plans["SPY"], plans["EW"] = {"targets": ["SPY"]}, {"targets": list(UNIVERSE)}
    return {"signal_date": day, "recorded_at": stamp(now).isoformat(), "execution_date": next_session(day).isoformat(),
            "plans": plans}, details


def close_cycle(home, snapshot, now=None):
    now = stamp(now or datetime.now(timezone.utc))
    freeze = read_freeze(home)
    day = snapshot["session"]
    ledger, state = read_state(home, freeze)
    if day == state["last_close"]:
        return status(home)
    expected = next_session(state["last_close"]).isoformat() if state["last_close"] else freeze["first_signal_session"]
    if day != expected:
        raise RuntimeError(f"Forward session gap or out-of-order input: expected {expected}, got {day}; no backfill permitted")
    if day < freeze["first_signal_session"] or session_open(day) <= stamp(freeze["frozen_at"]):
        raise ValueError("Pre-freeze sessions cannot count as forward evidence")
    if now < session_close(day) + timedelta(minutes=20):
        raise ValueError("Close processing is too early")
    frames, raw = validate_snapshot(snapshot, day, now)
    fills, actions = process_open(state, day, raw, freeze)
    valuations = {}
    for name, account in state["accounts"].items():
        for pos in account["positions"].values():
            pos["held_sessions"] += 1
        marked = sum(pos["shares"] * float(raw[s]["close"]) for s, pos in account["positions"].items())
        nav = account["cash"] + marked + account["dividend_receivable"]
        valuations[name] = {"equity": nav, "cash": account["cash"], "position_value": marked,
                            "dividend_receivable": account["dividend_receivable"], "return_pct": (nav / 10000 - 1) * 100,
                            "holdings": sorted(account["positions"]), "exposure_pct": marked / nav * 100}
    pending, details = make_plans(state, day, frames, raw, now)
    state["pending"] = pending
    state["last_close"] = day
    state["processed_closes"] += 1
    snapshot_hash = digest(snapshot)
    folder = Path(home) / "inputs" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{snapshot_hash}.json"
    if not path.exists():
        with path.open("x", encoding="utf-8") as out:
            out.write(canonical(snapshot))
    events = []
    for i, fill in enumerate(fills):
        events.append(event(freeze, "PAPER_FILL", f"{day}:{i}", now, {"session": day, **fill, "recorded_after_close": True,
                            "snapshot_sha256": snapshot_hash}, account=fill["account"], ticker=fill["symbol"], action=fill["action"],
                            quantity=fill["shares"], fill_price=fill["execution_price"], cost=fill["commission"], signal_at=fill["decision_recorded_at"]))
    events.append(event(freeze, "CLOSE_PROCESSED", day, now, {"session": day, "state": state, "valuations": valuations,
                        "actions": actions, "signal_details": details, "snapshot_sha256": snapshot_hash,
                        "observed_at": snapshot["observed_at"], "decision_recorded_at": now.isoformat()}))
    ledger.append_batch(events)
    return status(home)


def status(home=DEFAULT_HOME):
    freeze = read_freeze(home)
    ledger, state = read_state(home, freeze)
    events = ledger.events()
    closes = [e for e in events if e["event_type"] == "CLOSE_PROCESSED"]
    return {"status": "ACTIVE_COLLECTING" if closes else "ARMED_WAITING_FIRST_FORWARD_CLOSE", "version": VERSION,
            "frozen_at": freeze["frozen_at"], "first_signal_session": freeze["first_signal_session"],
            "first_possible_fill_session": next_session(freeze["first_signal_session"]).isoformat(),
            "forward_sessions": state["processed_closes"], "primary_fill_count": sum(e["event_type"] == "PAPER_FILL" and e["portfolio_id"] == "E3" for e in events),
            "last_close": state["last_close"], "pending": state["pending"],
            "accounts": state["accounts"], "valuations": closes[-1]["payload"]["valuations"] if closes else {},
            "ledger_integrity": ledger.verify_integrity(), "freeze_sha256": freeze["content_sha256"],
            "ledger_events": len(events), "paper_only": True}


def capture_baseline(home, snapshot, now=None):
    """Retain pre-start warmup without producing trades or forward observations."""
    freeze = read_freeze(home)
    ledger, state = read_state(home, freeze)
    if state["processed_closes"]:
        raise RuntimeError("Baseline initialization is already over")
    expected = previous_session(freeze["first_signal_session"]).isoformat()
    if snapshot["session"] != expected:
        raise ValueError("Baseline must end on the last pre-forward session")
    validate_snapshot(snapshot, expected, stamp(now or datetime.now(timezone.utc)))
    records = [e for e in ledger.events(CONTROL) if e["event_type"] == "BASELINE_CAPTURED"]
    if records:
        return {"baseline_session": expected, "baseline_sha256": records[0]["payload"]["snapshot_sha256"], "forward_counted": False}
    checksum = digest(snapshot)
    folder = Path(home) / "warmup"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{checksum}.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical(snapshot))
    ledger.append_batch([event(freeze, "BASELINE_CAPTURED", "baseline", now or datetime.now(timezone.utc),
                         {"session": expected, "snapshot_sha256": checksum, "forward_counted": False,
                          "observed_at": snapshot["observed_at"], "symbols": list(SYMBOLS)})])
    return {"baseline_session": expected, "baseline_sha256": checksum, "forward_counted": False}
