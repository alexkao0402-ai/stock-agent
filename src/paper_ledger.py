"""Transactional append-only event ledger for V12 paper trading."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable


LEDGER_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    portfolio_id: str
    event_type: str
    strategy_version: str
    signal_timestamp: str
    execution_rule: str
    data_asof: str
    ticker: str = ""
    action: str = ""
    expected_price: float | None = None
    fill_price: float | None = None
    quantity: float | None = None
    cost: float | None = None
    reason: str = ""
    payload: dict[str, Any] | None = None
    created_at: str = ""


def deterministic_event_id(*parts: object) -> str:
    value = "|".join(str(part) for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content(event: LedgerEvent) -> dict[str, Any]:
    data = asdict(event)
    data.pop("created_at", None)
    data["payload"] = data.get("payload") or {}
    return data


def _content_hash(event: LedgerEvent) -> str:
    return hashlib.sha256(_canonical(_content(event)).encode("utf-8")).hexdigest()


class AppendOnlyLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO metadata(key, value)
                    VALUES ('schema_version', '1');
                CREATE TABLE IF NOT EXISTS event_log (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    portfolio_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    signal_timestamp TEXT NOT NULL,
                    execution_rule TEXT NOT NULL,
                    data_asof TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    expected_price REAL,
                    fill_price REAL,
                    quantity REAL,
                    cost REAL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    previous_event_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS event_log_no_update
                BEFORE UPDATE ON event_log
                BEGIN SELECT RAISE(ABORT, 'event_log is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS event_log_no_delete
                BEFORE DELETE ON event_log
                BEGIN SELECT RAISE(ABORT, 'event_log is append-only'); END;
                """
            )
            connection.commit()
        finally:
            connection.close()

    def append_batch(
        self,
        events: Iterable[LedgerEvent],
        *,
        _fail_after_inserts: int | None = None,
    ) -> dict[str, int]:
        """Append all new events in one transaction; identical retries are skipped."""
        prepared = list(events)
        if len({event.event_id for event in prepared}) != len(prepared):
            raise ValueError("event batch contains duplicate event IDs")
        created = 0
        skipped = 0
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT event_hash FROM event_log ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = str(row[0]) if row else "GENESIS"
            for event in prepared:
                content_hash = _content_hash(event)
                existing = connection.execute(
                    "SELECT content_hash FROM event_log WHERE event_id=?", (event.event_id,)
                ).fetchone()
                if existing:
                    if str(existing[0]) != content_hash:
                        raise RuntimeError(
                            f"event ID collision with different content: {event.event_id}"
                        )
                    skipped += 1
                    continue
                created_at = event.created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
                event_hash = hashlib.sha256(
                    f"{previous_hash}|{content_hash}|{created_at}".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO event_log(
                        event_id, portfolio_id, event_type, strategy_version,
                        signal_timestamp, execution_rule, data_asof, ticker, action,
                        expected_price, fill_price, quantity, cost, reason,
                        payload_json, created_at, content_hash, previous_event_hash,
                        event_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id, event.portfolio_id, event.event_type,
                        event.strategy_version, event.signal_timestamp,
                        event.execution_rule, event.data_asof, event.ticker,
                        event.action, event.expected_price, event.fill_price,
                        event.quantity, event.cost, event.reason,
                        _canonical(event.payload or {}), created_at, content_hash,
                        previous_hash, event_hash,
                    ),
                )
                previous_hash = event_hash
                created += 1
                if _fail_after_inserts is not None and created >= _fail_after_inserts:
                    raise RuntimeError("simulated crash inside ledger transaction")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"created": created, "skipped": skipped}

    def events(self, portfolio_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM event_log"
        params: tuple[Any, ...] = ()
        if portfolio_id is not None:
            query += " WHERE portfolio_id=?"
            params = (portfolio_id,)
        query += " ORDER BY sequence"
        connection = self._connect()
        try:
            rows = connection.execute(query, params).fetchall()
        finally:
            connection.close()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            output.append(item)
        return output

    def verify_integrity(self) -> bool:
        previous = "GENESIS"
        for row in self.events():
            reconstructed = LedgerEvent(
                event_id=row["event_id"],
                portfolio_id=row["portfolio_id"],
                event_type=row["event_type"],
                strategy_version=row["strategy_version"],
                signal_timestamp=row["signal_timestamp"],
                execution_rule=row["execution_rule"],
                data_asof=row["data_asof"],
                ticker=row["ticker"],
                action=row["action"],
                expected_price=row["expected_price"],
                fill_price=row["fill_price"],
                quantity=row["quantity"],
                cost=row["cost"],
                reason=row["reason"],
                payload=row["payload"],
                created_at=row["created_at"],
            )
            if _content_hash(reconstructed) != row["content_hash"]:
                raise RuntimeError("ledger content hash mismatch")
            if row["previous_event_hash"] != previous:
                raise RuntimeError("ledger hash chain is broken")
            expected = hashlib.sha256(
                f"{previous}|{row['content_hash']}|{row['created_at']}".encode("utf-8")
            ).hexdigest()
            if row["event_hash"] != expected:
                raise RuntimeError("ledger event hash mismatch")
            previous = row["event_hash"]
        return True
