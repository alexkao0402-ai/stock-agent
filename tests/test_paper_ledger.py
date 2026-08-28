import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id


def _event(name: str, *, ticker: str = "") -> LedgerEvent:
    return LedgerEvent(
        event_id=deterministic_event_id("V12", "2026-08-31", "T1", name, ticker),
        portfolio_id="V12_T1",
        event_type=name,
        strategy_version="V12-FROZEN-2026-08-28",
        signal_timestamp="2026-08-31T16:00:00-04:00",
        execution_rule="T+1_OPEN",
        data_asof="2026-08-31T16:00:00-04:00",
        ticker=ticker,
        reason="test",
        payload={"status": "PENDING"},
        created_at="2026-08-31T20:05:00+00:00",
    )


class AppendOnlyLedgerTests(unittest.TestCase):
    def test_identical_retry_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = AppendOnlyLedger(Path(temp) / "ledger.sqlite3")
            event = _event("SIGNAL")
            self.assertEqual(ledger.append_batch([event]), {"created": 1, "skipped": 0})
            self.assertEqual(ledger.append_batch([event]), {"created": 0, "skipped": 1})
            self.assertEqual(len(ledger.events()), 1)
            self.assertTrue(ledger.verify_integrity())

    def test_same_id_with_changed_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = AppendOnlyLedger(Path(temp) / "ledger.sqlite3")
            original = _event("ORDER", ticker="AAPL")
            ledger.append_batch([original])
            changed = LedgerEvent(**{**original.__dict__, "reason": "changed"})
            with self.assertRaises(RuntimeError):
                ledger.append_batch([changed])

    def test_partial_batch_crash_rolls_back_every_event(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = AppendOnlyLedger(Path(temp) / "ledger.sqlite3")
            batch = [_event("SIGNAL"), _event("ORDER", ticker="AAPL")]
            with self.assertRaises(RuntimeError):
                ledger.append_batch(batch, _fail_after_inserts=1)
            self.assertEqual(ledger.events(), [])
            self.assertEqual(ledger.append_batch(batch)["created"], 2)

    def test_database_triggers_reject_update_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.sqlite3"
            ledger = AppendOnlyLedger(path)
            ledger.append_batch([_event("SIGNAL")])
            connection = sqlite3.connect(path)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("UPDATE event_log SET reason='x'")
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("DELETE FROM event_log")
            finally:
                connection.close()

    def test_integrity_recomputes_content_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.sqlite3"
            ledger = AppendOnlyLedger(path)
            ledger.append_batch([_event("SIGNAL")])
            connection = sqlite3.connect(path)
            try:
                connection.execute("DROP TRIGGER event_log_no_update")
                connection.execute("UPDATE event_log SET reason='tampered'")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(RuntimeError):
                ledger.verify_integrity()


if __name__ == "__main__":
    unittest.main()
