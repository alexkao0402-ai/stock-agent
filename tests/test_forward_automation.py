from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, patch

from scripts.run_v12_forward_automation import run_cycle


CONFIG = {
    "project_url": "https://project.supabase.co",
    "api_key": "sb_secret_test",
    "secret": "long-test-secret",
    "bucket": "v12-dashboard",
}


class ForwardAutomationTests(unittest.TestCase):
    @patch("scripts.run_v12_forward_automation._publish_dashboard")
    @patch("scripts.run_v12_forward_automation.is_session", return_value=False)
    @patch("scripts.run_v12_forward_automation.download_forward_state", return_value="RESTORED")
    @patch("scripts.run_v12_forward_automation._commit", return_value="abc")
    @patch("scripts.run_v12_forward_automation._cloud_configuration", return_value=CONFIG)
    def test_non_session_restores_and_publishes_without_trading(
        self, config, commit, download, is_session, publish
    ):
        result = run_cycle(now=datetime(2026, 9, 5, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "SKIPPED_NON_SESSION")
        download.assert_called_once()
        publish.assert_called_once()

    @patch("scripts.run_v12_forward_automation._publish_dashboard")
    @patch("scripts.run_v12_forward_automation._persist_forward_state")
    @patch("scripts.run_v12_forward_automation.record_daily_valuations")
    @patch("scripts.run_v12_forward_automation.execute_due_portfolios")
    @patch("scripts.run_v12_forward_automation.AppendOnlyLedger")
    @patch("scripts.run_v12_forward_automation.is_month_end_session", return_value=False)
    @patch("scripts.run_v12_forward_automation.is_session", return_value=True)
    @patch("scripts.run_v12_forward_automation.download_forward_state", return_value="RESTORED")
    @patch("scripts.run_v12_forward_automation._commit", return_value="abc")
    @patch("scripts.run_v12_forward_automation._cloud_configuration", return_value=CONFIG)
    def test_completed_cycle_persists_each_mutating_phase(
        self, config, commit, download, is_session, month_end, ledger_class,
        execute, value, persist, publish,
    ):
        ledger = MagicMock()
        ledger_class.return_value = ledger
        execute.return_value = [{"portfolio_id": "V12_T1"}]
        value.return_value = [{"portfolio_id": "V12_T1"}]
        result = run_cycle(now=datetime(2026, 9, 3, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["executed_portfolios"], ["V12_T1"])
        self.assertEqual(result["valued_portfolios"], ["V12_T1"])
        self.assertEqual(persist.call_count, 2)
        ledger.verify_integrity.assert_called_once()
        publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
