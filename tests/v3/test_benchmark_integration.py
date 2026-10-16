import unittest
from tests.v3 import test_runner as fixtures
from src.v3_accounting.accounting import Journal
from src.v3_accounting.evidence import digest


class IntegratedBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): fixtures.IntegrationTests.setUpClass()
    @classmethod
    def tearDownClass(cls): fixtures.IntegrationTests.tearDownClass()
    def setUp(self):
        self.f=fixtures.IntegrationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
    def accounts(self): return Journal(self.f.store).inspect()['state']['benchmarks']
    def test_common_initial_boundary_and_costs(self):
        opening,_=self.f.market(); result=self.f.process(opening)
        accounts=self.accounts()
        for ticker in ['SPY','QQQ']:
            self.assertEqual(accounts[ticker]['initial_capital'],10000)
            self.assertEqual(accounts[ticker]['start_at'],result['valuation']['effective_at'])
            self.assertLess(result['benchmarks'][ticker]['equity'],10000)
            self.assertGreater(accounts[ticker]['state']['fees'],0)
        self.assertAlmostEqual(result['benchmarks']['SPY']['equity'],result['benchmarks']['QQQ']['equity'])
    def test_missing_definitions_and_price_fail_atomically(self):
        opening,market=self.f.market(); before=Journal(self.f.store).inspect()
        market.pop('benchmarks'); self.f.save(opening,market)
        with self.assertRaisesRegex(ValueError,'definitions'): self.f.process(opening)
        self.assertEqual(before,Journal(self.f.store).inspect())
        opening,market=self.f.market(); market['marks'].pop('ETF-QQQ'); self.f.save(opening,market)
        with self.assertRaisesRegex(ValueError,'coverage or marks'): self.f.process(opening)
        self.assertEqual(before,Journal(self.f.store).inspect())
    def test_identity_source_must_be_bound(self):
        opening,market=self.f.market(); market['benchmarks']['SPY']['identity_source_sha256']='f'*64
        self.f.save(opening,market)
        with self.assertRaisesRegex(ValueError,'identity source'): self.f.process(opening)
        self.assertEqual(Journal(self.f.store).inspect()['events'],1)
    def ex(self,directory,security='ETF-SPY',day='2026-11-03'):
        at=day+'T14:30:00+00:00'; dividend='DIV:'+security+':'+at
        return {'kind':'EX_DIVIDEND','event_key':dividend+':EX','dividend_id':dividend,
            'security_id':security,'effective_at':at,'pay_at':'2026-11-04T14:30:00+00:00',
            'amount_per_share':1,'currency':'USD','dividend_type':'ORDINARY_CASH',
            'announced_at':'2026-10-29T12:00:00+00:00',
            'evidence_sha256':digest(directory/'sources/announcement.txt')}
    def entitlement(self):
        self.f.first_close()
        directory,market=self.f.market('CLOSE','2026-11-03','2026-11-02T21:00:00Z')
        market['marks']['ETF-SPY']=499; market['actions']=[self.ex(directory)]
        self.f.save(directory,market)
        self.f.process(directory,'CLOSE','2026-11-03T21:02:00Z')
        return market['actions'][0]['dividend_id']
    def test_receivable_then_payment_no_double_profit_or_reinvestment(self):
        dividend=self.entitlement(); before=self.accounts()['SPY']['state']
        shares=before['positions']['ETF-SPY']['shares']
        self.assertAlmostEqual(before['last_valuation']['receivable'],shares)
        self.assertLess(before['cash'],1e-6)
        directory,market=self.f.market('CLOSE','2026-11-04','2026-11-03T21:00:00Z')
        market['marks']['ETF-SPY']=499
        market['actions']=[{'kind':'PAY_DIVIDEND','event_key':dividend+':PAY','dividend_id':dividend,
            'security_id':'ETF-SPY','effective_at':'2026-11-04T14:30:00+00:00',
            'evidence_sha256':digest(directory/'sources/announcement.txt')}]
        self.f.save(directory,market)
        result=self.f.process(directory,'CLOSE','2026-11-04T21:02:00Z')
        after=self.accounts()['SPY']['state']
        self.assertAlmostEqual(after['cash']-before['cash'],shares)
        self.assertEqual(after['positions'],before['positions'])
        self.assertEqual(after['last_valuation']['equity'],before['last_valuation']['equity'])
        count=Journal(self.f.store).inspect()['events']
        self.assertFalse(self.f.process(directory,'CLOSE','2026-11-05T22:00:00Z')['created'])
        self.assertEqual(count,Journal(self.f.store).inspect()['events'])
    def test_benchmark_missing_payment_rolls_back_all_three_accounts(self):
        self.entitlement(); before=Journal(self.f.store).inspect()
        directory,_=self.f.market('CLOSE','2026-11-04','2026-11-03T21:00:00Z')
        with self.assertRaisesRegex(ValueError,'Benchmark due'):
            self.f.process(directory,'CLOSE','2026-11-04T21:02:00Z')
        self.assertEqual(before,Journal(self.f.store).inspect())
    def test_identity_changed_midstream_stops_entire_batch(self):
        self.f.first_close(); before=Journal(self.f.store).inspect()
        directory,market=self.f.market('CLOSE','2026-11-03','2026-11-02T21:00:00Z')
        market['benchmarks']['SPY']['security_id']='NEW-SPY'
        market['marks']['NEW-SPY']=500; market['coverage']['security_ids'].append('NEW-SPY')
        self.f.save(directory,market)
        with self.assertRaisesRegex(ValueError,'definition changed'):
            self.f.process(directory,'CLOSE','2026-11-03T21:02:00Z')
        self.assertEqual(before,Journal(self.f.store).inspect())
    def test_first_open_ex_date_does_not_get_past_dividend(self):
        directory,market=self.f.market()
        market['actions']=[self.ex(directory,day='2026-11-02')]
        self.f.save(directory,market); self.f.process(directory)
        self.assertEqual(self.accounts()['SPY']['state']['dividends_earned'],0)
    def test_second_benchmark_failure_does_not_commit_first(self):
        self.f.first_close(); before=Journal(self.f.store).inspect()
        directory,market=self.f.market('CLOSE','2026-11-03','2026-11-02T21:00:00Z')
        market['marks']['ETF-SPY']=550
        market['actions']=[{'kind':'PAY_DIVIDEND','event_key':'INVALID-QQQ-PAY',
            'dividend_id':'UNKNOWN','security_id':'ETF-QQQ',
            'effective_at':'2026-11-03T14:30:00+00:00',
            'evidence_sha256':digest(directory/'sources/announcement.txt')}]
        self.f.save(directory,market)
        with self.assertRaisesRegex(ValueError,'Missing'):
            self.f.process(directory,'CLOSE','2026-11-03T21:02:00Z')
        self.assertEqual(before,Journal(self.f.store).inspect())
    def test_close_marks_do_not_rebalance_benchmarks(self):
        self.f.first_close(); before=self.accounts()
        directory,market=self.f.market('CLOSE','2026-11-03','2026-11-02T21:00:00Z')
        market['marks']['ETF-SPY']=550; self.f.save(directory,market)
        self.f.process(directory,'CLOSE','2026-11-03T21:02:00Z')
        after=self.accounts()
        for ticker in ['SPY','QQQ']:
            self.assertEqual(before[ticker]['state']['positions'],after[ticker]['state']['positions'])
            self.assertEqual(before[ticker]['state']['fees'],after[ticker]['state']['fees'])


if __name__=='__main__': unittest.main()
