import unittest
import json
import tempfile
from pathlib import Path

import pandas as pd

from src.ai_analysis import extract_structured_data
from src.backtest_engine import BacktestConfig, run_backtest
from src.cross_sectional import cross_sectional_momentum_backtest, equal_weight_buy_and_hold
from src.indicators import add_moving_averages, add_relative_strength
from src.prediction_tracker import enrich_prediction
from src.performance import calculate_metrics, completed_round_trips
from src.strategies.mean_reversion import mean_reversion_signals
from src.strategies.momentum import momentum_relative_strength_signals
from src.strategy_validation import fixed_horizon_validation, strategy_scorecard


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
    def test_embedded_json_avoids_second_ai_extraction(self):
        report = """<!--STRUCTURED_JSON
{"current_price": 100, "bull_low": 120, "bull_high": 130}
-->
# Report
"""
        result = extract_structured_data("TEST", 100, report)
        self.assertEqual(result["bull_low"], 120)
        self.assertEqual(result["bull_high"], 130)

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
        result = run_backtest(data, "TEST", "Test", BacktestConfig(slippage_pct=0, transaction_cost_pct=0))
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
        config = BacktestConfig(initial_capital=10_000, transaction_cost_pct=0.001, slippage_pct=0.0005)
        result = run_backtest(data, "TEST", "Test", config)
        trade = result["trades"][0]
        expected_price = data.loc[1, "open"] * 1.0005
        expected_shares = 10_000 / (expected_price * 1.001)
        self.assertAlmostEqual(trade["execution_price"], expected_price)
        self.assertAlmostEqual(trade["shares"], expected_shares)
        self.assertAlmostEqual(trade["transaction_cost"], expected_shares * expected_price * 0.001)

    def test_slippage_is_adverse_at_next_open(self):
        data = frame(2, price=100)
        data["entry_signal"] = [True, False]
        data["exit_signal"] = False
        result = run_backtest(data, "TEST", "Test", BacktestConfig(transaction_cost_pct=0, slippage_pct=0.0005))
        self.assertAlmostEqual(result["trades"][0]["execution_price"], data.loc[1, "open"] * 1.0005)

    def test_open_position_is_not_a_completed_trade(self):
        data = frame(3)
        data["entry_signal"] = [True, False, False]
        data["exit_signal"] = False
        result = run_backtest(data, "TEST", "Test", BacktestConfig(slippage_pct=0, transaction_cost_pct=0))
        self.assertEqual(completed_round_trips(result["trades"]), [])
        self.assertEqual(calculate_metrics(result)["Trades"], 0)
        self.assertTrue(result["open_position"])

    def test_ma200_warmup_prevents_trades(self):
        signals = mean_reversion_signals(frame(199))
        self.assertFalse(signals["entry_signal"].any())
        self.assertFalse(signals["exit_signal"].any())

    def test_rsi_warmup_prevents_pullback_trades(self):
        signals = mean_reversion_signals(frame(13))
        self.assertFalse(signals["entry_signal"].any())

    def test_momentum_warmup_prevents_trades(self):
        stock = frame(19)
        spy = frame(19)
        signals = momentum_relative_strength_signals(stock, spy)
        self.assertFalse(signals["entry_signal"].any())

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
        result = run_backtest(signals, "TEST", "Mean Reversion", BacktestConfig(slippage_pct=0, transaction_cost_pct=0))
        sell = next(t for t in result["trades"] if t["action"] == "sell")
        self.assertEqual(sell["signal_date"], signals.loc[exit_i, "date"])
        self.assertEqual(sell["execution_date"], signals.loc[exit_i + 1, "date"])

    def test_fixed_horizon_validation_uses_exact_future_trading_rows(self):
        stock = frame(10, price=100)
        spy = frame(10, price=200)
        equity = pd.DataFrame({"date": stock["date"], "equity": [10_000 + i * 100 for i in range(10)]})
        record = {"timestamp": stock.loc[2, "date"] + "T18:00:00", "strategy_signals": [{"strategy": "Momentum", "signal": "BUY"}]}
        result = {"strategy": "Test", "equity_curve": equity}
        validated = fixed_horizon_validation(record, stock, spy, [result], horizons=(5, 20))
        self.assertIn("5", validated)
        self.assertNotIn("20", validated)
        self.assertEqual(validated["5"]["end_date"], stock.loc[7, "date"])

    def test_scorecard_counts_only_matured_recorded_outcomes(self):
        records = [{"strategy_validation": {"20": {"strategies": {
            "Momentum": {"stock_return_pct": 5, "spy_return_pct": 3, "alpha_vs_spy_pct": 2, "beat_spy": True}
        }}}}]
        scorecard = strategy_scorecard(records, 20)
        self.assertEqual(scorecard.loc[0, "已驗證訊號"], 1)
        self.assertEqual(scorecard.loc[0, "勝過 SPY 比率 %"], 100)

    def test_cross_sectional_ranking_executes_on_next_open(self):
        prices = {}
        for rank, symbol in enumerate(["A", "B", "C", "D", "E"], start=1):
            item = frame(260, price=100)
            item[["open", "high", "low", "close"]] = item[["open", "high", "low", "close"]] * (1 + rank * pd.Series(range(260)) / 1000).to_numpy()[:, None]
            prices[symbol] = item
        spy = frame(260, price=100)
        result = cross_sectional_momentum_backtest(
            prices, spy, BacktestConfig(transaction_cost_pct=0, slippage_pct=0), top_fraction=.2
        )
        first_buy = next(trade for trade in result["trades"] if trade["action"] == "BUY")
        buy_date_i = list(prices["A"]["date"]).index(first_buy["date"])
        self.assertEqual(first_buy["symbol"], "E")
        self.assertEqual(buy_date_i, 200)

    def test_cross_sectional_ranking_no_future_data(self):
        prices = {symbol: frame(260, price=100 + rank) for rank, symbol in enumerate(["A", "B", "C", "D", "E"])}
        spy = frame(260, price=100)
        cfg = BacktestConfig(transaction_cost_pct=0, slippage_pct=0)
        before = cross_sectional_momentum_backtest(prices, spy, cfg, top_fraction=.2)
        extended = {}
        for symbol, data in prices.items():
            future = data.iloc[[-1]].copy()
            future["date"] = "2030-01-01"
            future[["open", "high", "low", "close"]] = 1_000_000 if symbol == "A" else 1
            extended[symbol] = pd.concat([data, future], ignore_index=True)
        spy_future = spy.iloc[[-1]].copy()
        spy_future["date"] = "2030-01-01"
        after = cross_sectional_momentum_backtest(extended, pd.concat([spy, spy_future], ignore_index=True), cfg, top_fraction=.2)
        original_trades = [trade for trade in after["trades"] if trade["date"] <= prices["A"]["date"].iloc[-1]]
        self.assertEqual(before["trades"], original_trades)

    def test_equal_weight_waits_until_execution_date(self):
        prices = {symbol: frame(5) for symbol in ["A", "B"]}
        result = equal_weight_buy_and_hold(prices, BacktestConfig(transaction_cost_pct=0, slippage_pct=0))
        self.assertEqual(result["equity_curve"].iloc[0]["equity"], 10_000)

    def test_historical_signal_snapshot_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "record.json"
            path.write_text(json.dumps({"strategy_signals": [{"strategy": "Pullback", "signal": "BUY"}]}), encoding="utf-8")
            enrich_prediction(str(path), strategy_signals=[{"strategy": "Pullback", "signal": "WAIT"}])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["strategy_signals"][0]["signal"], "BUY")

    def test_old_snapshot_does_not_receive_recomputed_regime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "record.json"
            path.write_text(json.dumps({"strategy_signals": [{"strategy": "Pullback", "signal": "BUY"}]}), encoding="utf-8")
            enrich_prediction(str(path), strategy_signals=[{"strategy": "Pullback", "signal": "WAIT"}], market_regime="Favorable")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("market_regime", saved)

    def test_future_5d_10d_20d_validation_and_alpha(self):
        stock = frame(30, price=100)
        spy = frame(30, price=100)
        stock["close"] = [100 + i for i in range(30)]
        spy["close"] = [100 + i * .5 for i in range(30)]
        record = {"timestamp": stock.loc[0, "date"], "strategy_signals": [{"strategy": "Momentum", "signal": "BUY"}]}
        validated = fixed_horizon_validation(record, stock, spy)
        self.assertEqual(set(validated), {"5", "10", "20"})
        self.assertAlmostEqual(validated["10"]["alpha_pct"], 5.0)
        self.assertTrue(validated["20"]["beat_spy"])


if __name__ == "__main__":
    unittest.main()
