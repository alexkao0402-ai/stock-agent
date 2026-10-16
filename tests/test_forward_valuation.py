from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from src.forward_execution import execute_target_weights
from src.forward_valuation import record_daily_valuations
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id
from src.v12_live_signal import FROZEN_VERSION


def _ledger(path: Path) -> AppendOnlyLedger:
    ledger = AppendOnlyLedger(path)
    ledger.append_batch([LedgerEvent(
        event_id=deterministic_event_id(FROZEN_VERSION, "V12_T1", "INITIALIZE"),
        portfolio_id="V12_T1",
        event_type="INITIALIZE",
        strategy_version=FROZEN_VERSION,
        signal_timestamp="2026-08-31T16:00:00-04:00",
        execution_rule="T+1_OPEN",
        data_asof="2026-08-31T16:00:00-04:00",
        reason="fixture",
        payload={"initial_capital": 10_000.0},
        created_at="2026-08-31T20:05:00+00:00",
    )])
    execute_target_weights(
        ledger,
        portfolio_id="V12_T1",
        signal_date="2026-08-31",
        execution_rule="T+1_OPEN",
        target_weights={"AAPL": 1.0},
        raw_open_prices={"AAPL": 200.0},
        execution_date="2026-09-01",
        recorded_at=datetime(2026, 9, 1, 20, 5, tzinfo=timezone.utc),
    )
    return ledger


class ForwardValuationTests(unittest.TestCase):
    def test_daily_close_valuation_reconciles_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = _ledger(Path(temp) / "ledger.sqlite3")
            kwargs = dict(
                valuation_date="2026-09-02",
                observation_fetcher=lambda tickers, day: {
                    ticker: {"close": 210.0, "dividend": 0.0, "split": 0.0}
                    for ticker in tickers
                },
                recorded_at=datetime(2026, 9, 2, 21, 0, tzinfo=timezone.utc),
            )
            first = record_daily_valuations(ledger, **kwargs)
            second = record_daily_valuations(ledger, **kwargs)
            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])
            row = [r for r in ledger.events() if r["event_type"] == "VALUATION_SNAPSHOT"][0]
            payload = row["payload"]
            self.assertAlmostEqual(
                payload["portfolio_equity"], payload["cash"] + payload["market_value"]
            )
            self.assertTrue(ledger.verify_integrity())

    def test_corporate_action_fails_before_any_valuation_is_written(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = _ledger(Path(temp) / "ledger.sqlite3")
            with self.assertRaisesRegex(RuntimeError, "corporate action"):
                record_daily_valuations(
                    ledger,
                    valuation_date="2026-09-02",
                    observation_fetcher=lambda tickers, day: {
                        "AAPL": {"close": 210.0, "dividend": 0.25, "split": 0.0}
                    },
                    recorded_at=datetime(2026, 9, 2, 21, 0, tzinfo=timezone.utc),
                )
            self.assertFalse(any(
                row["event_type"] == "VALUATION_SNAPSHOT" for row in ledger.events()
            ))


if __name__ == "__main__":
    unittest.main()
