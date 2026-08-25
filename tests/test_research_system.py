import unittest

import pandas as pd

from src.backtest_engine import BacktestConfig, run_backtest
from src.indicators import add_moving_averages, add_relative_strength
from src.performance import calculate_metrics, completed_round_trips
from src.strategies.mean_reversion import mean_reversion_signals
from src.strategies.trend import trend_following_signals


def frame(size=220, start="2020-01-01", price=100.0):
    dates = pd.bdate_range(start, periods=size).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": dates,
        "open": [price + i * 0.1 for i in range(size)],
        "high": [price + i * 0.1 + 1 for i in range(size)],
        "low": [price + i * 0.1 - 1 for i in range(size)],
        "close": [price + i * 0.1 for i in range(size)],
        "volume": [1_000] * size,
    })


class ResearchSystemTests(unittest.TestCase):
    def test_indicators_do_not_change_when_future_row_is_appended(self):
        original = frame(220)
        before = add_moving_averages(original)
        future = original.iloc[[-1]].copy()
        future["date"] = "2030-01-01"
        future[["open", "high", "low", "close"]] = 1_000_000
        after = add_moving_averages(pd.concat([original, future], ignore_index=True))
        pd.testing.assert_series_equal(before["ma200"], after.iloc[:-1]["ma200"], check_names=False)

    def test_signal_executes_at_next_open_and_records_both_dates(self):
        data = frame(3)
        data["entry_signal"] = [True, False, False]
        data["exit_signal"] = False
        result = run_backtest(data, "TEST", "Test", BacktestConfig(slippage_rate=0, commission_rate=0))
        trade = result["trades"][0]
        self.assertEqual(trade["signal_date"], data.loc[0, "date"])
        self.assertEqual(trade["execution_date"], data.loc[1, "date"])
        self.assertEqual(trade["execution_price"], data.loc[1, "open"])

    def test_last_day_signal_cannot_execute(self):
        data = frame(2)
        data["entry_signal"] = [False, True]
        data["exit_signal"] = False
        self.assertEqual(run_backtest(data, "TEST", "Test")["trades"], [])

    def test_benchmark_alignment_uses_common_dates(self):
        stock = frame(140)
        benchmark = frame(140).drop(index=[5, 10]).reset_index(drop=True)
        aligned = add_relative_strength(stock, benchmark, periods=5)
        self.assertEqual(len(aligned), 138)
        self.assertNotIn(stock.loc[5, "date"], set(aligned["date"]))

    def test_buy_costs_apply_once(self):
        data = frame(2, price=100)
        data["entry_signal"] = [True, False]
        data["exit_signal"] = False
        config = BacktestConfig(initial_capital=10_000, commission_rate=0.001, slippage_rate=0.0005)
        result = run_backtest(data, "TEST", "Test", config)
        trade = result["trades"][0]
        expected_price = data.loc[1, "open"] * 1.0005
        expected_shares = 10_000 / (expected_price * 1.001)
        self.assertAlmostEqual(trade["execution_price"], expected_price)
        self.assertAlmostEqual(trade["shares"], expected_shares)
        self.assertAlmostEqual(trade["transaction_cost"], expected_shares * expected_price * 0.001)

    def test_open_position_is_not_a_completed_trade(self):
        data = frame(3)
        data["entry_signal"] = [True, False, False]
        data["exit_signal"] = False
        result = run_backtest(data, "TEST", "Test", BacktestConfig(slippage_rate=0, commission_rate=0))
        self.assertEqual(completed_round_trips(result["trades"]), [])
        self.assertEqual(calculate_metrics(result)["Trades"], 0)
        self.assertTrue(result["open_position"])

    def test_ma200_warmup_prevents_trades(self):
        signals = trend_following_signals(frame(199))
        self.assertFalse(signals["entry_signal"].any())
        self.assertFalse(signals["exit_signal"].any())

    def test_mean_reversion_max_holding_signal_executes_next_open(self):
        data = frame(230)
        # A sharp but still above-MA200 pullback creates an oversold entry.
        data.loc[210:, "close"] = [118 - i * 0.3 for i in range(20)]
        data.loc[210:, "open"] = data.loc[210:, "close"]
        signals = mean_reversion_signals(data, max_holding_days=2)
        entry_indexes = signals.index[signals["entry_signal"]].tolist()
        self.assertTrue(entry_indexes)
        entry_i = entry_indexes[0]
        exit_indexes = signals.index[(signals.index > entry_i) & signals["exit_signal"]].tolist()
        self.assertTrue(exit_indexes)
        exit_i = exit_indexes[0]
        self.assertGreaterEqual(exit_i, entry_i + 2)
        result = run_backtest(signals, "TEST", "Mean Reversion", BacktestConfig(slippage_rate=0, commission_rate=0))
        sell = next(t for t in result["trades"] if t["action"] == "SELL")
        self.assertEqual(sell["signal_date"], signals.loc[exit_i, "date"])
        self.assertEqual(sell["execution_date"], signals.loc[exit_i + 1, "date"])


if __name__ == "__main__":
    unittest.main()
