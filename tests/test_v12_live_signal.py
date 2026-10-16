import unittest

import numpy as np
import pandas as pd

from src.v12_live_signal import compute_frozen_v12_signal


def _universe(signal_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_date": signal_date,
                "stable_company_id": f"COMPANY-{index:02d}",
                "stable_security_id": f"SECURITY-{index:02d}",
                "ticker": f"S{index:02d}",
                "company_market_cap": float(1_000 - index),
                "market_cap_rank": index,
            }
            for index in range(1, 11)
        ]
    )


def _prices(*, spy_rising: bool = True, add_future_row: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-08-31", periods=300)
    rows = []
    for index in range(1, 11):
        # Higher-numbered stocks have stronger, monotonic momentum.
        growth = 0.0005 + index * 0.0002
        close = 100.0 * np.exp(np.arange(len(dates)) * growth)
        rows.extend(
            {
                "ticker": f"S{index:02d}",
                "trade_date": date.date().isoformat(),
                "adjusted_close": value,
            }
            for date, value in zip(dates, close)
        )
    spy_growth = 0.0005 if spy_rising else -0.0005
    spy_close = 100.0 * np.exp(np.arange(len(dates)) * spy_growth)
    rows.extend(
        {
            "ticker": "SPY",
            "trade_date": date.date().isoformat(),
            "adjusted_close": value,
        }
        for date, value in zip(dates, spy_close)
    )
    if add_future_row:
        for index in range(1, 11):
            rows.append(
                {
                    "ticker": f"S{index:02d}",
                    "trade_date": "2026-09-01",
                    "adjusted_close": 1.0 if index >= 9 else 1_000_000.0,
                }
            )
        rows.append(
            {"ticker": "SPY", "trade_date": "2026-09-01", "adjusted_close": 1.0}
        )
    return pd.DataFrame(rows)


class FrozenV12LiveSignalTests(unittest.TestCase):
    def test_bull_market_selects_two_strongest_names(self):
        result = compute_frozen_v12_signal(_universe("2026-08-31"), _prices())
        self.assertTrue(result["spy_bull"])
        self.assertEqual(result["v7_selected"], ["S09", "S10"])
        self.assertEqual(result["v8_selected"], ["S09", "S10"])
        self.assertEqual(result["consensus_type"], "Same 2")
        self.assertEqual(result["target_weights"], {"S09": 0.5, "S10": 0.5})

    def test_bear_market_holds_cash(self):
        result = compute_frozen_v12_signal(
            _universe("2026-08-31"), _prices(spy_rising=False)
        )
        self.assertFalse(result["spy_bull"])
        self.assertEqual(result["status"], "CASH_NO_ORDERS")
        self.assertEqual(result["target_weights"], {})

    def test_future_prices_cannot_change_signal(self):
        before = compute_frozen_v12_signal(_universe("2026-08-31"), _prices())
        after = compute_frozen_v12_signal(
            _universe("2026-08-31"), _prices(add_future_row=True)
        )
        self.assertEqual(before["v7_selected"], after["v7_selected"])
        self.assertEqual(before["v8_selected"], after["v8_selected"])
        self.assertEqual(before["target_weights"], after["target_weights"])


if __name__ == "__main__":
    unittest.main()
