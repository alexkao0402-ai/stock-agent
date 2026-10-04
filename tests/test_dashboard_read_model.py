from datetime import date
from pathlib import Path
import tempfile
import unittest

from src.dashboard_read_model import build_dashboard_snapshot, read_ledger_events
from src.paper_ledger import AppendOnlyLedger, LedgerEvent, deterministic_event_id


VERSION = "V12-FROZEN-2026-08-28"


def _event(
    portfolio_id: str,
    event_type: str,
    *,
    payload: dict,
    sequence_key: str,
    ticker: str = "",
) -> LedgerEvent:
    return LedgerEvent(
        event_id=deterministic_event_id(portfolio_id, event_type, sequence_key, ticker),
        portfolio_id=portfolio_id,
        event_type=event_type,
        strategy_version=VERSION,
        signal_timestamp="2026-08-31T16:00:00-04:00",
        execution_rule="T+1_OPEN" if portfolio_id.endswith("T1") else "T+2_OPEN",
        data_asof="2026-09-01T09:30:00-04:00",
        ticker=ticker,
        reason="test fixture",
        payload=payload,
        created_at="2026-09-01T20:00:00+00:00",
    )


class DashboardReadModelTests(unittest.TestCase):
    def test_missing_ledger_stays_missing_and_shows_zero_forward_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "does-not-exist.sqlite3"
            state = build_dashboard_snapshot(path, today=date(2026, 8, 29))
            self.assertFalse(path.exists())
            self.assertEqual(read_ledger_events(path), [])
            self.assertEqual(state["formal_forward_rows"], 0)
            self.assertEqual(state["health_status"], "WATCH")
            self.assertFalse(state["trading_blocked"])
            self.assertIn("The first official Forward Signal has not been generated", state["warnings"])

    def test_projects_portfolio_benchmarks_signal_and_holdings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.sqlite3"
            ledger = AppendOnlyLedger(path)
            events = []
            for portfolio_id in ("V12_T1", "SPY_T1", "QQQ_T1", "V12_T2"):
                events.append(_event(
                    portfolio_id, "INITIALIZE", payload={"initial_capital": 10_000.0},
                    sequence_key="init",
                ))
            events.append(_event(
                "V12_T1", "SIGNAL", sequence_key="signal",
                payload={
                    "signal_date": "2026-08-31",
                    "market_regime": "BULL",
                    "v7_selected": ["NVDA", "META"],
                    "v8_selected": ["NVDA", "AMZN"],
                    "portfolio_target_weights": {"NVDA": 0.5, "META": 0.25, "AMZN": 0.25},
                },
            ))
            events.append(_event(
                "V12_T1", "ORDER", sequence_key="order", ticker="NVDA",
                payload={"execution_date": "2026-09-01", "target_weight": 0.5, "status": "PENDING"},
            ))
            events.append(LedgerEvent(**{
                **_event(
                    "V12_T1", "FILL", sequence_key="fill", ticker="NVDA",
                    payload={"execution_date": "2026-09-01", "signal_date": "2026-08-31", "sequence": 1},
                ).__dict__,
                "action": "BUY",
                "fill_price": 100.0,
                "quantity": 10.0,
                "cost": 1.0,
            }))
            snapshots = {
                "V12_T1": 10_500.0,
                "SPY_T1": 10_200.0,
                "QQQ_T1": 10_300.0,
                "V12_T2": 10_450.0,
            }
            for portfolio_id, equity in snapshots.items():
                payload = {
                    "execution_date": "2026-09-01" if portfolio_id.endswith("T1") else "2026-09-02",
                    "cash": 1_000.0,
                    "portfolio_equity": equity,
                    "positions": {"NVDA": {"shares": 10.0, "average_cost": 100.0}} if portfolio_id.startswith("V12") else {},
                }
                events.append(_event(portfolio_id, "PORTFOLIO_SNAPSHOT", payload=payload, sequence_key="snapshot"))
            ledger.append_batch(events)

            state = build_dashboard_snapshot(path, today=date(2026, 9, 1))
            self.assertEqual(state["formal_forward_rows"], 1)
            self.assertAlmostEqual(state["portfolio_value"], 10_500.0)
            self.assertAlmostEqual(state["cumulative_return"], 0.05)
            self.assertAlmostEqual(state["excess_vs_spy"], 0.03)
            self.assertAlmostEqual(state["excess_vs_qqq"], 0.02)
            self.assertAlmostEqual(state["t1_t2_spread"], 0.005)
            self.assertEqual(state["agreement_count"], 1)
            self.assertEqual(state["execution_status"], "Executed")
            self.assertEqual(state["holdings"][0]["ticker"], "NVDA")
            self.assertEqual(set(state["curve"]["series"]), {"V12", "SPY", "QQQ"})
            self.assertEqual(state["latest_trades"][0]["ticker"], "NVDA")
            self.assertAlmostEqual(state["latest_buy_value"], 1_000.0)
            self.assertAlmostEqual(state["latest_sell_value"], 0.0)
            self.assertAlmostEqual(state["latest_trade_fees"], 1.0)

    def test_overdue_signal_is_operational_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.sqlite3"
            ledger = AppendOnlyLedger(path)
            ledger.append_batch([
                _event("V12_T1", "INITIALIZE", payload={"initial_capital": 10_000.0}, sequence_key="init"),
                _event(
                    "V12_T1", "SIGNAL", sequence_key="signal",
                    payload={"signal_date": "2026-08-31", "market_regime": "BULL", "v7_selected": [], "v8_selected": [], "portfolio_target_weights": {}},
                ),
                _event(
                    "V12_T1", "ORDER", sequence_key="order", ticker="CASH",
                    payload={"execution_date": "2026-09-01", "target_weight": 1.0, "status": "PENDING"},
                ),
            ])
            state = build_dashboard_snapshot(path, today=date(2026, 9, 2))
            self.assertTrue(state["trading_blocked"])
            self.assertEqual(state["health_status"], "ERROR")
            self.assertEqual(state["execution_status"], "Overdue")

    def test_latest_signal_does_not_reuse_previous_cycle_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.sqlite3"
            ledger = AppendOnlyLedger(path)
            old_signal = _event(
                "V12_T1", "SIGNAL", sequence_key="old-signal",
                payload={"signal_date": "2026-08-31", "portfolio_target_weights": {"NVDA": 1.0}},
            )
            old_order = _event(
                "V12_T1", "ORDER", sequence_key="old-order", ticker="NVDA",
                payload={"execution_date": "2026-09-01", "target_weight": 1.0, "status": "PENDING"},
            )
            old_snapshot = _event(
                "V12_T1", "PORTFOLIO_SNAPSHOT", sequence_key="old-snapshot",
                payload={"execution_date": "2026-09-01", "portfolio_equity": 10_000.0, "cash": 0.0, "positions": {}},
            )
            new_signal = LedgerEvent(**{
                **old_signal.__dict__,
                "event_id": deterministic_event_id("V12_T1", "SIGNAL", "new-signal"),
                "signal_timestamp": "2026-09-30T16:00:00-04:00",
                "data_asof": "2026-09-30T16:00:00-04:00",
                "payload": {"signal_date": "2026-09-30", "portfolio_target_weights": {"MU": 1.0}},
                "created_at": "2026-10-01T02:00:00+00:00",
            })
            new_order = LedgerEvent(**{
                **old_order.__dict__,
                "event_id": deterministic_event_id("V12_T1", "ORDER", "new-order", "MU"),
                "signal_timestamp": "2026-09-30T16:00:00-04:00",
                "data_asof": "2026-09-30T16:00:00-04:00",
                "ticker": "MU",
                "payload": {"execution_date": "2026-10-01", "target_weight": 1.0, "status": "PENDING"},
                "created_at": "2026-10-01T02:00:00+00:00",
            })
            ledger.append_batch([old_signal, old_order, old_snapshot, new_signal, new_order])

            state = build_dashboard_snapshot(path, today=date(2026, 9, 30))
            self.assertEqual(state["signal_date"], "2026-09-30")
            self.assertEqual(state["execution_date"], "2026-10-01")
            self.assertEqual(state["execution_status"], "Waiting for T+1 open")


if __name__ == "__main__":
    unittest.main()
