"""Immutable evidence and pending-order preparation for official V12 forward runs."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import pandas as pd

from src.live_large_cap_data import LiveDataError
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id
from src.trading_calendar import NEW_YORK, is_month_end_session, next_session, session_close, session_open
from src.v12_live_signal import FROZEN_VERSION


FREEZE_DATE = pd.Timestamp("2026-08-28").date()
INITIAL_CAPITAL = 10_000.0
EVIDENCE_DIR = Path("live_forward_runs")
PORTFOLIOS = {
    "V12_T1": "T+1_OPEN",
    "V12_T2": "T+2_OPEN",
    "SPY_T1": "T+1_OPEN",
    "SPY_T2": "T+2_OPEN",
    "QQQ_T1": "T+1_OPEN",
    "QQQ_T2": "T+2_OPEN",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise LiveDataError("recorded_at must be timezone-aware")
    return current.astimezone(timezone.utc)


def _validate_source_bundle(input_root: Path, signal_path: Path) -> tuple[dict, dict, pd.DataFrame, pd.DataFrame]:
    manifest_path = input_root / "manifest.json"
    if not manifest_path.exists() or not signal_path.exists():
        raise LiveDataError("input manifest or frozen signal is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in manifest.get("files", {}).items():
        path = input_root / name
        if not path.exists() or _sha256(path) != expected:
            raise LiveDataError(f"input integrity failure: {name}")
    signal = json.loads(signal_path.read_text(encoding="utf-8"))
    if signal.get("frozen_version") != FROZEN_VERSION:
        raise LiveDataError("strategy version does not match Frozen V12")
    if signal.get("source_manifest_sha256") != _sha256(manifest_path):
        raise LiveDataError("signal is not linked to the supplied input manifest")
    universe = pd.read_csv(input_root / "monthly_universe.csv")
    prices = pd.read_csv(input_root / "daily_prices.csv")
    if len(universe) != 10 or set(universe["market_cap_rank"].astype(int)) != set(range(1, 11)):
        raise LiveDataError("official evidence requires a complete top-ten universe")
    required_price_columns = {
        "ticker", "trade_date", "open", "close", "adjusted_close",
        "dividend", "stock_split", "source_timestamp",
    }
    if not required_price_columns.issubset(prices.columns):
        raise LiveDataError(
            f"price snapshot is malformed: missing {sorted(required_price_columns - set(prices.columns))}"
        )
    if prices.duplicated(["ticker", "trade_date"]).any():
        raise LiveDataError("price snapshot contains duplicate ticker/date rows")
    signal_date = str(signal.get("signal_date"))
    expected_tickers = set(universe["ticker"].astype(str)) | {"SPY", "QQQ"}
    observed_tickers = set(prices["ticker"].astype(str))
    if not expected_tickers.issubset(observed_tickers):
        raise LiveDataError(
            f"price snapshot is partial: missing {sorted(expected_tickers - observed_tickers)}"
        )
    latest = prices.groupby("ticker")["trade_date"].max().astype(str)
    stale = sorted(ticker for ticker in expected_tickers if latest.get(ticker) != signal_date)
    if stale:
        raise LiveDataError(f"price snapshot is stale for: {', '.join(stale)}")
    numeric = prices[["open", "close", "adjusted_close"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or bool((numeric <= 0).any().any()):
        raise LiveDataError("price snapshot contains missing or non-positive prices")
    return manifest, signal, universe, prices


def _pending_instructions(signal: dict, prices: pd.DataFrame) -> list[dict[str, Any]]:
    signal_date = signal["signal_date"]
    latest = prices[prices["trade_date"].astype(str).eq(signal_date)].copy()
    close_map = dict(zip(latest["ticker"].astype(str), pd.to_numeric(latest["close"], errors="coerce")))
    instructions = []
    targets = dict(signal.get("target_weights") or {})
    for portfolio_id, rule in PORTFOLIOS.items():
        if portfolio_id.startswith("V12"):
            weights = targets
        elif portfolio_id.startswith("SPY"):
            weights = {"SPY": 1.0}
        else:
            weights = {"QQQ": 1.0}
        delay = 1 if "T1" in portfolio_id else 2
        execution_date = next_session(signal_date, delay).isoformat()
        for ticker, weight in sorted(weights.items()):
            price = close_map.get(ticker)
            if price is None or not pd.notna(price) or float(price) <= 0:
                raise LiveDataError(f"missing signal-date raw close for pending order: {ticker}")
            event_id = deterministic_event_id(
                FROZEN_VERSION, signal_date, rule, portfolio_id, ticker, "TARGET_WEIGHT"
            )
            instructions.append(
                {
                    "event_id": event_id,
                    "portfolio_id": portfolio_id,
                    "execution_rule": rule,
                    "execution_date": execution_date,
                    "ticker": ticker,
                    "action": "TARGET_WEIGHT",
                    "target_weight": float(weight),
                    "expected_price": float(price),
                    "status": "PENDING",
                }
            )
        if portfolio_id.startswith("V12") and not weights:
            instructions.append(
                {
                    "event_id": deterministic_event_id(
                        FROZEN_VERSION, signal_date, rule, portfolio_id, "CASH", "TARGET_CASH"
                    ),
                    "portfolio_id": portfolio_id,
                    "execution_rule": rule,
                    "execution_date": execution_date,
                    "ticker": "CASH",
                    "action": "TARGET_CASH",
                    "target_weight": 1.0,
                    "expected_price": 1.0,
                    "status": "PENDING",
                }
            )
    return instructions


def _ledger_events(signal: dict, pending: list[dict[str, Any]], recorded_at: str) -> list[LedgerEvent]:
    signal_date = signal["signal_date"]
    signal_timestamp = session_close(signal_date).isoformat()
    events: list[LedgerEvent] = []
    initialization_timestamp = "2026-08-28T16:00:00-04:00"
    for portfolio_id, execution_rule in PORTFOLIOS.items():
        if portfolio_id.startswith("V12"):
            portfolio_targets = dict(signal["target_weights"])
        elif portfolio_id.startswith("SPY"):
            portfolio_targets = {"SPY": 1.0}
        else:
            portfolio_targets = {"QQQ": 1.0}
        events.append(
            LedgerEvent(
                event_id=deterministic_event_id(FROZEN_VERSION, portfolio_id, "INITIALIZE"),
                portfolio_id=portfolio_id,
                event_type="INITIALIZE",
                strategy_version=FROZEN_VERSION,
                signal_timestamp=initialization_timestamp,
                execution_rule=execution_rule,
                data_asof=initialization_timestamp,
                reason="Frozen paper account initialization",
                payload={"initial_capital": INITIAL_CAPITAL, "currency": "USD"},
                created_at=recorded_at,
            )
        )
        events.append(
            LedgerEvent(
                event_id=deterministic_event_id(FROZEN_VERSION, signal_date, portfolio_id, "SIGNAL"),
                portfolio_id=portfolio_id,
                event_type="SIGNAL",
                strategy_version=FROZEN_VERSION,
                signal_timestamp=signal_timestamp,
                execution_rule=execution_rule,
                data_asof=signal_timestamp,
                reason="Official forward signal; not backtest and not backfilled",
                payload={
                    "signal_date": signal_date,
                    "market_regime": "BULL" if signal["spy_bull"] else "CASH",
                    "v7_selected": signal["v7_selected"],
                    "v8_selected": signal["v8_selected"],
                    "v12_target_weights": signal["target_weights"],
                    "portfolio_target_weights": portfolio_targets,
                },
                created_at=recorded_at,
            )
        )
    for item in pending:
        events.append(
            LedgerEvent(
                event_id=item["event_id"],
                portfolio_id=item["portfolio_id"],
                event_type="ORDER",
                strategy_version=FROZEN_VERSION,
                signal_timestamp=signal_timestamp,
                execution_rule=item["execution_rule"],
                data_asof=signal_timestamp,
                ticker=item["ticker"],
                action=item["action"],
                expected_price=item["expected_price"],
                reason="Pending target for next valid US trading-session open",
                payload={
                    "status": "PENDING",
                    "target_weight": item["target_weight"],
                    "execution_date": item["execution_date"],
                },
                created_at=recorded_at,
            )
        )
    return events


def _verify_published(root: Path, required_event_ids: set[str], ledger: AppendOnlyLedger) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise LiveDataError("published evidence manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in manifest.get("files", {}).items():
        path = root / name
        if not path.exists() or _sha256(path) != expected:
            raise LiveDataError(f"published evidence hash mismatch: {name}")
    ledger_ids = {row["event_id"] for row in ledger.events()}
    if not required_event_ids.issubset(ledger_ids):
        raise LiveDataError("evidence exists without its complete ledger transaction")


def prepare_forward_evidence(
    input_root: str | Path,
    signal_path: str | Path,
    *,
    ledger_path: str | Path,
    output_directory: str | Path = EVIDENCE_DIR,
    git_commit: str,
    recorded_at: datetime | None = None,
    implementation_hashes: dict[str, str] | None = None,
    _fail_after_ledger: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    """Atomically append signal/orders and publish an immutable evidence package."""
    if len(git_commit.strip()) < 7:
        raise LiveDataError("a Git commit identifier is required for official evidence")
    input_root = Path(input_root)
    signal_path = Path(signal_path)
    manifest, signal, universe, prices = _validate_source_bundle(input_root, signal_path)
    signal_date = pd.Timestamp(signal["signal_date"]).date()
    if signal_date <= FREEZE_DATE:
        raise LiveDataError("official forward evidence cannot be pre-freeze or backfilled")
    if not is_month_end_session(signal_date):
        raise LiveDataError("signal date is not the last valid NYSE session of the month")
    now_utc = _parse_now(recorded_at)
    if now_utc < session_close(signal_date).astimezone(timezone.utc):
        raise LiveDataError("official evidence cannot be created before the US market close")
    if now_utc >= session_open(next_session(signal_date, 1)).astimezone(timezone.utc):
        raise LiveDataError("official signal preparation window has passed; backfill is prohibited")
    pending = _pending_instructions(signal, prices)
    recorded_text = now_utc.isoformat(timespec="seconds")
    events = _ledger_events(signal, pending, recorded_text)
    required_event_ids = {event.event_id for event in events}
    run_seed = f"{FROZEN_VERSION}|{signal_date.isoformat()}|{_sha256(input_root / 'manifest.json')}"
    run_id = hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:24]
    root = Path(output_directory) / signal_date.isoformat()
    ledger = AppendOnlyLedger(ledger_path)
    if root.exists():
        _verify_published(root, required_event_ids, ledger)
        return root, "ALREADY_PROCESSED", json.loads((root / "run.json").read_text(encoding="utf-8"))

    temporary = Path(output_directory) / f".{run_id}.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        for name in ["monthly_universe.csv", "daily_prices.csv", "selection_details.json", "manifest.json"]:
            shutil.copy2(input_root / name, temporary / f"input_{name}")
        shutil.copy2(signal_path, temporary / "v12_signal.json")
        evidence = {
            "schema_version": 1,
            "run_id": run_id,
            "classification": ["FORWARD", "NOT_BACKTEST", "NOT_BACKFILLED"],
            "strategy_version": FROZEN_VERSION,
            "signal_date": signal_date.isoformat(),
            "signal_timestamp": session_close(signal_date).isoformat(),
            "recorded_at": recorded_text,
            "data_asof": signal_date.isoformat(),
            "git_commit": git_commit.strip(),
            "implementation_hashes": implementation_hashes or {},
            "execution_rules": {"official": "T+1_OPEN", "challenger": "T+2_OPEN"},
            "universe_snapshot": universe.sort_values("market_cap_rank").to_dict(orient="records"),
            "market_cap_snapshot": universe[["stable_company_id", "ticker", "company_market_cap", "market_cap_rank"]].to_dict(orient="records"),
            "ticker_mapping": universe[["stable_company_id", "stable_security_id", "ticker"]].to_dict(orient="records"),
            "v7_selection": signal["v7_selected"],
            "v8_selection": signal["v8_selected"],
            "v12_selection": sorted(signal["target_weights"]),
            "target_weights": signal["target_weights"],
            "market_regime": "BULL" if signal["spy_bull"] else "CASH",
            "pending_orders": pending,
            "source_manifest_sha256": signal["source_manifest_sha256"],
            "provider_policy": json.loads((input_root / "selection_details.json").read_text(encoding="utf-8")).get("provider_policy"),
        }
        (temporary / "run.json").write_bytes(_canonical(evidence))
        file_hashes = {
            path.name: _sha256(path)
            for path in sorted(temporary.iterdir())
            if path.is_file()
        }
        evidence_manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "files": file_hashes,
            "source_files": manifest["files"],
            "ledger_event_ids": sorted(required_event_ids),
            "immutability": "Published evidence is never overwritten",
        }
        (temporary / "manifest.json").write_bytes(_canonical(evidence_manifest))
        ledger_result = ledger.append_batch(events)
        if _fail_after_ledger:
            raise RuntimeError("simulated crash after ledger commit")
        root.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(root)
        ledger.verify_integrity()
        return root, "CREATED", {**evidence, "ledger_result": ledger_result}
    except Exception:
        # A committed ledger batch is safe to retry because every ID is deterministic.
        # Temporary evidence is deliberately left for inspection/recovery.
        raise
