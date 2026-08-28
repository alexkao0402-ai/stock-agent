import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.live_large_cap_data import (
    LiveDataError,
    annotate_history_coverage,
    parse_nasdaq_directories,
    parse_sec_ticker_exchange,
    rank_us_companies,
    write_immutable_live_inputs,
)


NASDAQ_TEXT = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
GOOG|Alphabet Inc. Class C|Q|N|N|100|N|N
GOOGL|Alphabet Inc. Class A|Q|N|N|100|N|N
SPCX|Example ETF|Q|N|N|100|Y|N
TEST|Test Security|Q|Y|N|100|N|N
WXYZW|Example Warrants|Q|N|N|100|N|N
File Creation Time: 0828202621:00|||||||
"""

OTHER_TEXT = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B|N|BRK.B|N|100|N|BRK.B
TSM|Taiwan Semiconductor Manufacturing Company Ltd.|N|TSM|N|100|N|TSM
"""


class LiveLargeCapDataTests(unittest.TestCase):
    def test_nasdaq_parser_removes_etfs_tests_and_warrants(self):
        listed = parse_nasdaq_directories(NASDAQ_TEXT, OTHER_TEXT)
        self.assertIn("GOOG", listed)
        self.assertIn("GOOGL", listed)
        self.assertIn("BRK-B", listed)
        self.assertNotIn("SPCX", listed)
        self.assertNotIn("TEST", listed)
        self.assertNotIn("WXYZW", listed)

    def test_sec_mapping_normalizes_share_class_symbols(self):
        mapping = parse_sec_ticker_exchange({
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [[1067983, "BERKSHIRE HATHAWAY INC", "BRK.B", "NYSE"]],
        })
        self.assertEqual(mapping["BRK-B"]["cik"], 1067983)

    def test_company_ranking_deduplicates_share_classes_and_excludes_foreign(self):
        listed = parse_nasdaq_directories(NASDAQ_TEXT, OTHER_TEXT)
        sec = {
            "GOOG": {"cik": 1, "sec_name": "Alphabet", "sec_exchange": "Nasdaq"},
            "GOOGL": {"cik": 1, "sec_name": "Alphabet", "sec_exchange": "Nasdaq"},
            "BRK-B": {"cik": 2, "sec_name": "Berkshire", "sec_exchange": "NYSE"},
            "TSM": {"cik": 3, "sec_name": "TSMC", "sec_exchange": "NYSE"},
        }
        candidates = [
            {"symbol": "TSM", "market_cap": 500, "average_daily_volume_3m": 10},
            {"symbol": "GOOG", "market_cap": 450, "average_daily_volume_3m": 20},
            {"symbol": "GOOGL", "market_cap": 440, "average_daily_volume_3m": 30},
            {"symbol": "BRK-B", "market_cap": 300, "average_daily_volume_3m": 5},
        ]
        jurisdictions = {
            1: {"state_of_incorporation": "DE", "entity_name": "Alphabet"},
            2: {"state_of_incorporation": "DE", "entity_name": "Berkshire"},
            3: {"state_of_incorporation": "X1", "entity_name": "TSMC"},
        }
        selected, excluded, coverage = rank_us_companies(
            candidates,
            listed,
            sec,
            jurisdictions.__getitem__,
            top_n=2,
            eligibility_buffer=0,
        )
        self.assertEqual([row["stable_company_id"] for row in selected], ["SEC-CIK-0000000001", "SEC-CIK-0000000002"])
        self.assertEqual(selected[0]["ticker"], "GOOGL")
        self.assertEqual(selected[0]["share_classes"], ["GOOG", "GOOGL"])
        self.assertEqual(selected[0]["company_market_cap"], 450)
        self.assertTrue(any(row["symbol"] == "TSM" for row in excluded))
        self.assertEqual(coverage["selected_companies"], 2)

    def test_representative_ticker_uses_largest_share_class_before_liquidity(self):
        listed = parse_nasdaq_directories(NASDAQ_TEXT, OTHER_TEXT)
        sec = {
            "GOOG": {"cik": 1, "sec_name": "Alphabet", "sec_exchange": "Nasdaq"},
            "GOOGL": {"cik": 1, "sec_name": "Alphabet", "sec_exchange": "Nasdaq"},
        }
        candidates = [
            {"symbol": "GOOG", "market_cap": 450, "shares_outstanding": 100, "regular_market_price": 10, "average_daily_volume_3m": 10},
            {"symbol": "GOOGL", "market_cap": 440, "shares_outstanding": 50, "regular_market_price": 10, "average_daily_volume_3m": 100},
        ]
        selected, _, _ = rank_us_companies(
            candidates,
            listed,
            sec,
            lambda _: {"state_of_incorporation": "DE", "entity_name": "Alphabet"},
            top_n=1,
            eligibility_buffer=0,
        )
        self.assertEqual(selected[0]["ticker"], "GOOG")

    def test_ranking_fails_closed_when_coverage_is_too_small(self):
        with self.assertRaises(LiveDataError):
            rank_us_companies([], {}, {}, lambda _: {}, top_n=10)

    def test_yahoo_profile_fallback_preserves_company_and_country_checks(self):
        listed = parse_nasdaq_directories(NASDAQ_TEXT, OTHER_TEXT)
        candidates = [
            {"symbol": "TSM", "market_cap": 500, "message_board_id": "foreign", "average_daily_volume_3m": 10},
            {"symbol": "GOOG", "market_cap": 450, "message_board_id": "alphabet", "average_daily_volume_3m": 20},
            {"symbol": "GOOGL", "market_cap": 440, "message_board_id": "alphabet", "average_daily_volume_3m": 30},
            {"symbol": "BRK-B", "market_cap": 300, "message_board_id": "berkshire", "average_daily_volume_3m": 5},
        ]
        profiles = {
            "TSM": {"message_board_id": "foreign", "country": "Taiwan", "entity_name": "TSMC"},
            "GOOG": {"message_board_id": "alphabet", "country": "United States", "entity_name": "Alphabet"},
            "GOOGL": {"message_board_id": "alphabet", "country": "United States", "entity_name": "Alphabet"},
            "BRK-B": {"message_board_id": "berkshire", "country": "United States", "entity_name": "Berkshire"},
        }
        selected, excluded, _ = rank_us_companies(
            candidates,
            listed,
            {},
            lambda _: {},
            profile_lookup=profiles.__getitem__,
            top_n=2,
            eligibility_buffer=0,
        )
        self.assertEqual(selected[0]["stable_company_id"], "YAHOO-MBID-alphabet")
        self.assertEqual(selected[0]["share_classes"], ["GOOG", "GOOGL"])
        self.assertEqual(selected[0]["company_identity_source"], "YAHOO_PROFILE_FALLBACK")
        self.assertTrue(any(row["symbol"] == "TSM" for row in excluded))

    def test_sec_cik_remains_stable_when_yahoo_only_supplies_domicile(self):
        listed = parse_nasdaq_directories(NASDAQ_TEXT, OTHER_TEXT)
        selected, _, _ = rank_us_companies(
            [{"symbol": "GOOG", "market_cap": 450, "message_board_id": "alphabet"}],
            listed,
            {"GOOG": {"cik": 1652044, "sec_name": "Alphabet", "sec_exchange": "Nasdaq"}},
            lambda _: (_ for _ in ()).throw(LiveDataError("SEC unavailable")),
            profile_lookup=lambda _: {
                "message_board_id": "alphabet",
                "country": "United States",
                "entity_name": "Alphabet",
            },
            top_n=1,
            eligibility_buffer=0,
        )
        self.assertEqual(selected[0]["stable_company_id"], "SEC-CIK-0001652044")
        self.assertEqual(
            selected[0]["company_identity_source"],
            "SEC_CIK_YAHOO_DOMICILE_FALLBACK",
        )

    def test_recent_ipo_is_recorded_as_ineligible_instead_of_data_failure(self):
        dates = pd.bdate_range(end="2026-08-28", periods=253).strftime("%Y-%m-%d")
        prices = pd.DataFrame(
            [{"ticker": "SPY", "trade_date": date} for date in dates]
            + [{"ticker": "NEW", "trade_date": date} for date in dates[-20:]]
        )
        first_trade_ms = int(pd.Timestamp(dates[-20], tz="UTC").timestamp() * 1000)
        selected, insufficient = annotate_history_coverage(
            [{"ticker": "NEW", "first_trade_date_ms": first_trade_ms}],
            prices,
            "2026-08-28",
        )
        self.assertEqual(insufficient, ["NEW"])
        self.assertEqual(selected[0]["history_status"], "INSUFFICIENT_BY_DESIGN_V12_INELIGIBLE")

    def test_old_listing_with_short_history_fails_closed(self):
        dates = pd.bdate_range(end="2026-08-28", periods=253).strftime("%Y-%m-%d")
        prices = pd.DataFrame(
            [{"ticker": "SPY", "trade_date": date} for date in dates]
            + [{"ticker": "OLD", "trade_date": date} for date in dates[-20:]]
        )
        old_listing_ms = int(pd.Timestamp("2000-01-01", tz="UTC").timestamp() * 1000)
        with self.assertRaises(LiveDataError):
            annotate_history_coverage(
                [{"ticker": "OLD", "first_trade_date_ms": old_listing_ms}],
                prices,
                "2026-08-28",
            )

    def test_live_bundle_is_immutable_and_hashed(self):
        selected = [{
            "market_cap_rank": 1,
            "stable_company_id": "SEC-CIK-0000000001",
            "stable_security_id": "SEC-CIK-0000000001:AAA",
            "ticker": "AAA",
            "company_market_cap": 100.0,
        }]
        prices = pd.DataFrame([{
            "ticker": "AAA", "trade_date": "2026-08-28", "open": 10.0, "close": 11.0,
            "adjusted_close": 11.0, "total_return_or_corporate_action_adjustment": 1.0,
            "dividend": 0.0, "stock_split": 0.0,
        }, {
            "ticker": "SPY", "trade_date": "2026-08-28", "open": 20.0, "close": 21.0,
            "adjusted_close": 21.0, "total_return_or_corporate_action_adjustment": 1.0,
            "dividend": 0.0, "stock_split": 0.0,
        }])
        with tempfile.TemporaryDirectory() as temp_dir:
            root, created = write_immutable_live_inputs(
                "2026-08-28", selected, prices,
                source_hashes={"source": "a" * 64}, exclusions=[], coverage={},
                directory=temp_dir, captured_at="2026-08-29T00:00:00+00:00",
            )
            manifest_before = (root / "manifest.json").read_bytes()
            root_again, created_again = write_immutable_live_inputs(
                "2026-08-28", selected, prices.assign(close=999),
                source_hashes={"source": "b" * 64}, exclusions=[], coverage={},
                directory=temp_dir, captured_at="2026-08-30T00:00:00+00:00",
            )
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(root, root_again)
            self.assertEqual(manifest_before, (root / "manifest.json").read_bytes())
            manifest = json.loads(manifest_before)
            self.assertEqual(set(manifest["files"]), {"monthly_universe.csv", "daily_prices.csv", "selection_details.json"})


if __name__ == "__main__":
    unittest.main()
