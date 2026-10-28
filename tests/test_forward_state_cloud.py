from pathlib import Path
from io import BytesIO
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from src.forward_state_cloud import (
    ForwardStateError,
    _load_remote_bundle,
    create_forward_state_bundle,
    restore_forward_state_bundle,
    verify_forward_state_bundle,
)
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id


SECRET = "forward-state-test-secret-with-at-least-32-characters"


def _make_state(root: Path, event_name: str = "INITIALIZE") -> AppendOnlyLedger:
    ledger = AppendOnlyLedger(root / "paper_ledger" / "v12_events.sqlite3")
    ledger.append_batch([LedgerEvent(
        event_id=deterministic_event_id("test", event_name),
        portfolio_id="V12_T1",
        event_type=event_name,
        strategy_version="V12-FROZEN-2026-08-28",
        signal_timestamp="2026-08-31T16:00:00-04:00",
        execution_rule="T+1_OPEN",
        data_asof="2026-08-31T16:00:00-04:00",
        reason="fixture",
        payload={"initial_capital": 10_000.0},
        created_at="2026-08-31T20:00:00+00:00",
    )])
    evidence = root / "live_forward_runs" / "2026-08-31" / "manifest.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text('{"classification":"FORWARD"}\n', encoding="utf-8")
    return ledger


class ForwardStateCloudTests(unittest.TestCase):
    @patch("src.forward_state_cloud.urlopen")
    def test_supabase_no_such_key_response_is_treated_as_missing(self, open_url):
        open_url.side_effect = HTTPError(
            "https://project.supabase.co/object", 400, "bad request", {},
            BytesIO(b'{"statusCode":"404","code":"NoSuchKey"}'),
        )
        self.assertIsNone(_load_remote_bundle(
            "https://project.supabase.co", "sb_secret_test",
            bucket="v12-dashboard", object_path="forward/state.json", timeout=5,
        ))

    def test_signed_bundle_round_trip_restores_ledger_and_evidence(self):
        with tempfile.TemporaryDirectory() as source_temp, tempfile.TemporaryDirectory() as target_temp:
            source = Path(source_temp)
            target = Path(target_temp)
            _make_state(source)
            bundle = create_forward_state_bundle(
                source, SECRET, generated_at="2026-09-03T00:00:00+00:00", source_commit="abc"
            )
            verify_forward_state_bundle(bundle, SECRET)
            status = restore_forward_state_bundle(bundle, target, SECRET)
            self.assertEqual(status, "RESTORED")
            ledger = AppendOnlyLedger(target / "paper_ledger" / "v12_events.sqlite3")
            self.assertTrue(ledger.verify_integrity())
            self.assertEqual(len(ledger.events()), 1)
            self.assertTrue(
                (target / "live_forward_runs" / "2026-08-31" / "manifest.json").is_file()
            )

    def test_tampering_and_wrong_secret_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _make_state(root)
            bundle = create_forward_state_bundle(root, SECRET)
            changed = dict(bundle)
            changed["ledger_event_count"] = 999
            with self.assertRaisesRegex(ForwardStateError, "signature"):
                verify_forward_state_bundle(changed, SECRET)
            with self.assertRaisesRegex(ForwardStateError, "signature"):
                verify_forward_state_bundle(bundle, "wrong-secret")

    def test_divergent_local_ledger_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as remote_temp, tempfile.TemporaryDirectory() as local_temp:
            remote = Path(remote_temp)
            local = Path(local_temp)
            _make_state(remote, "REMOTE")
            _make_state(local, "LOCAL")
            bundle = create_forward_state_bundle(remote, SECRET)
            with self.assertRaisesRegex(ForwardStateError, "diverged"):
                restore_forward_state_bundle(bundle, local, SECRET)
            events = AppendOnlyLedger(local / "paper_ledger" / "v12_events.sqlite3").events()
            self.assertEqual(events[0]["event_type"], "LOCAL")


if __name__ == "__main__":
    unittest.main()
