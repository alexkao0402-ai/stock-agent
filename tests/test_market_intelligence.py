import unittest
from unittest.mock import Mock, patch
import pandas as pd
import requests
from src.market_intelligence import market_payload, yahoo_overview, normalize_news, normalize_filings, search_news, valid_symbol
from src.stock_data import DataProviderError


class MarketIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.ticker = Mock()
        self.ticker.get_info.return_value = {'longName':'NVIDIA','marketCap':123,'grossMargins':.75,'operatingMargins':.4}
        self.ticker.get_news.return_value = []
        self.ticker.get_earnings_dates.return_value = None
        self.ticker.get_sec_filings.return_value = []
        self.patchers = [patch('src.market_intelligence.yf.Ticker',return_value=self.ticker),
                         patch('src.market_intelligence.get_long_history_stock_data',return_value=pd.DataFrame()),
                         patch('src.market_intelligence.get_secret',return_value=None),
                         patch('src.market_intelligence.search_news',return_value=[{'title':'News','url':'https://example.com'}])]
        for p in self.patchers:
            p.start(); self.addCleanup(p.stop)

    def test_free_sources_work_without_key(self):
        with patch('src.market_intelligence._request_json') as alpha:
            result=market_payload('NVDA')
        self.assertEqual(result['fundamentals_source'],'Yahoo Finance')
        self.assertEqual(result['news_source'],'Google News search')
        self.assertEqual(result['overview']['毛利率'],75)
        alpha.assert_not_called()

    def test_paid_denial_is_explicit_and_not_retried(self):
        self.ticker.get_info.return_value={}
        with patch('src.market_intelligence.get_secret',return_value='test-key'), patch('src.market_intelligence._request_json',side_effect=DataProviderError('premium endpoint test-key')) as alpha:
            result=market_payload('NVDA')
        self.assertIn('Paid access required',[r['Status'] for r in result['provider_status']])
        self.assertNotIn('test-key',str(result))
        alpha.assert_called_once()
        self.assertEqual(alpha.call_args.kwargs['retries'],0)

    def test_all_providers_fail_without_crash(self):
        self.ticker.get_info.side_effect=requests.Timeout('secret url')
        self.ticker.get_news.side_effect=RuntimeError('429 rate limit')
        self.ticker.get_sec_filings.side_effect=RuntimeError('down')
        self.ticker.get_earnings_dates.side_effect=RuntimeError('down')
        with patch('src.market_intelligence.search_news',side_effect=requests.ConnectionError('private')):
            result=market_payload('NVDA')
        self.assertFalse(result['overview']); self.assertFalse(result['news'])
        self.assertNotIn('private',str(result)); self.assertNotIn('secret url',str(result))
        self.assertIn('Rate limited',[r['Status'] for r in result['provider_status']])

    def test_partial_failure_keeps_news_and_filings(self):
        self.ticker.get_info.side_effect=RuntimeError('down')
        self.ticker.get_sec_filings.return_value={'filings':[{'type':'10-Q','date':'2026-09-01','edgarUrl':'https://sec.gov/a'}]}
        result=market_payload('NVDA')
        self.assertTrue(result['news']); self.assertEqual(result['filings'][0]['type'],'10-Q')

    def test_missing_values_not_zero(self):
        result=yahoo_overview({'longName':'Company','grossMargins':float('nan')})
        self.assertIsNone(result['毛利率']); self.assertIsNone(result['市值'])

    def test_news_shapes_deduplicate_and_reject_unsafe_links(self):
        nested={'content':{'title':'A','canonicalUrl':{'url':'https://example.com/a'},'provider':{'displayName':'Publisher'},'pubDate':'2026-10-08'}}
        flat={'title':'B','link':'https://example.com/b','providerPublishTime':1791500000}
        rows=normalize_news([nested,nested,flat,{'title':'bad','url':'javascript:alert(1)'},None])
        self.assertEqual(len(rows),2); self.assertEqual(rows[0]['source'],'Publisher')

    def test_filings_dictionary_and_list(self):
        items=[{'date':'2026-10-01','type':'8-K','edgarUrl':'https://sec.gov/a'}]
        self.assertEqual(normalize_filings(items),normalize_filings({'filings':items}))
        self.assertEqual(normalize_filings(None),[])

    def test_symbol_rejected_before_network(self):
        for symbol in ('../secret','NVDA?x=y','', 'aapl'):
            self.assertFalse(valid_symbol(symbol))
            with self.assertRaises(ValueError):market_payload(symbol)
        for symbol in ('NVDA','BRK-B','^GSPC'):
            self.assertTrue(valid_symbol(symbol))

    def test_rss_parsing_and_timeout(self):
        # Stop the default mock for this individual parser check.
        from src import market_intelligence as module
        real_search=search_news
        response=Mock(content=b'<rss><channel><item><title>Headline</title><link>https://news.google.com/a</link><pubDate>Thu, 08 Oct 2026 15:00:00 GMT</pubDate><source>Publisher</source></item></channel></rss>')
        with patch.object(module.requests,'get',return_value=response) as request:
            rows=real_search('NVDA','NVIDIA')
        self.assertEqual(rows[0]['source'],'Publisher')
        self.assertEqual(request.call_args.kwargs['timeout'],15)
        self.assertEqual(rows[0]['overall_sentiment_label'],'Not scored')


class MarketPageTests(unittest.TestCase):
    def test_no_prices_does_not_hide_other_sections(self):
        from streamlit.testing.v1 import AppTest
        payload={'prices':pd.DataFrame(),'overview':{'公司名稱':'NVIDIA'},
                 'news':[{'title':'Test headline','source':'Publisher','url':'https://example.com','time_published':'2026-10-08'}],
                 'filings':[],'earnings':[],'source':'Yahoo Finance','fundamentals_source':'Yahoo Finance',
                 'news_source':'Google News search','fetched_at':'2026-10-08T00:00:00Z','provider_status':[]}
        with patch('app._market_payload',return_value=payload):
            at=AppTest.from_string('from app import render_market\nrender_market()')
            at.session_state['market_symbol']='NVDA'
            at.run(timeout=20)
        self.assertFalse(at.exception)
        self.assertTrue(any('Test headline' in item.value for item in at.markdown))
        self.assertTrue(any('Earnings & Fundamentals' in item.value for item in at.markdown))

    def test_invalid_input_does_not_load_data(self):
        from streamlit.testing.v1 import AppTest
        with patch('app._market_payload') as load:
            at=AppTest.from_string('from app import render_market\nrender_market()').run()
            at.text_input[0].set_value('../secret')
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertTrue(at.warning)
            load.assert_not_called()


if __name__=='__main__':unittest.main()
