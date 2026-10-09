import unittest

import pandas as pd

from src.strategy_lab import _conditional_metrics, _regime_calendar, research_verdict, strategy_summary


class StrategyLabTests(unittest.TestCase):
    def test_regime_uses_only_trailing_200_closes(self):
        spy = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=202), "close": [100.0] * 200 + [101.0, 99.0]})
        regimes = _regime_calendar(spy)
        self.assertTrue(regimes["Market Regime"].iloc[:199].isna().all())
        self.assertEqual(regimes.iloc[200]["Market Regime"], "Bull")
        self.assertEqual(regimes.iloc[201]["Market Regime"], "Bear")

    def test_conditional_metrics_separate_daily_sample_and_completed_trades(self):
        dates = pd.date_range("2020-01-01", periods=6)
        curve = pd.DataFrame({"date": dates, "equity": [100, 101, 102, 101, 103, 104], "position": [0, 1, 1, 0, 1, 0]})
        result = {
            "equity_curve": curve,
            "trades": [
                {"action": "BUY", "signal_date": dates[0], "execution_price": 10, "shares": 10, "transaction_cost": 0},
                {"action": "SELL", "signal_date": dates[2], "execution_price": 11, "shares": 10, "transaction_cost": 0},
            ],
        }
        benchmark = {"equity_curve": pd.DataFrame({"date": dates, "equity": [100, 100, 101, 101, 102, 102], "position": 1})}
        calendar = pd.DataFrame({"date": dates, "Market Regime": ["Bull", "Bull", "Bear", "Bear", "Bull", "Bull"]})
        row = _conditional_metrics(result, benchmark, benchmark, calendar, "Full History", "Bull")
        self.assertEqual(row["Sample Size"], 3)  # first pct-change row onward
        self.assertEqual(row["Trades"], 1)
        self.assertEqual(row["Win Rate %"], 100)

    def test_summary_uses_cross_stock_median_and_beat_rate(self):
        matrix = pd.DataFrame([
            {"Stock": "A", "Strategy": "Momentum", "Alpha vs B&H %": 10, "Alpha vs SPY %": 8, "Sharpe": 1.2, "Max Drawdown %": -10, "OOS Alpha vs B&H %": 4},
            {"Stock": "B", "Strategy": "Momentum", "Alpha vs B&H %": 2, "Alpha vs SPY %": 3, "Sharpe": 1.0, "Max Drawdown %": -12, "OOS Alpha vs B&H %": 1},
            {"Stock": "C", "Strategy": "Momentum", "Alpha vs B&H %": -1, "Alpha vs SPY %": 1, "Sharpe": .8, "Max Drawdown %": -14, "OOS Alpha vs B&H %": -1},
        ])
        summary = strategy_summary(matrix).iloc[0]
        self.assertEqual(summary["Beat B&H"], 2)
        self.assertAlmostEqual(summary["Beat B&H %"], 200 / 3)
        self.assertEqual(summary["Median Alpha vs B&H %"], 2)

    def test_keep_requires_majority_full_history_and_positive_oos_median(self):
        summary = pd.DataFrame([{
            "Strategy": "Momentum", "Stocks Tested": 10, "Beat B&H": 6, "Beat B&H %": 60,
            "Median Alpha vs B&H %": 2, "Average Alpha vs B&H %": 3,
            "Median Alpha vs SPY %": 4, "Median Sharpe": 1.1, "Median Max Drawdown %": -12,
            "OOS Stocks Available": 10, "OOS Beat B&H %": 60, "Median OOS Alpha vs B&H %": 1,
        }])
        self.assertEqual(research_verdict(summary).iloc[0]["Research Verdict"], "KEEP")

    def test_negative_full_and_oos_is_kill(self):
        summary = pd.DataFrame([{
            "Strategy": "Pullback", "Stocks Tested": 10, "Beat B&H": 2, "Beat B&H %": 20,
            "Median Alpha vs B&H %": -4, "Average Alpha vs B&H %": -3,
            "Median Alpha vs SPY %": 1, "Median Sharpe": .5, "Median Max Drawdown %": -10,
            "OOS Stocks Available": 10, "OOS Beat B&H %": 20, "Median OOS Alpha vs B&H %": -2,
        }])
        self.assertEqual(research_verdict(summary).iloc[0]["Research Verdict"], "KILL")

    def test_mixed_evidence_is_not_forced_to_keep_or_kill(self):
        summary = pd.DataFrame([{
            "Strategy": "Momentum", "Stocks Tested": 10, "Beat B&H": 7, "Beat B&H %": 70,
            "Median Alpha vs B&H %": 3, "Average Alpha vs B&H %": 5,
            "Median Alpha vs SPY %": 6, "Median Sharpe": 1.2, "Median Max Drawdown %": -15,
            "OOS Stocks Available": 10, "OOS Beat B&H %": 30, "Median OOS Alpha vs B&H %": -1,
        }])
        self.assertEqual(research_verdict(summary).iloc[0]["Research Verdict"], "MORE EVIDENCE")


if __name__ == "__main__":
    unittest.main()
