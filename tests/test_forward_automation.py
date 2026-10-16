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
    def test_recovery_is_valuation_only_and_persisted_before_current_day(self):
        with patch('scripts.run_v12_forward_automation._cloud_configuration', return_value=CONFIG), \
             patch('scripts.run_v12_forward_automation._commit',return_value='abc'), \
             patch('scripts.run_v12_forward_automation.download_forward_state'), \
             patch('scripts.run_v12_forward_automation.AppendOnlyLedger') as ledger, \
             patch('scripts.run_v12_forward_automation.pending_valuation_dates',return_value=['2026-10-14','2026-10-15']), \
             patch('scripts.run_v12_forward_automation.record_daily_valuations',return_value=[{'portfolio_id':'V12_T1'}]) as value, \
             patch('scripts.run_v12_forward_automation.execute_due_portfolios',return_value=[]) as execute, \
             patch('scripts.run_v12_forward_automation._persist_forward_state') as persist, \
             patch('scripts.run_v12_forward_automation._publish_dashboard') as publish:
            ledger.return_value.events.return_value=[]
            result=run_cycle(now=datetime(2026,10,16,1,tzinfo=timezone.utc))
            self.assertEqual([c.kwargs['valuation_date'] for c in value.call_args_list], ['2026-10-14','2026-10-15'])
            self.assertEqual(execute.call_count,1)
            self.assertEqual(execute.call_args.kwargs['execution_date'],'2026-10-15')
            self.assertEqual(persist.call_count,2)
            self.assertEqual(result['recovered_valuation_dates'],['2026-10-14'])
            publish.assert_called_once()

    def test_recovery_failure_does_not_execute_or_publish(self):
        with patch('scripts.run_v12_forward_automation._cloud_configuration', return_value=CONFIG), \
             patch('scripts.run_v12_forward_automation._commit',return_value='abc'), \
             patch('scripts.run_v12_forward_automation.download_forward_state'), \
             patch('scripts.run_v12_forward_automation.AppendOnlyLedger') as ledger, \
             patch('scripts.run_v12_forward_automation.pending_valuation_dates',return_value=['2026-10-14','2026-10-15']), \
             patch('scripts.run_v12_forward_automation.record_daily_valuations',side_effect=RuntimeError('corporate action')), \
             patch('scripts.run_v12_forward_automation.execute_due_portfolios') as execute, \
             patch('scripts.run_v12_forward_automation._persist_forward_state') as persist, \
             patch('scripts.run_v12_forward_automation._publish_dashboard') as publish:
            ledger.return_value.events.return_value=[]
            with self.assertRaisesRegex(RuntimeError,'corporate action'):
                run_cycle(now=datetime(2026,10,16,1,tzinfo=timezone.utc))
            execute.assert_not_called(); persist.assert_not_called(); publish.assert_not_called()

    @patch("scripts.run_v12_forward_automation.subprocess.run")
    @patch("scripts.run_v12_forward_automation.AppendOnlyLedger")
    @patch("scripts.run_v12_forward_automation.is_month_end_session", return_value=True)
    @patch("scripts.run_v12_forward_automation.is_session", return_value=True)
    @patch("scripts.run_v12_forward_automation.download_forward_state", return_value="RESTORED")
    @patch("scripts.run_v12_forward_automation._commit", return_value="abc")
    @patch("scripts.run_v12_forward_automation._cloud_configuration", return_value=CONFIG)
    def test_month_end_capture_runs_as_module_and_reports_stderr(
        self, config, commit, download, is_session, month_end, ledger_class, run,
    ):
        run.return_value = MagicMock(returncode=1, stdout="", stderr="module import failed")
        with self.assertRaisesRegex(RuntimeError, "module import failed"):
            run_cycle(now=datetime(2026, 10, 1, 2, 16, tzinfo=timezone.utc))
        command = run.call_args.args[0]
        self.assertEqual(command[1:], ["-m", "scripts.capture_v12_live_inputs"])

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
