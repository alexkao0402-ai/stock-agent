from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from src.forward_execution import (
    due_portfolio_targets,
    execute_due_portfolios,
    execute_target_weights,
    portfolio_state_from_ledger,
)
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id
from src.v12_live_signal import FROZEN_VERSION


def _initialized_ledger(path: Path, portfolio_id: str = "V12_T1") -> AppendOnlyLedger:
    ledger = AppendOnlyLedger(path)
    ledger.append_batch([
        LedgerEvent(
            event_id=deterministic_event_id(FROZEN_VERSION, portfolio_id, "INITIALIZE"),
            portfolio_id=portfolio_id,
            event_type="INITIALIZE",
            strategy_version=FROZEN_VERSION,
            signal_timestamp="2026-08-31T16:00:00-04:00",
            execution_rule="T+1_OPEN",
            data_asof="2026-08-31T16:00:00-04:00",
            reason="test",
            payload={"initial_capital": 10_000.0},
            created_at="2026-08-31T20:05:00+00:00",
        )
    ])
    return ledger


class ForwardExecutionTests(unittest.TestCase):
    def test_fill_and_snapshot_reconcile(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = _initialized_ledger(Path(temp) / "ledger.sqlite3")
            result = execute_target_weights(
                ledger,
                portfolio_id="V12_T1",
                signal_date="2026-08-31",
                execution_rule="T+1_OPEN",
                target_weights={"AAPL": 0.5, "MSFT": 0.5},
                raw_open_prices={"AAPL": 200.0, "MSFT": 500.0},
                execution_date="2026-09-01",
                recorded_at=datetime(2026, 9, 1, 13, 31, tzinfo=timezone.utc),
            )
            snapshot = result["snapshot"]
            self.assertAlmostEqual(
                snapshot["portfolio_equity"], snapshot["cash"] + snapshot["market_value"]
            )
            state = portfolio_state_from_ledger(ledger, "V12_T1")
            self.assertEqual(set(state.positions), {"AAPL", "MSFT"})

    def test_execution_retry_does_not_duplicate_fills(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = _initialized_ledger(Path(temp) / "ledger.sqlite3")
            kwargs = dict(
                portfolio_id="V12_T1", signal_date="2026-08-31",
                execution_rule="T+1_OPEN", target_weights={"AAPL": 1.0},
                raw_open_prices={"AAPL": 200.0}, execution_date="2026-09-01",
                recorded_at=datetime(2026, 9, 1, 13, 31, tzinfo=timezone.utc),
            )
            execute_target_weights(ledger, **kwargs)
            second = execute_target_weights(ledger, **kwargs)
            self.assertEqual(second["status"], "ALREADY_PROCESSED")
            self.assertEqual(len([row for row in ledger.events() if row["event_type"] == "FILL"]), 1)

    def test_wrong_session_and_partial_transaction_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = _initialized_ledger(Path(temp) / "ledger.sqlite3")
            kwargs = dict(
                portfolio_id="V12_T1", signal_date="2026-08-31",
                execution_rule="T+1_OPEN", target_weights={"AAPL": 1.0},
                raw_open_prices={"AAPL": 200.0},
                recorded_at=datetime(2026, 9, 1, 13, 31, tzinfo=timezone.utc),
            )
            with self.assertRaises(ValueError):
                execute_target_weights(ledger, execution_date="2026-09-02", **kwargs)
            with self.assertRaises(RuntimeError):
                execute_target_weights(
                    ledger, execution_date="2026-09-01", _fail_after_inserts=1, **kwargs
                )
            self.assertEqual(len([row for row in ledger.events() if row["event_type"] == "FILL"]), 0)

    def test_due_portfolio_orchestrator_runs_once_after_close(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = _initialized_ledger(Path(temp) / "ledger.sqlite3")
            ledger.append_batch([
                LedgerEvent(
                    event_id=deterministic_event_id(FROZEN_VERSION, "2026-08-31", "V12_T1", "SIGNAL"),
                    portfolio_id="V12_T1",
                    event_type="SIGNAL",
                    strategy_version=FROZEN_VERSION,
                    signal_timestamp="2026-08-31T16:00:00-04:00",
                    execution_rule="T+1_OPEN",
                    data_asof="2026-08-31T16:00:00-04:00",
                    reason="test",
                    payload={"signal_date": "2026-08-31", "portfolio_target_weights": {"AAPL": 1.0}},
                    created_at="2026-08-31T20:05:00+00:00",
                )
            ])
            self.assertEqual(len(due_portfolio_targets(ledger, "2026-09-01")), 1)
            results = execute_due_portfolios(
                ledger,
                execution_date="2026-09-01",
                price_fetcher=lambda tickers, date: {ticker: 200.0 for ticker in tickers},
                recorded_at=datetime(2026, 9, 1, 20, 5, tzinfo=timezone.utc),
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(due_portfolio_targets(ledger, "2026-09-01"), [])
            self.assertEqual(execute_due_portfolios(
                ledger,
                execution_date="2026-09-01",
                price_fetcher=lambda tickers, date: {ticker: 200.0 for ticker in tickers},
                recorded_at=datetime(2026, 9, 1, 20, 6, tzinfo=timezone.utc),
            ), [])


if __name__ == "__main__":
    unittest.main()
