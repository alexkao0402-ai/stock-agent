"""Initialize, inspect or run the isolated E3 forward-paper close cycle."""
from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "cache" / "researchdeps").is_dir():
    sys.path.insert(0, str(ROOT / "cache" / "researchdeps"))
sys.path.insert(0, str(ROOT))
from src.e3_forward import DEFAULT_HOME, SYMBOLS, capture_baseline, close_cycle, initialize, read_freeze, status
from src.trading_calendar import NEW_YORK, is_session, next_session, previous_session, session_close


def fetch_snapshot(day):
    import yfinance as yf
    import pandas as pd
    prices = {}
    for symbol in SYMBOLS:
        frame = yf.Ticker(symbol).history(period="2y", auto_adjust=False, actions=True, raise_errors=True, timeout=20)
        needed = {"Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"}
        if frame.empty or not needed.issubset(frame.columns):
            raise RuntimeError(f"Missing required raw/adjusted/action columns: {symbol}")
        rows = []
        for date, row in frame.iterrows():
            session = pd.Timestamp(date).strftime("%Y-%m-%d")
            if session > day:
                continue
            rows.append({"date": session, "open": float(row["Open"]), "high": float(row["High"]),
                         "low": float(row["Low"]), "close": float(row["Close"]), "adj_close": float(row["Adj Close"]),
                         "volume": float(row["Volume"]), "dividend": float(row["Dividends"]), "split": float(row["Stock Splits"])})
        prices[symbol] = rows
    return {"session": day, "observed_at": datetime.now(timezone.utc).isoformat(), "provider": "Yahoo Finance via yfinance; raw OHLC plus observed adjusted close and actions",
            "prices": prices}


def run_cycle(home):
    now = datetime.now(timezone.utc)
    freeze = read_freeze(home)
    day = now.astimezone(NEW_YORK).date().isoformat()
    current_status = status(home)
    if not is_session(day) or day < freeze["first_signal_session"]:
        return {**current_status, "cycle": "WAIT_NON_SESSION_OR_BEFORE_START"}
    if now < session_close(day) + timedelta(minutes=20):
        return {**current_status, "cycle": "WAIT_COMPLETED_DAILY_BAR"}
    if current_status["last_close"] == day:
        return {**current_status, "cycle": "ALREADY_PROCESSED"}
    expected = next_session(current_status["last_close"]).isoformat() if current_status["last_close"] else freeze["first_signal_session"]
    if day != expected:
        raise RuntimeError(f"Missed forward session {expected}; stopping without backfilled signals or fills")
    snapshot = fetch_snapshot(day)
    return {**close_cycle(home, snapshot), "cycle": "CLOSE_PROCESSED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "status", "cycle", "baseline"))
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.home)
        output = status(args.home)
    elif args.command == "status":
        output = status(args.home)
    elif args.command == "baseline":
        freeze = read_freeze(args.home)
        day = previous_session(freeze["first_signal_session"]).isoformat()
        output = capture_baseline(args.home, fetch_snapshot(day))
    else:
        output = run_cycle(args.home)
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
