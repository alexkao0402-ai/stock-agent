import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from src.dashboard_cloud_snapshot import (
    DashboardSnapshotError,
    create_signed_snapshot,
    load_signed_snapshot,
    load_supabase_snapshot,
    upload_supabase_snapshot,
    verify_signed_snapshot,
    write_signed_snapshot,
)


SECRET = "test-only-dashboard-signing-secret"


def _state():
    return {
        "frozen_version": "V12-FROZEN-2026-08-28",
        "events": [{
            "sequence": 1,
            "created_at": "2026-09-01T04:05:00+08:00",
            "portfolio_id": "V12_T1",
            "event_type": "SIGNAL",
            "ticker": None,
            "action": "TARGET",
            "data_asof": "2026-08-31T16:00:00-04:00",
            "payload": {"private_internal_detail": "must-not-export"},
            "content_hash": "must-not-export",
        }],
        "formal_forward_rows": 1,
        "curve": pd.DataFrame([
            {"date": "2026-09-01", "series": "V12", "value": 10000.0}
        ]),
        "portfolio_value": 10000.0,
        "cumulative_return": 0.0,
        "excess_vs_spy": 0.0,
        "excess_vs_qqq": 0.0,
        "max_drawdown": 0.0,
        "cash": 0.0,
        "holdings": [{"ticker": "AAPL", "shares": 10.0, "average_cost": 100.0, "target_weight": 1.0}],
        "latest_signal": {"payload": {"private": "must-not-export"}},
        "signal_date": "2026-08-31",
        "market_regime": "BULL",
        "v7_selected": ["AAPL"],
        "v8_selected": ["AAPL"],
        "agreement_count": 1,
        "target_weights": {"AAPL": 1.0},
        "execution_status": "已執行",
        "execution_date": "2026-09-01",
        "rolling_sharpe": None,
        "sharpe_deviation": None,
        "t1_return": 0.0,
        "t2_return": None,
        "t1_t2_spread": None,
        "health_status": "WATCH",
        "health_label": "觀察",
        "trading_blocked": False,
        "integrity_error": None,
        "warnings": ["樣本不足"],
        "last_data_asof": "2026-09-01T16:00:00-04:00",
    }


class DashboardCloudSnapshotTests(unittest.TestCase):
    def test_round_trip_is_signed_and_display_only(self):
        envelope = create_signed_snapshot(
            _state(), SECRET, generated_at="2026-09-02T00:00:00+00:00", source_commit="abc123"
        )
        serialized = json.dumps(envelope)
        self.assertNotIn("must-not-export", serialized)
        recovered = verify_signed_snapshot(envelope, SECRET)
        self.assertEqual(recovered["portfolio_value"], 10000.0)
        self.assertEqual(recovered["events"][0]["event_type"], "SIGNAL")
        self.assertEqual(recovered["curve"].iloc[0]["series"], "V12")
        self.assertEqual(recovered["latest_signal"], {"present": True})

    def test_tampering_and_wrong_secret_fail_closed(self):
        envelope = create_signed_snapshot(_state(), SECRET)
        envelope["payload"]["portfolio_value"] = 999999.0
        with self.assertRaisesRegex(DashboardSnapshotError, "signature mismatch"):
            verify_signed_snapshot(envelope, SECRET)
        valid = create_signed_snapshot(_state(), SECRET)
        with self.assertRaisesRegex(DashboardSnapshotError, "signature mismatch"):
            verify_signed_snapshot(valid, "wrong-secret")

    def test_atomic_file_round_trip_and_http_rejection(self):
        envelope = create_signed_snapshot(_state(), SECRET)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dashboard.json"
            write_signed_snapshot(envelope, path)
            recovered = load_signed_snapshot(path, SECRET)
            self.assertEqual(recovered["signal_date"], "2026-08-31")
            self.assertFalse(path.with_suffix(".json.tmp").exists())
        with self.assertRaisesRegex(DashboardSnapshotError, "must use HTTPS"):
            load_signed_snapshot("http://example.com/dashboard.json", SECRET)

    def test_missing_secret_and_bad_ledger_state_are_rejected(self):
        with self.assertRaisesRegex(DashboardSnapshotError, "not configured"):
            create_signed_snapshot(_state(), "")
        state = _state()
        state["integrity_error"] = "ledger hash mismatch"
        with self.assertRaisesRegex(DashboardSnapshotError, "ledger errors"):
            create_signed_snapshot(state, SECRET)

    @patch("src.dashboard_cloud_snapshot.urlopen")
    def test_supabase_upload_is_private_explicit_and_display_only(self, open_url):
        response = MagicMock(status=200)
        open_url.return_value.__enter__.return_value = response
        envelope = create_signed_snapshot(_state(), SECRET)
        upload_supabase_snapshot(
            envelope,
            "https://project-ref.supabase.co",
            "sb_secret_test",
            bucket="v12-dashboard",
            object_path="snapshots/latest.json",
        )
        call = open_url.call_args
        request = call.args[0]
        self.assertEqual(
            request.full_url,
            "https://project-ref.supabase.co/storage/v1/object/"
            "v12-dashboard/snapshots/latest.json",
        )
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-upsert"], "true")
        self.assertEqual(headers["apikey"], "sb_secret_test")
        self.assertNotIn("authorization", headers)
        self.assertNotIn(b"must-not-export", request.data)

    @patch("src.dashboard_cloud_snapshot.urlopen")
    def test_supabase_download_verifies_signature(self, open_url):
        envelope = create_signed_snapshot(_state(), SECRET)
        response = MagicMock(status=200)
        response.read.return_value = json.dumps(envelope).encode("utf-8")
        open_url.return_value.__enter__.return_value = response
        state = load_supabase_snapshot(
            "https://project-ref.supabase.co",
            "sb_secret_test",
            SECRET,
        )
        self.assertEqual(state["signal_date"], "2026-08-31")
        request = open_url.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["apikey"], "sb_secret_test")
        self.assertNotIn("authorization", headers)

    def test_supabase_configuration_and_http_fail_closed_without_key_leak(self):
        envelope = create_signed_snapshot(_state(), SECRET)
        with self.assertRaisesRegex(DashboardSnapshotError, "valid HTTPS"):
            upload_supabase_snapshot(envelope, "http://unsafe.example", "private-key")
        with self.assertRaisesRegex(DashboardSnapshotError, "not configured"):
            upload_supabase_snapshot(envelope, "https://project.supabase.co", "")
        with self.assertRaisesRegex(DashboardSnapshotError, "unsigned"):
            upload_supabase_snapshot({}, "https://project.supabase.co", "private-key")

    @patch("src.dashboard_cloud_snapshot.urlopen")
    def test_supabase_http_error_does_not_echo_credentials(self, open_url):
        response = MagicMock(status=403)
        open_url.return_value.__enter__.return_value = response
        with self.assertRaises(DashboardSnapshotError) as caught:
            load_supabase_snapshot(
                "https://project.supabase.co",
                "never-echo-this-key",
                SECRET,
            )
        self.assertNotIn("never-echo-this-key", str(caught.exception))
        self.assertIn("HTTP 403", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
