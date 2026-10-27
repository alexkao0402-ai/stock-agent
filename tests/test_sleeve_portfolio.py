import unittest

import pandas as pd
import numpy as np

from src.backtest_engine import BacktestConfig
from src.candidate_strategies import bollinger_mean_reversion_variant
from src.cross_sectional import cross_sectional_momentum_backtest
from src.portfolio_backtest import run_signal_portfolio
from src.sleeve_portfolio import combine_sleeves, disjoint_periods, fifo_sell_fills, period_metrics, replay_fills


def result(values, cash=None, capital=None):
    return {"strategy": "Synthetic", "initial_capital": capital or values[0], "final_value": values[-1],
            "equity_curve": pd.DataFrame({"date": pd.date_range("2025-01-01", periods=len(values)),
                                          "equity": values, "cash": cash if cash is not None else values}), "trades": []}


class SleevePortfolioTests(unittest.TestCase):
    def test_sums_dollars_and_permits_weight_drift(self):
        mixed = combine_sleeves({"CSM": result([50, 100, 100]), "E3": result([50, 50, 100])}, "50/50")
        self.assertEqual(mixed["equity_curve"]["equity"].tolist(), [100, 150, 200])
        self.assertAlmostEqual(mixed["equity_curve"].iloc[1]["CSM_weight"], 2 / 3)
        self.assertEqual(mixed["initial_capital"], 100)

    def test_rejects_misaligned_calendars(self):
        other = result([50, 50, 50])
        other["equity_curve"].loc[2, "date"] = pd.Timestamp("2025-01-05")
        with self.assertRaises(ValueError):
            combine_sleeves({"CSM": result([50, 50, 50]), "E3": other}, "mixed")

    def test_split_contains_each_return_once_and_compounds(self):
        item = result([100, 110, 132, 118.8])
        periods = disjoint_periods(item["equity_curve"]["date"], "2025-01-03")
        self.assertEqual(len(periods["Research"].intersection(periods["Explored OOS"])), 0)
        a = period_metrics(item, periods["Research"], item, item)
        b = period_metrics(item, periods["Explored OOS"], item, item)
        c = period_metrics(item, periods["Full"], item, item)
        self.assertAlmostEqual((1 + a["Return %"] / 100) * (1 + b["Return %"] / 100), 1 + c["Return %"] / 100)
        self.assertEqual(a["Sessions"] + b["Sessions"], c["Sessions"])

    def test_fifo_partial_sells_allocate_entry_commission(self):
        fills = [
            {"symbol": "A", "execution_date": "2025-01-02", "action": "BUY", "execution_price": 10, "shares": 10, "transaction_cost": 1},
            {"symbol": "A", "execution_date": "2025-01-03", "action": "SELL", "execution_price": 12, "shares": 4, "transaction_cost": 0.48},
            {"symbol": "A", "execution_date": "2025-01-04", "action": "SELL", "execution_price": 9, "shares": 6, "transaction_cost": 0.54},
        ]
        closed = fifo_sell_fills(fills)
        self.assertAlmostEqual(closed[0]["net_pnl"], 7.12)
        self.assertAlmostEqual(closed[1]["net_pnl"], -7.14)
        self.assertAlmostEqual(sum(c["cost_basis"] for c in closed), 101)

    def test_replay_rejects_same_day_fill(self):
        item = result([100, 100, 100])
        item["trades"] = [{"symbol": "A", "execution_date": "2025-01-02", "signal_date": "2025-01-02",
                            "action": "BUY", "execution_price": 10, "shares": 1, "transaction_cost": 0.01}]
        with self.assertRaisesRegex(ValueError, "next common session"):
            replay_fills(item, {})

    def test_drawdown_includes_starting_nav(self):
        item = result([100, 80, 90])
        metrics = period_metrics(item, pd.date_range("2025-01-02", periods=2), item, item)
        self.assertAlmostEqual(metrics["Max Drawdown %"], -20)

    def test_future_prices_cannot_change_prior_sleeve_nav(self):
        dates = pd.date_range("2020-01-01", periods=245)
        def frame(prices):
            return pd.DataFrame({"date": dates, "open": prices, "high": prices * 1.01,
                                 "low": prices * 0.99, "close": prices, "volume": 1000})
        closes = 100 + np.arange(245) * 0.2
        closes[205:207] = [126, 125]
        stock, spy = frame(closes), frame(100 + np.arange(245) * 0.1)
        future_stock, future_spy = stock.copy(), spy.copy()
        for item in (future_stock, future_spy):
            item.loc[220:, ["open", "high", "low", "close"]] *= 2
        cfg = BacktestConfig()
        old_signals = bollinger_mean_reversion_variant(stock, spy, False, True, False)
        new_signals = bollinger_mean_reversion_variant(future_stock, future_spy, False, True, False)
        self.assertTrue(old_signals.iloc[205]["entry_signal"])
        old_e3 = run_signal_portfolio({"A": old_signals}, "E3", cfg, 2, 10)
        new_e3 = run_signal_portfolio({"A": new_signals}, "E3", cfg, 2, 10)
        old_csm = cross_sectional_momentum_backtest({"A": stock}, spy, cfg)
        new_csm = cross_sectional_momentum_backtest({"A": future_stock}, future_spy, cfg)
        for old, new in ((old_e3, new_e3), (old_csm, new_csm)):
            pd.testing.assert_series_equal(old["equity_curve"]["equity"].iloc[:220], new["equity_curve"]["equity"].iloc[:220])


if __name__ == "__main__":
    unittest.main()
