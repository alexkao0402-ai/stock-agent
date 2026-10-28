from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import Mock, patch

from src.e3_dashboard import freshness
from src.e3_dashboard_snapshot import E3DisplayError, OBJECT_PATH, create_envelope, load_display, publish_display, verify_envelope

NOW = datetime(2026, 10, 27, 6, 40, tzinfo=timezone.utc)
KEY = "synthetic-signing-key-not-a-real-secret"


def fixture():
    return {"version": "F1-E3-PAPER-V1", "paper_only": True, "ledger_integrity": True,
            "forward_sessions": 0, "primary_fill_count": 0, "ledger_events": 2,
            "status": "ARMED_WAITING_FIRST_FORWARD_CLOSE", "frozen_at": "2026-10-27T06:26:06+00:00",
            "first_signal_session": "2026-10-27", "first_possible_fill_session": "2026-10-28",
            "freeze_sha256": "a" * 64, "last_close": None, "pending": None,
            "rules": {"universe": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]},
            "curve": [], "trades": [], "accounts": {name: {"cash": 10000.0, "equity": 10000.0,
                 "dividend_receivable": 0, "positions": {}, "return_pct": None} for name in ("E3", "CSM", "SPY", "EW")}}


class E3DisplayTests(unittest.TestCase):
    def test_signed_round_trip_preserves_zero_forward_observations(self):
        original = fixture()
        signed = create_envelope(original, KEY, NOW.isoformat())
        view = verify_envelope(signed, KEY, NOW)
        self.assertEqual(view["accounts"]["E3"]["cash"], 10000)
        self.assertIsNone(view["accounts"]["E3"]["return_pct"])
        self.assertEqual(original["curve"], [])

    def test_modified_payload_wrong_key_and_wrong_schema_rejected(self):
        signed = create_envelope(fixture(), KEY, NOW.isoformat())
        bad = deepcopy(signed)
        bad["payload"]["accounts"]["E3"]["cash"] = 99999
        for envelope, key in ((bad, KEY), (signed, "wrong"), ({"schema_version": 1}, KEY)):
            with self.assertRaises(E3DisplayError):
                verify_envelope(envelope, key, NOW)

    def test_cannot_present_startup_as_performance(self):
        for change in ("trades", "curve", "return"):
            item = fixture()
            if change == "return":
                item["accounts"]["E3"]["return_pct"] = 42
            else:
                item[change] = [{"fabricated": True}]
            with self.assertRaises(E3DisplayError):
                create_envelope(item, KEY)

    def test_export_requires_verified_ledger_and_full_universe(self):
        for field in ("ledger_integrity", "universe"):
            item = fixture()
            if field == "universe":
                item["rules"]["universe"] = ["NVDA"]
            else:
                item[field] = False
            with self.assertRaises(E3DisplayError):
                create_envelope(item, KEY)

    def test_uploader_can_only_target_the_separate_e3_object(self):
        signed = create_envelope(fixture(), KEY)
        with patch("src.e3_dashboard_snapshot.upload_supabase_snapshot") as upload:
            publish_display(signed, "https://test.supabase.co", "test-key")
            self.assertEqual(upload.call_args.kwargs["object_path"], OBJECT_PATH)
            self.assertNotEqual(upload.call_args.kwargs["object_path"], "v12_dashboard.json")

    def test_failed_load_does_not_expose_keys_or_substitute_v12(self):
        with patch("src.e3_dashboard_snapshot.urlopen", side_effect=RuntimeError("hidden-sensitive-value")):
            with self.assertRaises(E3DisplayError) as caught:
                load_display("https://test.supabase.co", "hidden-sensitive-value", KEY)
        self.assertNotIn("hidden-sensitive-value", str(caught.exception))

    def test_missing_session_warns_even_after_new_publication(self):
        view = verify_envelope(create_envelope(fixture(), KEY, NOW.isoformat()), KEY, NOW)
        self.assertIsNone(freshness(view, NOW))
        later = datetime(2026, 10, 27, 21, tzinfo=timezone.utc)
        view["published_at"] = later.isoformat()
        self.assertIn("completed market session", freshness(view, later))

    def test_future_publication_is_rejected(self):
        signed = create_envelope(fixture(), KEY, "2026-10-28T06:40:00+00:00")
        with self.assertRaises(E3DisplayError):
            verify_envelope(signed, KEY, NOW)


class E3PageTests(unittest.TestCase):
    def test_startup_page_has_no_synthetic_chart_or_returns(self):
        from streamlit.testing.v1 import AppTest
        view = verify_envelope(create_envelope(fixture(), KEY, NOW.isoformat()), KEY, NOW)
        with patch("src.e3_dashboard.load_display", return_value=view):
            app = AppTest.from_string("from src.e3_dashboard import render_e3_dashboard\nrender_e3_dashboard()").run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([metric.value for metric in app.metric[:4]], ["$10,000.00", "$10,000.00", "0", "0"])
        self.assertEqual(len(app.get("plotly_chart")), 0)
        self.assertTrue(any("No forward trades or performance" in item.value for item in app.info))


if __name__ == "__main__":
    unittest.main()
