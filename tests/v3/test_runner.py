import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
from tests.v3 import signal_fixtures as fixtures
from src.v3_accounting.accounting import ROOT, Journal
from src.v3_accounting.evidence import digest, signature
from src.v3_accounting.runner import Runner
from src.v3_accounting.payment_policy import POLICY
from src.trading_calendar import previous_session

KEY='SYNTHETIC-TEST-KEY-NOT-A-REAL-SECRET-12345'


def dt(value):return datetime.fromisoformat(value.replace('Z','+00:00'))


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=ROOT/'shadow_forward/V3_ACCOUNTING/rehearsals';base.mkdir(parents=True,exist_ok=True)
        cls.shared=TemporaryDirectory(dir=base)
        cls.shared_bundle,_=fixtures.ShadowTests().bundle(cls.shared.name)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        base=ROOT/'shadow_forward/V3_ACCOUNTING/rehearsals';base.mkdir(parents=True,exist_ok=True)
        self.temp=TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.bundle=self.shared_bundle
        self.store=Path(self.temp.name)/'v3'
        self.runner=Runner(self.store);self.runner.init(dt('2026-10-07T06:00:00Z'))
        self.signal=self.runner.signal(self.bundle,dt('2026-10-30T22:00:00Z'))['payload']

    def market(self,kind='OPEN',date='2026-11-02',start='2026-10-07T06:00:00+00:00'):
        hour='14:30:00' if kind=='OPEN' else '21:00:00'
        boundary=f'{date}T{hour}+00:00';captured=f'{date}T'+('14:31:00' if kind=='OPEN' else '21:01:00')+'+00:00'
        directory=Path(self.temp.name)/f'{kind}-{date}';directory.mkdir(exist_ok=True)
        (directory/'sources').mkdir(exist_ok=True)
        (directory/'sources/price.txt').write_text('SYNTHETIC raw prices, NOT REAL MARKET DATA')
        (directory/'sources/announcement.txt').write_text('SYNTHETIC ordinary cash dividend declaration')
        (directory/'sources/etf_identity.txt').write_text('SYNTHETIC SPY/QQQ USD ETF identities, NOT REAL DATA')
        market={'schema_version':1,'date':date,'kind':kind,'price_basis':'RAW',
                'data_asof':captured,'captured_at':captured,
                'price_source_sha256':digest(directory/'sources/price.txt'),
                'marks':{f'S{i}':100.+i for i in range(10)},
                'coverage':{'confirmed':True,'from':start,'through':boundary,
                            'security_ids':[f'S{i}' for i in range(10)]+['ETF-SPY','ETF-QQQ']},'actions':[],
                'benchmarks':{t:{'security_id':'ETF-'+t,'instrument_type':'ETF','currency':'USD',
                    'identity_source_sha256':digest(directory/'sources/etf_identity.txt')} for t in ['SPY','QQQ']}}
        market['marks'].update({'ETF-SPY':500.,'ETF-QQQ':400.})
        self.save(directory,market)
        return directory,market

    def save(self,directory,market):
        # Synthetic fixtures explicitly provide issuer dates under the new policy.
        for action in market['actions']:
            if action['kind']=='EX_DIVIDEND' and 'cash_policy' not in action:
                action['cash_policy']=POLICY
                action['issuer_payment_date']=previous_session(action['pay_at'][:10]).isoformat()
        (directory/'market.json').write_text(json.dumps(market),encoding='utf-8')
        payload={'approved':True,'reviewer':'SYNTHETIC_TEST_ONLY','coverage_note':'Synthetic complete coverage',
                 'reviewed_at':market['captured_at'],'files':{name:digest(directory/name) for name in
                      ['market.json','sources/price.txt','sources/announcement.txt','sources/etf_identity.txt']}}
        (directory/'review.json').write_text(json.dumps({'payload':payload,'signature':signature(payload,KEY)}))

    def process(self,directory,kind='OPEN',now='2026-11-02T14:32:00Z'):
        return self.runner.process(directory,KEY,signal_bundle=self.bundle if kind=='OPEN' else None,now=dt(now))

    def first_close(self):
        opening,_=self.market();self.process(opening)
        close,_=self.market('CLOSE',start='2026-11-02T14:30:00Z');self.process(close,'CLOSE','2026-11-02T21:02:00Z')

    def test_full_t1_close_entitlement_payment_retries(self):
        opening,_=self.market();result=self.process(opening)
        self.assertAlmostEqual(result['valuation']['equity'],9985.74525)
        close,_=self.market('CLOSE',start='2026-11-02T14:30:00Z');self.process(close,'CLOSE','2026-11-02T21:02:00Z')
        state=Journal(self.store).inspect()['state'];security=next(iter(state['positions']))
        shares=state['positions'][security]['shares'];cash=state['cash']
        ex_at='2026-11-03T14:30:00+00:00';dividend_id='DIV:'+security+':'+ex_at
        exdir,market=self.market('CLOSE','2026-11-03','2026-11-02T21:00:00Z')
        market['marks'][security]-=1
        market['actions']=[{'kind':'EX_DIVIDEND','event_key':dividend_id+':EX','dividend_id':dividend_id,
                            'security_id':security,'effective_at':ex_at,'pay_at':'2026-11-04T14:30:00+00:00',
                            'amount_per_share':1,'currency':'USD','dividend_type':'ORDINARY_CASH',
                            'announced_at':'2026-10-29T12:00:00+00:00',
                            'evidence_sha256':digest(exdir/'sources/announcement.txt')}]
        self.save(exdir,market)
        result=self.process(exdir,'CLOSE','2026-11-03T21:02:00Z')
        self.assertAlmostEqual(result['valuation']['cash'],cash)
        self.assertAlmostEqual(result['valuation']['receivable'],shares)
        self.assertAlmostEqual(result['valuation']['equity'],9985.74525)
        paydir,market=self.market('CLOSE','2026-11-04','2026-11-03T21:00:00Z');market['marks'][security]-=1
        market['actions']=[{'kind':'PAY_DIVIDEND','event_key':dividend_id+':PAY','dividend_id':dividend_id,
                            'security_id':security,'effective_at':'2026-11-04T14:30:00+00:00',
                            'evidence_sha256':digest(paydir/'sources/announcement.txt')}]
        self.save(paydir,market);result=self.process(paydir,'CLOSE','2026-11-04T21:02:00Z')
        self.assertAlmostEqual(result['valuation']['cash'],cash+shares)
        self.assertEqual(result['valuation']['receivable'],0)
        reopened=Runner(self.store)
        self.assertFalse(reopened.process(opening,KEY,signal_bundle=self.bundle,now=dt('2026-11-05T22:00:00Z'))['created'])
        self.assertFalse(reopened.process(paydir,KEY,now=dt('2026-11-05T22:00:00Z'))['created'])
        self.assertEqual(Journal(self.store).inspect()['events'],5)

    def test_bad_signature_no_mutation(self):
        directory,_=self.market();before=Journal(self.store).inspect()
        with self.assertRaisesRegex(ValueError,'signature'):self.runner.process(directory,'b'*40,signal_bundle=self.bundle,now=dt('2026-11-02T14:32:00Z'))
        self.assertEqual(Journal(self.store).inspect(),before)

    def test_tampered_source_and_market_rejected(self):
        directory,_=self.market();(directory/'sources/price.txt').write_text('TAMPERED')
        with self.assertRaisesRegex(ValueError,'hash'):self.process(directory)
        self.assertEqual(Journal(self.store).inspect()['events'],1)

    def test_missing_coverage_rolls_back_whole_batch(self):
        directory,market=self.market();market['coverage']['security_ids']=[];self.save(directory,market)
        with self.assertRaisesRegex(ValueError,'coverage'):self.process(directory)
        self.assertEqual(Journal(self.store).inspect()['events'],1)

    def test_unsupported_event_rolls_back(self):
        directory,market=self.market();market['actions']=[{'kind':'MERGER','event_key':'M',
            'security_id':next(iter(self.signal['target_weights'])),'effective_at':'2026-11-02T14:30:00+00:00',
            'evidence_sha256':digest(directory/'sources/announcement.txt')}];self.save(directory,market)
        with self.assertRaisesRegex(ValueError,'Unsupported'):self.process(directory)
        self.assertEqual(Journal(self.store).inspect()['events'],1)

    def test_missing_execution_close_rejected(self):
        opening,_=self.market();self.process(opening)
        directory,_=self.market('CLOSE','2026-11-03','2026-11-02T14:30:00Z')
        with self.assertRaisesRegex(ValueError,'execution-day'):self.process(directory,'CLOSE','2026-11-03T21:02:00Z')

    def test_changed_retry_is_conflict(self):
        opening,market=self.market();self.process(opening)
        market['marks']['S7']+=1;self.save(opening,market)
        with self.assertRaisesRegex(ValueError,'conflict'):self.process(opening)
        self.assertEqual(Journal(self.store).inspect()['events'],2)

    def test_missing_review_key_and_future_review_rejected(self):
        directory,_=self.market()
        with self.assertRaisesRegex(ValueError,'review key'):self.runner.process(directory,'',signal_bundle=self.bundle)
        with self.assertRaisesRegex(ValueError,'availability'):self.process(directory,now='2026-11-02T14:30:00Z')

    def test_due_payment_missing_rolls_back_entitlement(self):
        self.first_close()
        directory,market=self.market('CLOSE','2026-11-03','2026-11-02T21:00:00Z')
        security=next(iter(Journal(self.store).inspect()['state']['positions']))
        ex_at='2026-11-03T14:30:00+00:00';dividend_id='DIV:'+security+':'+ex_at
        market['actions']=[{'kind':'EX_DIVIDEND','event_key':dividend_id+':EX','dividend_id':dividend_id,
                           'security_id':security,'effective_at':ex_at,'pay_at':'2026-11-04T14:30:00+00:00','amount_per_share':1,
                           'currency':'USD','dividend_type':'ORDINARY_CASH',
                           'announced_at':'2026-10-29T12:00:00+00:00',
                           'evidence_sha256':digest(directory/'sources/announcement.txt')}]
        self.save(directory,market)
        self.process(directory,'CLOSE','2026-11-03T21:02:00Z')
        next_directory,_=self.market('CLOSE','2026-11-04','2026-11-03T21:00:00Z')
        before=Journal(self.store).inspect()
        with self.assertRaisesRegex(ValueError,'Due dividend'):self.process(next_directory,'CLOSE','2026-11-04T21:02:00Z')
        self.assertEqual(Journal(self.store).inspect(),before)

    def test_mid_batch_failure_no_partial_receivable(self):
        self.first_close()
        directory,market=self.market('CLOSE','2026-11-03','2026-11-02T21:00:00Z')
        security=next(iter(Journal(self.store).inspect()['state']['positions']))
        ex_at='2026-11-03T14:30:00+00:00';dividend_id='DIV:'+security+':'+ex_at
        sha=digest(directory/'sources/announcement.txt')
        market['actions']=[{'kind':'EX_DIVIDEND','event_key':dividend_id+':EX','dividend_id':dividend_id,
                           'security_id':security,'effective_at':ex_at,'pay_at':'2026-11-04T14:30:00+00:00',
                           'amount_per_share':1,'currency':'USD','dividend_type':'ORDINARY_CASH',
                           'announced_at':'2026-10-29T12:00:00+00:00','evidence_sha256':sha},
                          {'kind':'PAY_DIVIDEND','event_key':'BAD-PAY','dividend_id':'UNKNOWN',
                           'security_id':security,'effective_at':ex_at,'evidence_sha256':sha}]
        self.save(directory,market);before=Journal(self.store).inspect()
        with self.assertRaisesRegex(ValueError,'Missing'):self.process(directory,'CLOSE','2026-11-03T21:02:00Z')
        self.assertEqual(Journal(self.store).inspect(),before)

    def test_source_originals_archived(self):
        directory,_=self.market();self.process(directory)
        archives=list((self.store/'evidence').glob('*/sources/price.txt'))
        self.assertEqual(len(archives),1)
        self.assertEqual(archives[0].read_bytes(),(directory/'sources/price.txt').read_bytes())

    def test_historical_capture_rejected(self):
        directory,market=self.market();market['captured_at']='2026-11-03T14:31:00+00:00'
        self.save(directory,market)
        with self.assertRaisesRegex(ValueError,'Historical'):
            self.process(directory,now='2026-11-03T14:32:00Z')


if __name__=='__main__':unittest.main()
