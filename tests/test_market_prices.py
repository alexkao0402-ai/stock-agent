from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from src.market_prices import completed_rows, market_prices, alpha_daily, yahoo_daily
from src.research_cache import ResearchCache


class PriceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache = ResearchCache(directory.name)
        self.now = datetime(2026, 10, 12, 18, tzinfo=timezone.utc)  # 14:00 New York
        self.rows = [{'date': '2026-10-09', 'close': 100}, {'date': '2026-10-08', 'close': 98}]

    def test_completed_daily_only_and_bad_values(self):
        rows = self.rows + [{'date': '2026-10-12', 'close': 102}, {'date': '2026-10-13', 'close': 103},
                            {'date': 'bad', 'close': 100}, {'date': '2026-10-07', 'close': float('nan')},
                            {'date': '2026-10-06', 'close': -1}]
        self.assertEqual([r['date'] for r in completed_rows(rows, self.now)], ['2026-10-08', '2026-10-09'])
        after_close = datetime(2026,10,12,21,tzinfo=timezone.utc)
        self.assertEqual(completed_rows(rows, after_close)[-1]['date'], '2026-10-12')

    def test_yahoo_failure_uses_alpha_once_and_caches(self):
        with patch('src.market_prices.get_secret', return_value='private'), \
             patch('src.market_prices.yahoo_daily', side_effect=RuntimeError('429 private')), \
             patch('src.market_prices.alpha_daily', return_value=self.rows) as alpha:
            frame, source, status = market_prices('AAPL', self.cache, self.now)
            again = market_prices('AAPL', self.cache, self.now)
        self.assertEqual(source, 'Alpha Vantage')
        self.assertEqual(frame.iloc[-1]['close'], 100)
        self.assertEqual(again[1], source)
        self.assertEqual(status[0]['Status'], 'Rate limited')
        self.assertNotIn('private', str(status))
        alpha.assert_called_once()

    def test_yahoo_success_does_not_spend_alpha_quota(self):
        with patch('src.market_prices.get_secret', return_value='private'), \
             patch('src.market_prices.yahoo_daily', return_value=self.rows), \
             patch('src.market_prices.alpha_daily') as alpha:
            _, source, _ = market_prices('AAPL', self.cache, self.now)
        self.assertEqual(source, 'Yahoo Finance')
        alpha.assert_not_called()

    def test_missing_key_and_failures_return_empty_safely(self):
        with patch('src.market_prices.get_secret', return_value=None), \
             patch('src.market_prices.yahoo_daily', side_effect=requests.Timeout('private')), \
             patch('src.market_prices.alpha_daily') as alpha:
            frame, source, status = market_prices('AAPL', self.cache, self.now)
        self.assertTrue(frame.empty)
        self.assertEqual(source, 'Unavailable')
        self.assertEqual(status[0]['Status'], 'Connection failed')
        alpha.assert_not_called()

    def test_alpha_response_identity_and_zero_retries(self):
        data = {'Meta Data': {'2. Symbol': 'AAPL'}, 'Time Series (Daily)': {'2026-10-09': {'4. close': '100'}}}
        with patch('src.market_prices._request_json', return_value=data) as request:
            self.assertEqual(alpha_daily('AAPL')[0]['close'], '100')
            self.assertEqual(request.call_args.kwargs['retries'], 0)
            with self.assertRaises(ValueError): alpha_daily('NVDA')

    def test_raw_yahoo_prices_not_strategy_adjusted_cache(self):
        ticker = Mock()
        ticker.history.return_value = pd.DataFrame({'Close': [100]}, index=pd.to_datetime(['2026-10-09']))
        with patch('src.market_prices.yf.Ticker', return_value=ticker):
            self.assertEqual(yahoo_daily('AAPL')[0]['close'], 100)
        self.assertFalse(ticker.history.call_args.kwargs['auto_adjust'])
        self.assertTrue(ticker.history.call_args.kwargs['raise_errors'])

    def test_all_sources_unavailable_no_false_price(self):
        with patch('src.market_prices.get_secret', return_value='private'), \
             patch('src.market_prices.yahoo_daily', return_value=[]), \
             patch('src.market_prices.alpha_daily', side_effect=RuntimeError('premium private')):
            frame, source, status = market_prices('AAPL', self.cache, self.now)
        self.assertTrue(frame.empty)
        self.assertEqual(source, 'Unavailable')
        self.assertEqual(status[-1]['Status'], 'Paid access required')

    def test_invalid_ticker_never_requests(self):
        with patch('src.market_prices.yahoo_daily') as request:
            with self.assertRaises(ValueError): market_prices('../env', self.cache)
        request.assert_not_called()

    def test_fresh_alpha_preferred_over_failed_yahoo_refresh(self):
        clock = [1000000]
        self.cache.now = lambda: clock[0]
        self.cache.get('Raw daily prices / Yahoo Finance', 'AAPL', lambda: self.rows, 3600)
        clock[0] += 3601
        with patch('src.market_prices.get_secret', return_value='private'), \
             patch('src.market_prices.yahoo_daily', side_effect=requests.Timeout()), \
             patch('src.market_prices.alpha_daily', return_value=self.rows):
            _, source, status = market_prices('AAPL', self.cache, self.now)
        self.assertEqual(source, 'Alpha Vantage')
        self.assertEqual(status[0]['Status'], 'Stale backup')

    def test_stale_success_used_only_when_no_fresh_source(self):
        clock = [1000000]
        self.cache.now = lambda: clock[0]
        self.cache.get('Raw daily prices / Yahoo Finance', 'AAPL', lambda: self.rows, 3600)
        clock[0] += 3601
        with patch('src.market_prices.get_secret', return_value=None), \
             patch('src.market_prices.yahoo_daily', side_effect=requests.Timeout()):
            frame, source, status = market_prices('AAPL', self.cache, self.now)
        self.assertFalse(frame.empty)
        self.assertEqual(source, 'Yahoo Finance')
        self.assertEqual(status[0]['Status'], 'Stale backup')
