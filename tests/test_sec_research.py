from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.sec_research import reported_financials, sec_context, filing_url
from src.market_intelligence import relevant_news
from src.research_cache import ResearchCache


class HeadlineTests(unittest.TestCase):
    def rows(self, titles, when='2026-10-12T12:00:00Z'):
        return [{'title': t, 'url': 'https://example.com/' + str(i), 'time_published': when} for i, t in enumerate(titles)]

    def filter(self, titles, symbol='NVDA', company='NVIDIA Corporation'):
        return relevant_news(self.rows(titles), symbol, company, datetime(2026, 10, 12, 16, tzinfo=timezone.utc))

    def test_only_explicit_company_matches(self):
        result = self.filter(['Nvidia announces earnings', 'NVDA stock falls', 'Technology stocks rise', 'NVDAA launches product', 'Markets today - NVIDIA'])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r['relevance_reason'] for r in result))

    def test_ambiguous_company_names_need_context(self):
        self.assertEqual(len(self.filter(['Apple pie recipe', 'Apple earnings grow', '$AAPL gains'], 'AAPL', 'Apple Inc.')), 2)
        self.assertEqual(self.filter(['COST of living increases'], 'COST', 'Costco Wholesale Corporation'), [])
        self.assertEqual(self.filter(['Meta study on cancer'], 'META', 'Meta Platforms, Inc.'), [])
        self.assertEqual(self.filter(['FAST cars on the road'], 'FAST', None), [])

    def test_dates_links_and_duplicates(self):
        now = datetime(2026, 10, 12, 16, tzinfo=timezone.utc)
        rows = self.rows(['NVIDIA earnings', 'NVIDIA earnings'])
        rows += self.rows(['NVDA old'], '2026-10-01') + self.rows(['NVDA future'], '2026-10-13') + self.rows(['NVDA unknown'], '')
        rows += [{'title': 'NVDA bad', 'url': 'javascript:alert(1)', 'time_published': '2026-10-12'}]
        self.assertEqual(len(relevant_news(rows, 'NVDA', 'NVIDIA', now)), 1)

    def test_alpha_date_and_ticker_boundaries(self):
        rows = self.rows(['NASDAQ: T beats earnings'], '20261012T120000')
        self.assertEqual(len(relevant_news(rows, 'T', None, datetime(2026,10,12,16,tzinfo=timezone.utc))), 1)
        self.assertEqual(self.filter(['The market is up'], 'T', None), [])


class SecTests(unittest.TestCase):
    def fact(self, **overrides):
        return {'val': 100, 'start': '2026-04-01', 'end': '2026-06-30', 'filed': '2026-08-01',
                'form': '10-Q', 'accn': '0000000001-26-000001', **overrides}

    def test_periods_not_mislabeled_ttm_and_future_filings_excluded(self):
        facts = {'cik': 1, 'facts': {'us-gaap': {
            'Revenues': {'units': {'USD': [self.fact(start='2026-01-01', val=200), self.fact(), self.fact(filed='2026-11-01', val=999)]}},
            'EarningsPerShareDiluted': {'units': {'USD/shares': [self.fact(val=2)]}},
            'Assets': {'units': {'USD': [self.fact(start=None, val=300)]}}}}}
        rows = reported_financials(facts, 1, date(2026,10,12))
        self.assertEqual([r['Value'] for r in rows], [100, 2, 300])
        self.assertEqual(rows[0]['Period start'], '2026-04-01')
        self.assertEqual(rows[2]['Period start'], 'Instant')
        with self.assertRaises(ValueError): reported_financials(facts, 2)

    def test_invalid_units_values_and_source_rejected(self):
        facts = {'cik': 1, 'facts': {'us-gaap': {'Revenues': {'units': {
            'EUR': [self.fact()], 'USD': [self.fact(val=float('nan')), self.fact(accn='bad'), self.fact(end='invalid')]}}}}}
        self.assertEqual(reported_financials(facts, 1), [])
        self.assertNotIn('../', filing_url(1, '0000000001-26-000001', '../../secret'))

    def test_missing_user_agent_does_not_request(self):
        with patch('src.sec_research.get_secret', return_value=None), patch('src.sec_research.requests.get') as request:
            self.assertIn('not configured', sec_context('NVDA', None)['status'])
        request.assert_not_called()

    def test_financials_failure_keeps_filings(self):
        directory = {'0': {'cik_str': 1, 'ticker': 'NVDA', 'title': 'NVIDIA'}}
        submission = {'cik': 1, 'name': 'NVIDIA', 'tickers': ['NVDA'], 'filings': {'recent': {
            'form': ['10-Q'], 'filingDate': ['2026-08-01'], 'accessionNumber': ['0000000001-26-000001'], 'primaryDocument': ['report.htm']}}}
        with patch('src.sec_research.get_secret', return_value='Research contact@university.edu'):
            def cache(section, key, loader, ttl):
                if section == 'SEC financials': raise RuntimeError('private provider message')
                return directory if section == 'SEC ticker directory' else submission
            result = sec_context('NVDA', cache)
        self.assertEqual(len(result['filings']), 1)
        self.assertFalse(result['financials'])
        self.assertNotIn('private provider message', str(result))


class CacheTests(unittest.TestCase):
    def test_fresh_stale_cooldown_and_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = [1000000]
            cache = ResearchCache(directory, lambda: clock[0])
            self.assertEqual(cache.get('news', 'NVDA', lambda: ['ok'], 60), ['ok'])
            clock[0] += 61
            def fail(): raise RuntimeError('secret')
            self.assertEqual(cache.get('news', 'NVDA', fail, 60), ['ok'])
            self.assertIn('Stale', cache.metadata[-1]['Status'])
            with patch('builtins.print'):
                self.assertEqual(cache.get('news', 'NVDA', lambda: self.fail('cooldown ignored'), 60), ['ok'])
            clock[0] += 8 * 86400
            with self.assertRaises(RuntimeError): cache.get('news', 'NVDA', fail)

    def test_corrupt_cache_and_future_timestamp_refetch(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = ResearchCache(directory, lambda: 100)
            cache.get('facts', '1', lambda: {'good': True})
            path = next(Path(directory).glob('*.json'))
            path.write_text('{bad', encoding='utf-8')
            self.assertEqual(cache.get('facts', '1', lambda: {'new': True}), {'new': True})
            path.write_text('[]', encoding='utf-8')
            self.assertEqual(cache.get('facts', '1', lambda: {'new': True}), {'new': True})
            path.write_text(json.dumps({'saved_at': 999, 'data': {'future': True}}), encoding='utf-8')
            self.assertEqual(cache.get('facts', '1', lambda: {'correct': True}), {'correct': True})
