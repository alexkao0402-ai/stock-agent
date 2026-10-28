import unittest

import pandas as pd

from src.backtest_engine import BacktestConfig
from src.candidate_strategies import bollinger_mean_reversion_variant, donchian_breakout, pead_availability
from src.portfolio_backtest import run_signal_portfolio


class CandidateStrategyTests(unittest.TestCase):
    def test_donchian_uses_prior_high_not_current_high(self):
        rows = []
        for i in range(56):
            rows.append({"date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i), "open": 10,
                         "high": 10 if i < 55 else 12, "low": 9, "close": 10 if i < 55 else 11,
                         "volume": 1})
        out = donchian_breakout(pd.DataFrame(rows))
        self.assertTrue(out.iloc[-1]["entry_signal"])

    def test_portfolio_executes_next_open_and_caps_positions(self):
        dates = pd.date_range("2026-01-01", periods=3)
        prepared = {}
        for n, symbol in enumerate(("A", "B", "C")):
            prepared[symbol] = pd.DataFrame({"date": dates, "open": [10+n, 20+n, 30+n],
                "close": [10+n, 20+n, 30+n], "entry_signal": [True, False, False],
                "exit_signal": [False, False, False], "score": [3-n, 0, 0]})
        result = run_signal_portfolio(prepared, "Test", BacktestConfig(1000, 0, 0), max_positions=2)
        buys = [t for t in result["trades"] if t["action"] == "BUY"]
        self.assertEqual(len(buys), 2)
        self.assertTrue(all(t["execution_date"] == dates[1] for t in buys))

    def test_pead_is_rejected_without_point_in_time_fields(self):
        status = pead_availability(None)
        self.assertFalse(status["comparable"])
        self.assertIn("released_at", status["missing_fields"])

    def test_bollinger_filters_are_entry_only(self):
        dates = pd.date_range("2020-01-01", periods=202)
        stock = pd.DataFrame({"date": dates, "open": 100.0, "high": 101.0, "low": 99.0,
                              "close": [100.0] * 200 + [80.0, 105.0], "volume": 1})
        spy = pd.DataFrame({"date": dates, "open": 100.0, "high": 101.0, "low": 99.0,
                            "close": [100.0] * 202, "volume": 1})
        out = bollinger_mean_reversion_variant(stock, spy, False, False, True)
        self.assertTrue(out.iloc[200]["entry_signal"])
        self.assertTrue(out.iloc[201]["exit_signal"])


if __name__ == "__main__":
    unittest.main()
