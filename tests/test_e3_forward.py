from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.e3_forward import SYMBOLS, capture_baseline, close_cycle, initialize, read_state, session_window, status
from src.trading_calendar import next_session, previous_session, session_close

FREEZE = datetime(2026, 10, 27, 6, 30, tzinfo=timezone.utc)


def snapshot(day, now=None, dividend=0.0, split=0.0):
    dates = list(reversed(session_window(day, 260)))
    # Absolute time trend: histories stay the same when the snapshot window rolls.
    from datetime import date
    prices = {}
    for symbol in SYMBOLS:
        rows = []
        for day_text in dates:
            trend = 100 + (date.fromisoformat(day_text) - date(2025, 1, 1)).days * 0.05
            price = trend - 5 if symbol == "AAPL" and day_text == "2026-10-27" else trend
            rows.append({"date": day_text, "open": price, "high": price * 1.01, "low": price * 0.99,
                         "close": price, "adj_close": price, "volume": 10000, "dividend": 0.0, "split": 0.0})
        if symbol == "AAPL":
            rows[-1]["dividend"], rows[-1]["split"] = dividend, split
        prices[symbol] = rows
    from datetime import timedelta
    observed = now or (session_close(day) + timedelta(minutes=30))
    return {"session": day, "observed_at": observed.isoformat(), "provider": "synthetic unit-test fixture", "prices": prices}


class E3ForwardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        initialize(self.home, FREEZE)

    def tearDown(self):
        self.temp.cleanup()

    def run_day(self, day, **options):
        item = snapshot(day, **options)
        return close_cycle(self.home, item, item["observed_at"])

    def test_initialization_is_idempotent_and_no_past_trades(self):
        initialize(self.home, datetime(2026, 10, 28, 6, tzinfo=timezone.utc))
        out = status(self.home)
        self.assertEqual(out["first_signal_session"], "2026-10-27")
        self.assertEqual(out["first_possible_fill_session"], "2026-10-28")
        self.assertEqual(out["forward_sessions"], 0)
        self.assertEqual(out["ledger_events"], 1)

    def test_t_plus_one_fill_and_retry_are_atomic(self):
        first = self.run_day("2026-10-27")
        self.assertEqual(first["primary_fill_count"], 0)
        self.assertIn("AAPL", first["pending"]["plans"]["E3"]["entries"])
        second = self.run_day("2026-10-28")
        self.assertEqual(second["primary_fill_count"], 1)
        self.assertEqual(second["accounts"]["E3"]["positions"]["AAPL"]["held_sessions"], 1)
        self.assertEqual(second, self.run_day("2026-10-28"))
        ledger, _ = read_state(self.home)
        fills = [e for e in ledger.events("E3") if e["event_type"] == "PAPER_FILL"]
        self.assertEqual(fills[0]["payload"]["signal_date"], "2026-10-27")
        self.assertLess(fills[0]["signal_timestamp"], fills[0]["created_at"])

    def test_no_early_close_or_future_bar(self):
        data = snapshot("2026-10-27")
        with self.assertRaises(ValueError):
            close_cycle(self.home, data, session_close("2026-10-27"))
        data["prices"]["MSFT"][-1]["date"] = "2026-10-28"
        with self.assertRaisesRegex(ValueError, "future bars"):
            close_cycle(self.home, data, data["observed_at"])
        self.assertEqual(status(self.home)["forward_sessions"], 0)

    def test_missing_session_halts_without_backfill(self):
        with self.assertRaisesRegex(RuntimeError, "gap"):
            self.run_day("2026-10-28")
        self.assertEqual(status(self.home)["primary_fill_count"], 0)

    def test_missing_symbol_or_warmup_rejected(self):
        data = snapshot("2026-10-27")
        del data["prices"]["NVDA"]
        with self.assertRaises(ValueError):
            close_cycle(self.home, data, data["observed_at"])
        data = snapshot("2026-10-27")
        data["prices"]["NVDA"] = data["prices"]["NVDA"][-10:]
        with self.assertRaisesRegex(ValueError, "warmup"):
            close_cycle(self.home, data, data["observed_at"])

    def test_exit_after_ten_held_session_closes(self):
        self.run_day("2026-10-27")
        day = "2026-10-28"
        for i in range(10):
            output = self.run_day(day)
            self.assertEqual(output["accounts"]["E3"]["positions"]["AAPL"]["held_sessions"], i + 1)
            if i < 9:
                day = next_session(day).isoformat()
        self.assertIn("AAPL", output["pending"]["plans"]["E3"]["exits"])
        sold = self.run_day(next_session(day).isoformat())
        self.assertEqual(sold["primary_fill_count"], 2)
        self.assertNotIn("AAPL", sold["accounts"]["E3"]["positions"])

    def test_dividend_receivable_is_not_spendable_cash(self):
        self.run_day("2026-10-27")
        bought = self.run_day("2026-10-28")
        quantity = bought["accounts"]["E3"]["positions"]["AAPL"]["shares"]
        accrued = self.run_day("2026-10-29", dividend=0.5)
        account = accrued["accounts"]["E3"]
        self.assertAlmostEqual(account["cash"], bought["accounts"]["E3"]["cash"])
        self.assertAlmostEqual(account["dividend_receivable"], quantity * 0.5)

    def test_baseline_is_not_forward_data(self):
        data = snapshot("2026-10-26", now=FREEZE)
        result = capture_baseline(self.home, data, FREEZE)
        self.assertFalse(result["forward_counted"])
        self.assertEqual(status(self.home)["forward_sessions"], 0)
        self.assertEqual(status(self.home)["primary_fill_count"], 0)

    def test_modified_freeze_fails_closed(self):
        path = self.home / "freeze.json"
        data = json.loads(path.read_text())
        data["rules"]["holding_sessions"] = 20
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "manifest was modified"):
            status(self.home)

    def test_ledger_refuses_update_and_delete(self):
        connection = sqlite3.connect(self.home / "events.sqlite3")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM event_log")
        finally:
            connection.close()

    def test_changed_input_snapshot_is_detected(self):
        self.run_day("2026-10-27")
        path = next((self.home / "inputs" / "2026-10-27").glob("*.json"))
        content = json.loads(path.read_text())
        content["prices"]["AAPL"][-1]["close"] = 999
        path.write_text(json.dumps(content))
        with self.assertRaisesRegex(RuntimeError, "hash changed"):
            status(self.home)

    def test_split_adjusts_shares_before_marks(self):
        self.run_day("2026-10-27")
        before = self.run_day("2026-10-28")
        shares = before["accounts"]["E3"]["positions"]["AAPL"]["shares"]
        after = self.run_day("2026-10-29", split=2)
        self.assertAlmostEqual(after["accounts"]["E3"]["positions"]["AAPL"]["shares"], shares * 2)


if __name__ == "__main__":
    unittest.main()
