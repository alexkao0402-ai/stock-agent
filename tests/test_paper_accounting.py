import unittest

from src.paper_accounting import (
    PortfolioState,
    Position,
    apply_dividend,
    apply_fills,
    apply_split,
    apply_ticker_change,
    build_order_plan,
)


class PaperAccountingTests(unittest.TestCase):
    def test_rotation_reconciles_cash_positions_costs_and_pnl(self):
        state = PortfolioState(
            100.0,
            {"OLD": Position(10.0, 50.0), "KEEP": Position(5.0, 100.0)},
        )
        plan = build_order_plan(
            state,
            {"OLD": 60.0, "KEEP": 100.0, "NEW": 50.0},
            {"KEEP": 0.5, "NEW": 0.5},
        )
        self.assertEqual(plan.orders[0].side, "SELL")
        self.assertTrue(any(order.ticker == "NEW" for order in plan.orders))
        final = apply_fills(state, plan.orders)
        marks = {"KEEP": 100.0, "NEW": 50.0}
        self.assertAlmostEqual(final.equity(marks), final.cash + sum(
            position.shares * marks[ticker] for ticker, position in final.positions.items()
        ))
        self.assertGreater(final.realized_pnl, 0.0)
        self.assertGreater(final.transaction_costs, 0.0)

    def test_unchanged_exact_target_does_not_trade(self):
        state = PortfolioState(0.0, {"AAPL": Position(50.0, 100.0), "MSFT": Position(25.0, 200.0)})
        plan = build_order_plan(state, {"AAPL": 100.0, "MSFT": 200.0}, {"AAPL": 0.5, "MSFT": 0.5})
        self.assertEqual(plan.orders, ())

    def test_full_cash_sells_all_positions(self):
        state = PortfolioState(0.0, {"AAPL": Position(10.0, 100.0)})
        plan = build_order_plan(state, {"AAPL": 110.0}, {})
        self.assertTrue(plan.orders)
        self.assertTrue(all(order.side == "SELL" for order in plan.orders))
        self.assertEqual(apply_fills(state, plan.orders).positions, {})

    def test_whole_share_rounding_and_insufficient_cash(self):
        state = PortfolioState(1_000.0)
        plan = build_order_plan(
            state, {"A": 600.0, "B": 600.0}, {"A": 0.5, "B": 0.5}, fractional_shares=False
        )
        self.assertGreaterEqual(plan.estimated_ending_cash, 0.0)
        self.assertTrue(all(order.shares == int(order.shares) for order in plan.orders))

    def test_split_dividend_and_ticker_change_preserve_economic_value(self):
        state = PortfolioState(100.0, {"OLD": Position(10.0, 50.0)})
        split = apply_split(state, "OLD", 2.0)
        self.assertAlmostEqual(state.equity({"OLD": 60.0}), split.equity({"OLD": 30.0}))
        paid = apply_dividend(split, "OLD", 1.0)
        self.assertEqual(paid.dividends, 20.0)
        renamed = apply_ticker_change(paid, "OLD", "NEW")
        self.assertIn("NEW", renamed.positions)
        self.assertNotIn("OLD", renamed.positions)

    def test_missing_price_fails_closed(self):
        with self.assertRaises(ValueError):
            build_order_plan(
                PortfolioState(1_000.0), {}, {"AAPL": 1.0}
            )


if __name__ == "__main__":
    unittest.main()
