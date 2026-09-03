"""Run one fail-closed, idempotent V12 Forward maintenance cycle."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

from dotenv import load_dotenv
import pandas as pd
import yfinance as yf

from src.config import get_secret
from src.dashboard_cloud_snapshot import (
    create_signed_snapshot,
    upload_supabase_snapshot,
    write_signed_snapshot,
)
from src.dashboard_read_model import build_dashboard_snapshot
from src.forward_execution import execute_due_portfolios
from src.forward_state_cloud import download_forward_state, upload_forward_state
from src.forward_valuation import record_daily_valuations
from src.paper_ledger import AppendOnlyLedger
from src.trading_calendar import NEW_YORK, is_month_end_session, is_session, session_close


REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "paper_ledger" / "v12_events.sqlite3"


def _cloud_configuration() -> dict[str, str]:
    values = {
        "project_url": get_secret("SUPABASE_URL") or "",
        "api_key": (
            get_secret("SUPABASE_SECRET_KEY")
            or get_secret("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ),
        "secret": get_secret("V12_DASHBOARD_SYNC_SECRET") or "",
        "bucket": get_secret("V12_DASHBOARD_SUPABASE_BUCKET") or "v12-dashboard",
    }
    missing = [name for name in ("project_url", "api_key", "secret") if not values[name]]
    if missing:
        raise RuntimeError(f"missing required cloud configuration: {', '.join(missing)}")
    return values


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def fetch_exact_raw_closes(tickers: list[str], valuation_date: str) -> dict[str, dict[str, float]]:
    date = pd.Timestamp(valuation_date)
    end = (date + timedelta(days=1)).date().isoformat()
    observations: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        frame = yf.download(
            ticker,
            start=date.date().isoformat(),
            end=end,
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
        )
        if frame.empty:
            raise RuntimeError(f"missing exact valuation-session data for {ticker}")
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        observed = pd.Timestamp(frame.index[0]).date().isoformat()
        if observed != valuation_date:
            raise RuntimeError(f"wrong valuation date for {ticker}: {observed}")
        close = float(frame["Close"].iloc[0]) if "Close" in frame else 0.0
        dividend = float(frame["Dividends"].iloc[0]) if "Dividends" in frame else 0.0
        split = float(frame["Stock Splits"].iloc[0]) if "Stock Splits" in frame else 0.0
        observations[ticker] = {"close": close, "dividend": dividend, "split": split}
    return observations


def _persist_forward_state(config: dict[str, str], commit: str) -> dict:
    return upload_forward_state(
        REPO_ROOT,
        config["project_url"], config["api_key"], config["secret"],
        bucket=config["bucket"],
        object_path=(
            get_secret("V12_FORWARD_STATE_SUPABASE_OBJECT")
            or "forward_state/v12_forward_state.json"
        ),
        source_commit=commit,
    )


def _publish_dashboard(config: dict[str, str], commit: str) -> None:
    state = build_dashboard_snapshot(LEDGER_PATH)
    envelope = create_signed_snapshot(state, config["secret"], source_commit=commit)
    write_signed_snapshot(envelope, REPO_ROOT / "dashboard_exports" / "v12_dashboard.json")
    upload_supabase_snapshot(
        envelope,
        config["project_url"],
        config["api_key"],
        bucket=config["bucket"],
        object_path=get_secret("V12_DASHBOARD_SUPABASE_OBJECT") or "v12_dashboard.json",
    )


def run_cycle(*, now: datetime | None = None) -> dict:
    config = _cloud_configuration()
    commit = _commit()
    state_object = (
        get_secret("V12_FORWARD_STATE_SUPABASE_OBJECT")
        or "forward_state/v12_forward_state.json"
    )
    restore_status = download_forward_state(
        REPO_ROOT,
        config["project_url"], config["api_key"], config["secret"],
        bucket=config["bucket"], object_path=state_object,
    )
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    new_york_now = current.astimezone(NEW_YORK)
    run_date = new_york_now.date().isoformat()
    if not is_session(run_date):
        _publish_dashboard(config, commit)
        return {"status": "SKIPPED_NON_SESSION", "date": run_date, "restore": restore_status}
    if current.astimezone(timezone.utc) < session_close(run_date).astimezone(timezone.utc):
        _publish_dashboard(config, commit)
        return {"status": "SKIPPED_BEFORE_CLOSE", "date": run_date, "restore": restore_status}

    captured = False
    if is_month_end_session(run_date):
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "capture_v12_live_inputs.py")],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"month-end capture failed: {completed.stdout.strip()}")
        captured = True
        _persist_forward_state(config, commit)

    from scripts.process_v12_paper_open import fetch_exact_raw_opens

    ledger = AppendOnlyLedger(LEDGER_PATH)
    executions = execute_due_portfolios(
        ledger,
        execution_date=run_date,
        price_fetcher=fetch_exact_raw_opens,
        recorded_at=current,
    )
    if executions:
        _persist_forward_state(config, commit)

    valuations = record_daily_valuations(
        ledger,
        valuation_date=run_date,
        observation_fetcher=fetch_exact_raw_closes,
        recorded_at=current,
    )
    if valuations:
        _persist_forward_state(config, commit)

    ledger.verify_integrity()
    _publish_dashboard(config, commit)
    return {
        "status": "COMPLETED",
        "date": run_date,
        "restore": restore_status,
        "month_end_capture": captured,
        "executed_portfolios": [row["portfolio_id"] for row in executions],
        "valued_portfolios": [row["portfolio_id"] for row in valuations],
    }


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    try:
        result = run_cycle()
    except Exception as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
