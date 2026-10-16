from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.forward_evidence import prepare_forward_evidence
from src.live_large_cap_data import LiveDataError, write_immutable_live_inputs
from src.paper_ledger import AppendOnlyLedger
from src.v12_live_signal import write_immutable_v12_signal


def _make_bundle(root: Path) -> tuple[Path, Path]:
    signal_date = "2026-08-31"
    selected = [
        {
            "market_cap_rank": index,
            "stable_company_id": f"COMPANY-{index:02d}",
            "stable_security_id": f"SECURITY-{index:02d}",
            "ticker": f"S{index:02d}",
            "company_market_cap": float(1_000 - index),
            "history_rows": 300,
            "history_status": "SUFFICIENT_FOR_V12",
        }
        for index in range(1, 11)
    ]
    dates = pd.bdate_range(end=signal_date, periods=300)
    rows = []
    for index, ticker in enumerate([*(f"S{i:02d}" for i in range(1, 11)), "SPY", "QQQ"], start=1):
        growth = 0.0003 + index * 0.00005
        adjusted = 100.0 * np.exp(np.arange(len(dates)) * growth)
        for date, price in zip(dates, adjusted):
            rows.append(
                {
                    "ticker": ticker,
                    "trade_date": date.date().isoformat(),
                    "open": price * 0.999,
                    "close": price,
                    "adjusted_close": price,
                    "total_return_or_corporate_action_adjustment": 1.0,
                    "dividend": 0.0,
                    "stock_split": 0.0,
                }
            )
    input_dir = root / "inputs"
    input_root, _ = write_immutable_live_inputs(
        signal_date,
        selected,
        pd.DataFrame(rows),
        source_hashes={"synthetic": "a" * 64},
        exclusions=[],
        coverage={"selected_companies": 10},
        directory=input_dir,
        captured_at="2026-08-31T20:05:00+00:00",
    )
    signal_dir = root / "signals"
    signal_path, _, _ = write_immutable_v12_signal(input_root, output_directory=signal_dir)
    return input_root, signal_path


class ForwardEvidenceTests(unittest.TestCase):
    def test_creates_complete_immutable_evidence_and_ledger_events(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, signal = _make_bundle(root)
            evidence, status, run = prepare_forward_evidence(
                inputs,
                signal,
                ledger_path=root / "ledger" / "events.sqlite3",
                output_directory=root / "runs",
                git_commit="1" * 40,
                implementation_hashes={"v12_live_signal.py": "b" * 64},
                recorded_at=datetime(2026, 8, 31, 20, 5, tzinfo=timezone.utc),
            )
            self.assertEqual(status, "CREATED")
            self.assertEqual(run["classification"], ["FORWARD", "NOT_BACKTEST", "NOT_BACKFILLED"])
            self.assertTrue((evidence / "manifest.json").exists())
            self.assertEqual(len(run["pending_orders"]), 8)  # V12 two names twice + SPY/QQQ twice.
            ledger = AppendOnlyLedger(root / "ledger" / "events.sqlite3")
            self.assertTrue(ledger.verify_integrity())
            self.assertEqual(len(ledger.events()), 20)  # 6 init + 6 signal + 8 pending orders.

    def test_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, signal = _make_bundle(root)
            kwargs = dict(
                ledger_path=root / "ledger.sqlite3",
                output_directory=root / "runs",
                git_commit="2" * 40,
                recorded_at=datetime(2026, 8, 31, 20, 5, tzinfo=timezone.utc),
            )
            prepare_forward_evidence(inputs, signal, **kwargs)
            _, status, _ = prepare_forward_evidence(inputs, signal, **kwargs)
            self.assertEqual(status, "ALREADY_PROCESSED")
            self.assertEqual(len(AppendOnlyLedger(root / "ledger.sqlite3").events()), 20)

    def test_crash_after_ledger_is_retry_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, signal = _make_bundle(root)
            kwargs = dict(
                ledger_path=root / "ledger.sqlite3",
                output_directory=root / "runs",
                git_commit="3" * 40,
                recorded_at=datetime(2026, 8, 31, 20, 5, tzinfo=timezone.utc),
            )
            with self.assertRaises(RuntimeError):
                prepare_forward_evidence(inputs, signal, _fail_after_ledger=True, **kwargs)
            self.assertEqual(len(AppendOnlyLedger(root / "ledger.sqlite3").events()), 20)
            _, status, _ = prepare_forward_evidence(inputs, signal, **kwargs)
            self.assertEqual(status, "CREATED")
            self.assertEqual(len(AppendOnlyLedger(root / "ledger.sqlite3").events()), 20)

    def test_preclose_backfill_and_corruption_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, signal = _make_bundle(root)
            with self.assertRaises(LiveDataError):
                prepare_forward_evidence(
                    inputs,
                    signal,
                    ledger_path=root / "ledger.sqlite3",
                    output_directory=root / "runs",
                    git_commit="4" * 40,
                    recorded_at=datetime(2026, 8, 31, 19, 59, tzinfo=timezone.utc),
                )
            prices_path = inputs / "daily_prices.csv"
            prices_path.write_text("corrupt", encoding="utf-8")
            with self.assertRaises(LiveDataError):
                prepare_forward_evidence(
                    inputs,
                    signal,
                    ledger_path=root / "ledger2.sqlite3",
                    output_directory=root / "runs2",
                    git_commit="4" * 40,
                    recorded_at=datetime(2026, 8, 31, 20, 5, tzinfo=timezone.utc),
                )


if __name__ == "__main__":
    unittest.main()
