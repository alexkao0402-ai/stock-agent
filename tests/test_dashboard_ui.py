import unittest

import pandas as pd

from src.dashboard_ui import latest_curve_date, selection_rows


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


if __name__ == "__main__":
    unittest.main()
