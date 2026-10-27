from copy import deepcopy
import unittest
from unittest.mock import patch

from src.strategy_overview import account_cards
from tests.test_e3_dashboard import fixture, KEY, NOW
from src.e3_dashboard_snapshot import create_envelope, verify_envelope, E3DisplayError


def v12_fixture():
    return {"integrity_error": None, "formal_forward_rows": 35, "portfolio_value": 9474.03,
            "cash": 2.5, "cumulative_return": -0.052597, "trading_blocked": False,
            "holdings": [{"ticker": "NVDA"}], "execution_status": "Executed",
            "next_signal_date": "2026-10-30", "latest_valuation_date": "2026-10-26",
            "snapshot_generated_at": NOW.isoformat()}


def e3_fixture():
    return verify_envelope(create_envelope(fixture(), KEY, NOW.isoformat()), KEY, NOW)


class StrategyOverviewTests(unittest.TestCase):
    def test_startup_values_and_returns_are_separate_without_mutation(self):
        v12, e3 = v12_fixture(), e3_fixture()
        before = deepcopy((v12, e3))
        old, new = account_cards(v12, e3)
        self.assertEqual((old["value"], old["return"]), ("$9,474.03", "-5.26%"))
        self.assertEqual((new["value"], new["return"]), ("$10,000.00", "Waiting"))
        self.assertIn("only if a stock qualifies", new["next"])
        self.assertEqual((v12, e3), before)

    def test_recorded_percent_units_and_pending_plan(self):
        e3 = e3_fixture()
        e3.update(forward_sessions=2, last_close="2026-10-28",
                  pending={"execution_date": "2026-10-29", "plans": {"E3": {"entries": ["WMT"], "exits": ["NVDA"]}}})
        e3["accounts"]["E3"].update(return_pct=1.23, equity=10123, positions={"NVDA": {"shares": 1}})
        new = account_cards(v12_fixture(), e3)[1]
        self.assertEqual(new["return"], "+1.23%")
        self.assertEqual(new["holdings"], "NVDA")
        self.assertIn("Buy WMT; Sell NVDA", new["next"])

    def test_bad_v12_data_and_missing_e3_never_show_substitute_balances(self):
        v12 = v12_fixture()
        v12["integrity_error"] = "test-error"
        cards = account_cards(v12)
        self.assertTrue(all(card["value"] == "Unavailable" for card in cards))
        self.assertTrue(all(card["return"] == "Unavailable" for card in cards))

    def test_overview_renders_both_accounts_and_escapes_snapshot_text(self):
        from streamlit.testing.v1 import AppTest
        v12 = v12_fixture()
        v12["holdings"][0]["ticker"] = '<script>bad</script>'
        with patch("src.strategy_overview.dashboard_view", return_value=e3_fixture()), \
             patch("src.strategy_overview.freshness", return_value=None), \
             patch("src.strategy_overview.account_cards", wraps=account_cards) as model:
            # The synthetic fixture is injected into the test script, never persisted as live data.
            app = AppTest.from_string(
                "from src.strategy_overview import render_strategy_overview\n"
                f"render_strategy_overview({v12!r})"
            ).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        content = "\n".join(item.value for item in app.markdown)
        self.assertIn('aria-label="V12 paper account"', content)
        self.assertIn('aria-label="E3 paper account"', content)
        self.assertIn("&lt;script&gt;", content)
        self.assertNotIn("<script>", content)
        self.assertIn("different times", app.info[0].value)
        self.assertEqual(model.call_count, 1)

    def test_e3_load_failure_preserves_v12(self):
        from streamlit.testing.v1 import AppTest
        with patch("src.strategy_overview.dashboard_view", side_effect=E3DisplayError("unavailable")):
            app = AppTest.from_string(
                "from src.strategy_overview import render_strategy_overview\n"
                f"render_strategy_overview({v12_fixture()!r})"
            ).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertIn("$9,474.03", "\n".join(item.value for item in app.markdown))
        self.assertIn("E3 data could not be verified", app.warning[0].value)


if __name__ == "__main__":
    unittest.main()
