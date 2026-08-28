import unittest

import pandas as pd

from src.point_in_time_universe import PointInTimeDataError, PointInTimeUniverse


def fixture():
    memberships = pd.DataFrame([
        {"permanent_id": "A", "ticker": "AAA", "member_from": "2019-01-01", "member_to": None, "index_name": "S&P 500"},
        {"permanent_id": "B", "ticker": "BBB", "member_from": "2019-01-01", "member_to": None, "index_name": "S&P 500"},
        {"permanent_id": "C", "ticker": "CCC", "member_from": "2021-01-01", "member_to": None, "index_name": "S&P 500"},
    ])
    caps = pd.DataFrame([
        {"permanent_id": "A", "as_of_date": "2020-01-31", "available_date": "2020-02-01", "market_cap_usd": 100},
        {"permanent_id": "B", "as_of_date": "2020-01-31", "available_date": "2020-02-01", "market_cap_usd": 90},
        {"permanent_id": "A", "as_of_date": "2020-02-29", "available_date": "2020-03-01", "market_cap_usd": 80},
        {"permanent_id": "B", "as_of_date": "2020-02-29", "available_date": "2020-03-01", "market_cap_usd": 120},
        {"permanent_id": "C", "as_of_date": "2021-01-31", "available_date": "2021-02-01", "market_cap_usd": 200},
    ])
    return PointInTimeUniverse(memberships, caps).validated()


class PointInTimeUniverseTests(unittest.TestCase):
    def test_uses_only_information_available_on_signal_date(self):
        universe = fixture()
        selected = universe.top_n("2020-02-15", n=1)
        self.assertEqual(selected.iloc[0]["permanent_id"], "A")

    def test_future_market_cap_does_not_rewrite_past_ranking(self):
        universe = fixture()
        before = universe.top_n("2020-02-15", n=2)
        future = pd.concat([universe.market_caps, pd.DataFrame([{
            "permanent_id": "B", "as_of_date": "2025-01-31",
            "available_date": "2025-02-01", "market_cap_usd": 9999,
        }])], ignore_index=True)
        after = PointInTimeUniverse(universe.memberships, future).validated().top_n("2020-02-15", n=2)
        pd.testing.assert_frame_equal(before, after)

    def test_future_member_is_not_visible_early(self):
        universe = fixture()
        selected = universe.top_n("2020-02-15", n=2)
        self.assertNotIn("C", selected["permanent_id"].tolist())

    def test_rejects_availability_before_observation(self):
        universe = fixture()
        bad = universe.market_caps.copy()
        bad.loc[0, "available_date"] = pd.Timestamp("2019-12-01")
        with self.assertRaises(PointInTimeDataError):
            PointInTimeUniverse(universe.memberships, bad).validated()

    def test_fails_closed_when_coverage_is_incomplete(self):
        universe = fixture()
        with self.assertRaises(PointInTimeDataError):
            universe.top_n("2020-02-15", n=3)


if __name__ == "__main__":
    unittest.main()
