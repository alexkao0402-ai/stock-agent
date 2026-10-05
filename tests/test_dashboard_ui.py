import unittest

import pandas as pd

from src.dashboard_ui import (
    activity_event_rows,
    latest_curve_date,
    selection_rows,
    trade_activity_rows,
)


class DashboardUiFallbackTests(unittest.TestCase):
    def test_old_snapshot_reconstructs_selection_explanations(self):
        state = {
            "target_weights": {"GOOGL": 0.25, "MU": 0.50, "NVDA": 0.25},
            "v7_selected": ["GOOGL", "MU"],
            "v8_selected": ["MU", "NVDA"],
        }

        rows = selection_rows(state)

        self.assertEqual([row["ticker"] for row in rows], ["MU", "GOOGL", "NVDA"])
        self.assertEqual(rows[0]["support"], "V7 + V8")
        self.assertEqual(rows[1]["support"], "V7")
        self.assertEqual(rows[2]["support"], "V8")

    def test_explicit_rows_and_valuation_date_take_priority(self):
        explicit = [{"ticker": "MU", "target_weight": 0.5}]
        state = {
            "selection_explanations": explicit,
            "latest_valuation_date": "2026-10-03",
            "curve": pd.DataFrame({"date": ["2026-10-02"]}),
        }

        self.assertEqual(selection_rows(state), explicit)
        self.assertEqual(latest_curve_date(state), "2026-10-03")

    def test_curve_supplies_missing_valuation_date(self):
        state = {
            "curve": pd.DataFrame(
                {"date": pd.to_datetime(["2026-10-01", "2026-10-02"])}
            )
        }

        self.assertEqual(latest_curve_date(state), "2026-10-02")

    def test_activity_events_are_newest_first_and_display_only(self):
        state = {
            "events": [
                {
                    "created_at": "2026-09-30T20:00:00Z",
                    "portfolio_id": "V12_T1",
                    "event_type": "SIGNAL",
                    "ticker": None,
                    "action": None,
                    "data_asof": "2026-09-30",
                },
                {
                    "created_at": "2026-10-01T13:30:00Z",
                    "portfolio_id": "V12_T1",
                    "event_type": "FILL",
                    "ticker": "NVDA",
                    "action": "BUY",
                    "data_asof": "2026-10-01",
                },
            ]
        }

        rows = activity_event_rows(state)

        self.assertEqual(rows[0]["Event"], "FILL")
        self.assertEqual(rows[0]["Ticker"], "NVDA")
        self.assertEqual(rows[1]["Ticker"], "—")
        self.assertNotIn("payload", rows[0])

    def test_trade_activity_formats_trim_without_changing_source(self):
        trade = {
            "action": "SELL",
            "ticker": "MU",
            "shares": 0.2395,
            "fill_price": 1053.55,
            "trade_value": 252.29,
            "realized_pnl": 26.33,
            "target_weight": 0.5,
            "is_trim": True,
            "reason": "Trimmed to 50% target",
        }

        rows = trade_activity_rows([trade])

        self.assertEqual(rows[0]["Action"], "SELL · TRIM")
        self.assertEqual(rows[0]["Shares"], "0.2395")
        self.assertEqual(rows[0]["Target"], "50%")
        self.assertEqual(trade["action"], "SELL")


if __name__ == "__main__":
    unittest.main()
