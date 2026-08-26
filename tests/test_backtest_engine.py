import unittest

import pandas as pd

from src.backtest_engine import BacktestConfig, calculate_buy_and_hold, run_backtest


def frame(rows):
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "signal"])


class BacktestEngineTests(unittest.TestCase):
    def test_signal_executes_next_day_open(self):
        df = frame([
            ["2026-01-01", 10, 11, 9, 10, "buy"],
            ["2026-01-02", 20, 21, 19, 20, None],
        ])
        result = run_backtest(
            df,
            BacktestConfig(initial_capital=1000, transaction_cost_pct=0, slippage_pct=0),
        )
        trade = result["trades"][0]
        self.assertEqual(trade["signal_date"], "2026-01-01")
        self.assertEqual(trade["execution_date"], "2026-01-02")
        self.assertEqual(trade["execution_price"], 20)

    def test_future_open_does_not_change_prior_day_equity(self):
        base = frame([
            ["2026-01-01", 10, 10, 10, 10, "buy"],
            ["2026-01-02", 20, 20, 20, 20, None],
            ["2026-01-03", 30, 30, 30, 30, None],
        ])
        changed = base.copy()
        changed.loc[2, "open"] = 999
        cfg = BacktestConfig(initial_capital=1000, transaction_cost_pct=0, slippage_pct=0)
        r1 = run_backtest(base, cfg)
        r2 = run_backtest(changed, cfg)
        self.assertEqual(
            r1["equity_curve"].loc[1, "portfolio_value"],
            r2["equity_curve"].loc[1, "portfolio_value"],
        )

    def test_trailing_stop_does_not_use_same_day_new_high(self):
        df = frame([
            ["2026-01-01", 100, 100, 100, 100, "buy"],
            ["2026-01-02", 100, 100, 90, 100, None],
            ["2026-01-03", 110, 150, 100, 140, None],
            ["2026-01-04", 130, 135, 119, 125, None],
        ])
        result = run_backtest(
            df,
            BacktestConfig(
                initial_capital=1000,
                transaction_cost_pct=0,
                slippage_pct=0,
                exit_mode="trailing",
                trailing_pct=20,
            ),
        )
        sells = [t for t in result["trades"] if t["action"] == "sell"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["execution_date"], "2026-01-04")
        self.assertEqual(sells[0]["execution_price"], 120)

    def test_gap_down_trailing_executes_at_open_not_stop(self):
        df = frame([
            ["2026-01-01", 100, 100, 100, 100, "buy"],
            ["2026-01-02", 100, 125, 100, 120, None],
            ["2026-01-03", 90, 95, 80, 85, None],
        ])
        result = run_backtest(
            df,
            BacktestConfig(
                initial_capital=1000,
                transaction_cost_pct=0,
                slippage_pct=0,
                exit_mode="trailing",
                trailing_pct=20,
            ),
        )
        sells = [t for t in result["trades"] if t["action"] == "sell"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["execution_date"], "2026-01-03")
        self.assertEqual(sells[0]["execution_price"], 90)

    def test_take_profit_has_equity_curve_and_execution_date(self):
        df = frame([
            ["2026-01-01", 100, 100, 100, 100, "buy"],
            ["2026-01-02", 100, 130, 99, 125, None],
        ])
        result = run_backtest(
            df,
            BacktestConfig(
                initial_capital=1000,
                transaction_cost_pct=0,
                slippage_pct=0,
                exit_mode="take_profit",
                take_profit_pct=25,
            ),
        )
        sells = [t for t in result["trades"] if t["action"] == "sell"]
        self.assertEqual(sells[0]["execution_date"], "2026-01-02")
        self.assertEqual(sells[0]["execution_price"], 125)
        self.assertEqual(len(result["equity_curve"]), 2)
        self.assertEqual(result["equity_curve"].iloc[-1]["portfolio_value"], 1250)

    def test_gap_up_take_profit_executes_at_open(self):
        df = frame([
            ["2026-01-01", 100, 100, 100, 100, "buy"],
            ["2026-01-02", 100, 110, 99, 105, None],
            ["2026-01-03", 140, 145, 138, 142, None],
        ])
        result = run_backtest(
            df,
            BacktestConfig(
                initial_capital=1000,
                transaction_cost_pct=0,
                slippage_pct=0,
                exit_mode="take_profit",
                take_profit_pct=25,
            ),
        )
        sells = [t for t in result["trades"] if t["action"] == "sell"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["execution_date"], "2026-01-03")
        self.assertEqual(sells[0]["execution_price"], 140)

    def test_buy_and_hold_applies_cost_and_slippage(self):
        df = frame([
            ["2026-01-01", 100, 105, 95, 100, None],
            ["2026-01-02", 110, 115, 105, 110, None],
        ])
        frictionless = calculate_buy_and_hold(
            df,
            initial_capital=1000,
            transaction_cost_pct=0,
            slippage_pct=0,
        )
        with_costs = calculate_buy_and_hold(
            df,
            initial_capital=1000,
            transaction_cost_pct=0.001,
            slippage_pct=0.0005,
        )
        self.assertEqual(frictionless["total_return_pct"], 10.0)
        self.assertLess(with_costs["total_return_pct"], frictionless["total_return_pct"])


if __name__ == "__main__":
    unittest.main()
