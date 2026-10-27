from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.dashboard_read_model import build_dashboard_snapshot
from src.e3_dashboard_snapshot import E3DisplayError, build_local_projection, create_envelope, verify_envelope
from src.e3_forward import initialize, close_cycle
from src.strategy_page_model import e3_model, v12_model
from tests.test_e3_dashboard import fixture, NOW, KEY
from tests.test_e3_forward import FREEZE, snapshot


def startup_view():
    return verify_envelope(create_envelope(fixture(), KEY, NOW.isoformat()), KEY, NOW)


def v12_view():
    state = build_dashboard_snapshot(Path("__nonexistent_test_ledger__.sqlite3"))
    state.update(portfolio_value=9474.03, cash=0.0, cumulative_return=-0.052597,
                 formal_forward_rows=2, integrity_error=None, ledger_verified=True,
                 snapshot_generated_at=NOW.isoformat(), latest_valuation_date="2026-10-26",
                 curve=pd.DataFrame([{"date": "2026-10-23", "series": "V12", "value": 9600},
                                     {"date": "2026-10-26", "series": "V12", "value": 9474.03}]))
    return state


class E3DetailProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        initialize(self.home, FREEZE)

    def tearDown(self):
        self.temp.cleanup()

    def day(self, day, **kwargs):
        data = snapshot(day, **kwargs)
        return close_cycle(self.home, data, data["observed_at"])

    def test_saved_fill_accounting_and_marks_reconcile_without_writes(self):
        self.day("2026-10-27")
        self.day("2026-10-28")
        self.day("2026-10-29", dividend=0.5)
        paths = [self.home / "events.sqlite3", self.home / "freeze.json"]
        before = [p.read_bytes() for p in paths]
        view = build_local_projection(self.home)
        d = view["details"]
        self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertEqual(len(d["transactions"]), 1)
        self.assertEqual(len(d["signal_history"]), 3)
        self.assertEqual(len(d["signal_history"][-1]["stocks"]), 10)
        holding = d["holdings"][0]
        fill = d["transactions"][0]
        self.assertAlmostEqual(holding["average_cost"], fill["fill_price"] * 1.001)
        self.assertGreater(d["transaction_costs"], d["commissions"])
        self.assertGreater(view["accounts"]["E3"]["dividend_receivable"], 0)
        self.assertAlmostEqual(view["accounts"]["E3"]["equity"],
                               10000 + d["realized_pnl"] + d["unrealized_pnl"] + view["accounts"]["E3"]["dividend_receivable"])
        self.assertIsNone(d["rolling_sharpe"])
        self.assertIsNone(d["win_rate"])

    def test_split_keeps_basis_and_uses_captured_raw_mark(self):
        self.day("2026-10-27")
        self.day("2026-10-28")
        old = build_local_projection(self.home)["details"]["holdings"][0]
        data = snapshot("2026-10-29", split=2)
        for key in ("open", "high", "low", "close"):
            data["prices"]["AAPL"][-1][key] /= 2
        close_cycle(self.home, data, data["observed_at"])
        new = build_local_projection(self.home)["details"]["holdings"][0]
        self.assertAlmostEqual(new["shares"], old["shares"] * 2)
        self.assertAlmostEqual(new["average_cost"], old["average_cost"] / 2)
        self.assertEqual(new["mark"], data["prices"]["AAPL"][-1]["close"])

    def test_completed_trade_uses_both_sides_costs(self):
        from src.trading_calendar import next_session
        self.day("2026-10-27")
        day = "2026-10-28"
        for _ in range(10):
            self.day(day)
            day = next_session(day).isoformat()
        self.day(day)
        view = build_local_projection(self.home)
        d = view["details"]
        self.assertEqual(d["closed_trades"], 1)
        self.assertFalse(d["holdings"])
        buy, sell = d["transactions"]
        self.assertAlmostEqual(d["realized_pnl"], sell["trade_value"] - sell["fee"] - buy["trade_value"] - buy["fee"])
        self.assertAlmostEqual(d["realized_pnl"], view["accounts"]["E3"]["equity"] - 10000)

    def test_detail_counts_and_startup_performance_cannot_be_fabricated(self):
        view = build_local_projection(self.home)
        create_envelope(view, KEY, NOW.isoformat())
        bad = deepcopy(view)
        bad["details"]["transactions"] = [{"synthetic": True}]
        with self.assertRaises(E3DisplayError):
            create_envelope(bad, KEY, NOW.isoformat())
        bad = deepcopy(view)
        bad["details"]["max_drawdown"] = -0.2
        with self.assertRaises(E3DisplayError):
            create_envelope(bad, KEY, NOW.isoformat())


class PairedPageTests(unittest.TestCase):
    def render(self, page, e3=None):
        from streamlit.testing.v1 import AppTest
        # Patch the model boundary: synthetic test data never enters a cloud publication.
        with patch("src.strategy_pages.v12_model", return_value=v12_model(v12_view())), \
             patch("src.strategy_pages.e3_model", return_value=e3_model(startup_view()) if e3 is None else e3):
            return AppTest.from_string(
                "from src.strategy_pages import render_paired_page\n"
                f"render_paired_page({page!r}, {{}}, None)"
            ).run(timeout=25)

    def test_all_tracking_pages_have_both_strategy_columns_and_no_exceptions(self):
        from src.strategy_pages import SECTIONS
        for page, sections in SECTIONS.items():
            with self.subTest(page=page):
                app = self.render(page)
                self.assertEqual(len(app.exception), 0)
                labels = [m.value for m in app.markdown if 'class="paired-label' in m.value]
                self.assertEqual(len(labels), len(sections) * 2)
                self.assertTrue(all('>V12<' in labels[i] and '>E3<' in labels[i + 1] for i in range(0, len(labels), 2)))

    def test_startup_has_no_e3_chart_or_fake_metrics(self):
        app = self.render("overview")
        self.assertEqual(len(app.get("plotly_chart")), 1)  # V12 only
        returns = [m.value for m in app.metric if m.label == "Cumulative Return"]
        self.assertEqual(returns, ["-5.26%", "Waiting"])
        app = self.render("health")
        agreement = [m.value for m in app.metric if m.label == "V7 / V8 agreement"]
        self.assertEqual(agreement[-1], "Not applicable")

    def test_unavailable_e3_does_not_hide_or_copy_v12(self):
        app = self.render("overview", e3_model(None))
        self.assertEqual(len(app.exception), 0)
        self.assertIn("$9,474.03", [m.value for m in app.metric])
        self.assertNotIn("$10,000.00", [m.value for m in app.metric])
        self.assertTrue(any("E3 data unavailable" in e.value for e in app.error))

    def test_future_activity_has_independent_filters_and_saved_signal_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            initialize(home, FREEZE)
            for day in ("2026-10-27", "2026-10-28"):
                data = snapshot(day)
                close_cycle(home, data, data["observed_at"])
            view = build_local_projection(home)
            view["published_at"] = NOW.isoformat()
            app = self.render("activity", e3_model(view))
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(s.key == "E3_signal_session" for s in app.selectbox))
        self.assertTrue(any(s.key == "E3_side" for s in app.selectbox))
        self.assertGreater(len(app.dataframe), 2)

if __name__ == "__main__":
    unittest.main()
