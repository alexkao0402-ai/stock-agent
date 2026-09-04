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
            self.assertIn("尚未產生第一筆正式 Forward Signal", state["warnings"])

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
            self.assertEqual(state["execution_status"], "已執行")
            self.assertEqual(state["holdings"][0]["ticker"], "NVDA")
            self.assertEqual(set(state["curve"]["series"]), {"V12", "SPY", "QQQ"})

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
            self.assertEqual(state["execution_status"], "逾期未執行")


if __name__ == "__main__":
    unittest.main()
