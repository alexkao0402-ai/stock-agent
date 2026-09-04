import unittest

from src.trading_calendar import (
    is_early_close,
    is_month_end_session,
    is_session,
    next_session,
    session_close,
)


class TradingCalendarTests(unittest.TestCase):
    def test_weekend_and_us_holiday_are_not_sessions(self):
        self.assertFalse(is_session("2026-08-29"))
        self.assertFalse(is_session("2026-09-07"))  # Labor Day

    def test_t1_and_t2_use_sessions_not_calendar_days(self):
        self.assertEqual(next_session("2026-09-04", 1).isoformat(), "2026-09-08")
        self.assertEqual(next_session("2026-09-04", 2).isoformat(), "2026-09-09")

    def test_month_end_weekend_and_holiday(self):
        self.assertTrue(is_month_end_session("2024-08-30"))
        self.assertFalse(is_month_end_session("2024-08-31"))
        self.assertTrue(is_month_end_session("2021-05-28"))  # Memorial Day was May 31.

    def test_early_close_and_dst_are_explicit_new_york_times(self):
        self.assertTrue(is_early_close("2026-11-27"))
        self.assertEqual(session_close("2026-11-27").hour, 13)
        self.assertEqual(str(session_close("2026-03-06").tzinfo), "America/New_York")
        self.assertNotEqual(
            session_close("2026-03-06").utcoffset(),
            session_close("2026-03-09").utcoffset(),
        )


if __name__ == "__main__":
    unittest.main()
