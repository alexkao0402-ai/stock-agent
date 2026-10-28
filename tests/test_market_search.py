import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest


def payload(symbol):
    return {"prices": pd.DataFrame({"date": ["2026-10-26", "2026-10-27"], "close": [100.0, 101.0]}),
            "overview": {"公司名稱": f"Test company {symbol}"}, "news": [], "filings": [], "earnings": [],
            "source": "Synthetic test fixture", "fundamentals_source": "Synthetic test fixture",
            "news_source": "Unavailable", "fetched_at": "2026-10-27T21:32:00Z", "provider_status": []}


def search_button(page):
    return next(button for button in page.button if button.label == "Search")


class SharedMarketSearchTests(unittest.TestCase):
    def page(self):
        return AppTest.from_string("from app import render_market\nrender_market()")

    def test_initial_page_has_one_search_and_no_account_dependencies(self):
        with patch("app._market_payload") as load, \
             patch("app._dashboard_state", side_effect=AssertionError("Market page must not load V12")), \
             patch("app._e3_view", side_effect=AssertionError("Market page must not load E3")):
            page = self.page().run(timeout=20)
        self.assertFalse(page.exception)
        self.assertEqual(len(page.text_input), 1)
        self.assertEqual(len(page.selectbox), 0)
        self.assertEqual([button.label for button in page.button], ["Search"])
        load.assert_not_called()

    def test_googl_search_normalizes_input_and_uses_the_submitted_ticker(self):
        with patch("app._market_payload", side_effect=payload) as load:
            page = self.page().run(timeout=20)
            page.text_input[0].set_value(" googl ")
            search_button(page).click().run(timeout=20)
        self.assertFalse(page.exception)
        load.assert_called_once_with("GOOGL")
        self.assertEqual(page.session_state["market_symbol"], "GOOGL")
        self.assertTrue(any("Test company GOOGL" in m.value for m in page.markdown))
        self.assertFalse(any("valid ticker" in w.value for w in page.warning))

    def test_switching_tickers_replaces_results_and_invalid_input_does_not_reuse_them(self):
        with patch("app._market_payload", side_effect=payload) as load:
            page = self.page().run(timeout=20)
            for ticker in ("NVDA", "GOOGL"):
                page.text_input[0].set_value(ticker)
                search_button(page).click().run(timeout=20)
                self.assertFalse(page.exception)
                self.assertEqual(page.session_state["market_symbol"], ticker)
                self.assertTrue(any(f"Test company {ticker}" in m.value for m in page.markdown))
            self.assertEqual([call.args[0] for call in load.call_args_list], ["NVDA", "GOOGL"])
            load.reset_mock()
            page.text_input[0].set_value("../secret")
            search_button(page).click().run(timeout=20)
            self.assertFalse(page.exception)
            self.assertTrue(any("valid ticker" in w.value for w in page.warning))
            self.assertNotIn("market_symbol", page.session_state)
            self.assertFalse(any("Test company" in m.value for m in page.markdown))
            load.assert_not_called()

    def test_remembered_ticker_is_visible_in_the_only_search_field(self):
        with patch("app._market_payload", side_effect=payload) as load:
            page = self.page()
            page.session_state["market_symbol"] = "GOOGL"
            page.run(timeout=20)
        self.assertFalse(page.exception)
        self.assertEqual(page.text_input[0].value, "GOOGL")
        load.assert_called_once_with("GOOGL")


if __name__ == "__main__":
    unittest.main()
