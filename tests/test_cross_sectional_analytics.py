import unittest

import pandas as pd

from src.cross_sectional_analytics import monthly_return_matrix, realized_trade_ledger, rebalance_summary


class CrossSectionalAnalyticsTests(unittest.TestCase):
    def test_fifo_realized_pnl_includes_buy_and_sell_costs(self):
        trades = [
            {"symbol": "A", "action": "BUY", "execution_date": "2024-01-02", "execution_price": 10, "shares": 10, "transaction_cost": 1},
            {"symbol": "A", "action": "SELL", "execution_date": "2024-02-02", "execution_price": 12, "shares": 5, "transaction_cost": 0.6},
        ]
        ledger = realized_trade_ledger(trades)
        self.assertEqual(len(ledger), 1)
        self.assertAlmostEqual(ledger.iloc[0]["Net P&L"], 8.9)
        self.assertEqual(ledger.iloc[0]["Holding Days"], 31)

    def test_rebalance_summary_reports_cycle_pnl_without_next_execution_day(self):
        result = {
            "equity_curve": pd.DataFrame({
                "date": pd.date_range("2024-01-01", periods=5),
                "equity": [100, 101, 103, 102, 105],
            }),
            "trades": [],
            "rebalance_log": [
                {"signal_date": "2024-01-01", "execution_date": "2024-01-02", "market_regime": "Bull", "holdings_before": [], "holdings_after": ["A"], "bought": ["A"], "sold": [], "transaction_cost": 1, "turnover_notional": 100, "pretrade_value": 100, "rankings": []},
                {"signal_date": "2024-01-03", "execution_date": "2024-01-04", "market_regime": "Bull", "holdings_before": ["A"], "holdings_after": ["B"], "bought": ["B"], "sold": ["A"], "transaction_cost": 1, "turnover_notional": 200, "pretrade_value": 103, "rankings": []},
            ],
        }
        summary = rebalance_summary(result)
        self.assertAlmostEqual(summary.iloc[0]["Cycle P&L"], 2.0)
        self.assertEqual(summary.iloc[0]["Selected Holdings"], "A")

    def test_monthly_matrix_preserves_first_month_return_from_initial_capital(self):
        curve = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02", "2024-01-31", "2024-02-29"]),
            "equity": [100, 110, 121],
        })
        matrix = monthly_return_matrix(curve, 100)
        self.assertAlmostEqual(matrix.loc[2024, 1], 10.0)
        self.assertAlmostEqual(matrix.loc[2024, 2], 10.0)


if __name__ == "__main__":
    unittest.main()
