from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.v3_accounting.intake import QUEUE, capture, public_issuer, inspect_dividends, inspect_prices
from src.v3_accounting.evidence import read_bundle

NOW = datetime.fromisoformat('2026-10-07T22:00:00+00:00')
SECRET = 'SYNTHETIC_ALPHA_KEY'
ISSUER = 'https://investor.nvidia.com/news/test'


class Response:
    def __init__(self, content, status=200):
        self.content, self.status_code = content, status
    def iter_content(self, size):
        yield self.content
    def close(self):
        pass


class Session:
    def __init__(self):
        self.calls = []
        self.price = {'chart': {'result': [{'meta': {'symbol': 'NVDA', 'currency': 'USD',
            'instrumentType': 'EQUITY', 'exchangeTimezoneName': 'America/New_York'},
            'timestamp': [1791379800], 'indicators': {'quote': [{'open': [100], 'close': [101]}]},
            'events': {}}]}}
        # Exact Oct 7 NY opening timestamp, no machine-local timezone assumption.
        self.price['chart']['result'][0]['timestamp'] = [int(datetime.fromisoformat('2026-10-07T13:30:00+00:00').timestamp())]
        self.dividends = {'symbol': 'NVDA', 'data': [{'ex_dividend_date': '2026-09-10', 'record_date': '2026-09-10',
            'declaration_date': '2026-08-26', 'payment_date': '2026-10-01', 'amount': '0.25'}]}
        self.issuer = b'SYNTHETIC announcement, not real evidence'
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        data = self.price if 'yahoo' in url else self.dividends if 'alphavantage' in url else self.issuer
        return Response(data if isinstance(data, bytes) else json.dumps(data).encode())


class IntakeTests(unittest.TestCase):
    def test_etf_type_requires_explicit_selection_and_matching_source(self):
        session=Session(); meta=session.price['chart']['result'][0]['meta']
        meta.update(symbol='SPY',instrumentType='ETF')
        data=json.dumps(session.price).encode()
        with self.assertRaises(ValueError): inspect_prices(data,'SPY','2026-10-07','CLOSE')
        self.assertEqual(inspect_prices(data,'SPY','2026-10-07','CLOSE','ETF')['observed_price'],101)
        with self.assertRaises(ValueError): inspect_prices(data,'NVDA','2026-10-07','CLOSE','ETF')
    def setUp(self):
        QUEUE.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=QUEUE)
        self.addCleanup(self.temp.cleanup)
        self.queue = Path(self.temp.name)
        self.session = Session()

    def capture(self, **kwargs):
        options = dict(ticker='NVDA', security_id='CLAIMED-NVDA-ID', trade_date='2026-10-07', kind='CLOSE',
                       issuer_urls=[ISSUER], alpha_key=SECRET, session=self.session, clock=lambda: NOW,
                       queue=self.queue)
        options.update(kwargs)
        return capture(**options)

    def test_complete_observations_still_pending_no_signature_or_ledger(self):
        result = self.capture()
        directory = Path(result['directory'])
        draft = json.loads((directory / 'draft.json').read_text())
        self.assertFalse(draft['approved'])
        self.assertFalse(draft['forward_eligible'])
        self.assertEqual(result['sources_saved'], 3)
        self.assertEqual(draft['observations']['price']['observed_price'], 101)
        for name in ['review.json', 'market.json', 'corporate_actions.sqlite3']:
            self.assertFalse((directory / name).exists())
        with self.assertRaises(FileNotFoundError):
            read_bundle(directory, 'x' * 32, NOW.isoformat())
        self.assertNotIn(SECRET, (directory / 'draft.json').read_text())
        self.assertTrue(all(not args['allow_redirects'] for _, args in self.session.calls))

    def test_repeat_is_immutable(self):
        first = self.capture()
        second = self.capture()
        self.assertEqual(first['directory'], second['directory'])
        self.assertEqual(len(list(self.queue.iterdir())), 1)

    def test_wrong_identity_and_null_price_flagged(self):
        meta = self.session.price['chart']['result'][0]['meta']
        meta['symbol'] = 'OTHER'
        self.assertIn('PRICE_SCHEMA_OR_IDENTITY_INVALID', self.capture()['review_required'])

    def test_empty_dividend_response_never_confirms_coverage(self):
        self.session.dividends = {'symbol': 'NVDA', 'data': []}
        result = self.capture()
        draft = json.loads((Path(result['directory']) / 'draft.json').read_text())
        self.assertFalse(draft['observations']['dividends']['coverage_confirmed'])

    def test_rate_limit_saved_but_not_treated_as_dividend_data(self):
        self.session.dividends = {'Information': 'SYNTHETIC quota error'}
        self.assertIn('DIVIDEND_SCHEMA_OR_DATES_REQUIRE_REVIEW', self.capture()['review_required'])

    def test_no_secret_echo_saved(self):
        self.session.dividends = {'error': SECRET}
        result = self.capture()
        self.assertIn('sources/alpha_dividends.json:SECRET_ECHO_REJECTED', result['review_required'])
        self.assertFalse((Path(result['directory']) / 'sources/alpha_dividends.json').exists())

    def test_missing_api_and_issuer_are_explicit(self):
        result = self.capture(alpha_key='', issuer_urls=[])
        self.assertIn('ALPHAVANTAGE_KEY_MISSING', result['review_required'])
        self.assertIn('ISSUER_ORIGINAL_MISSING', result['review_required'])

    def test_historical_retrieval_is_not_forward(self):
        later = datetime.fromisoformat('2026-10-08T22:00:00+00:00')
        result = self.capture(clock=lambda: later)
        self.assertIn('HISTORICAL_RETRIEVAL_NOT_FORWARD', result['review_required'])

    def test_premature_close_no_network(self):
        before = datetime.fromisoformat('2026-10-07T18:00:00+00:00')
        with self.assertRaises(ValueError):
            self.capture(clock=lambda: before)
        self.assertEqual(self.session.calls, [])

    def test_unsafe_urls_and_destination_rejected(self):
        for url in ['http://investor.nvidia.com/a', 'https://127.0.0.1/a',
                    'https://investor.nvidia.com/a?key=secret', 'https://evil.example/a']:
            with self.assertRaises(ValueError):
                public_issuer(url, {'investor.nvidia.com'})
        with self.assertRaisesRegex(ValueError, 'quarantine'):
            self.capture(queue=QUEUE.parent / 'integration')

    def test_contradictory_dividends_flagged(self):
        self.session.price['chart']['result'][0]['events'] = {'dividends': {'a': {
            'date': int(datetime.fromisoformat('2026-09-10T13:30:00+00:00').timestamp()), 'amount': .5}}}
        self.assertIn('YAHOO_ALPHA_DIVIDEND_MISMATCH', self.capture()['review_required'])

    def test_invalid_date_and_amount_rejected(self):
        self.session.dividends['data'][0]['payment_date'] = '2026-01-01'
        result = inspect_dividends(json.dumps(self.session.dividends).encode())
        self.assertEqual(result['candidates'], [])
        self.assertEqual(len(result['row_issues']), 1)

    def test_old_incomplete_records_do_not_discard_valid_records(self):
        self.session.dividends['data'].append({'ex_dividend_date': '2020-01-01', 'amount': '0.1'})
        result = self.capture()
        draft = json.loads((Path(result['directory']) / 'draft.json').read_text())
        self.assertEqual(len(draft['observations']['dividends']['candidates']), 1)
        self.assertEqual(len(draft['observations']['dividends']['row_issues']), 1)
        self.assertIn('DIVIDEND_RECORDS_INCOMPLETE_REQUIRES_SCOPED_REVIEW', result['review_required'])

    def test_dividend_symbol_mismatch_rejected(self):
        self.session.dividends['symbol'] = 'OTHER'
        self.assertIn('DIVIDEND_SCHEMA_OR_DATES_REQUIRE_REVIEW', self.capture()['review_required'])


if __name__ == '__main__':
    unittest.main()
