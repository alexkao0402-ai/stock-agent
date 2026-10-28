import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
import pandas as pd
import json
from datetime import datetime
from src.v3_accounting.signal import rank_features,indicators,validate_time,immutable,ROOT,freeze,generate,digest,is_session

class ShadowTests(unittest.TestCase):
    def features(self):
        return pd.DataFrame({'momentum_3_1':[.1,.2,.3,.4], 'momentum_6_1':[.1,.2,.3,.4], 'momentum_12_1':[.1,.2,.3,.4],
                             'exact_month_end_price':[True]*4,'above_ma200':[True]*4})
    def test_top3_and_reserve(self):
        r=rank_features(self.features(),True)
        self.assertEqual(r.selected.tolist(),[False,True,True,True]);self.assertAlmostEqual(r.target_weight.sum(),.95)
    def test_cash_regime(self):self.assertEqual(rank_features(self.features(),False).target_weight.sum(),0.)
    def test_price_future_invariance(self):
        dates=pd.bdate_range('2025-01-01',periods=260)
        p=pd.DataFrame({'trade_date':dates.strftime('%Y-%m-%d'),'adjusted_close':range(100,360)})
        date=p.trade_date.iloc[-2];a=indicators(p,date);p.loc[len(p)-1,'adjusted_close']=1e9
        self.assertEqual(a,indicators(p,date))
    def test_no_backfilled_forward(self):
        with self.assertRaises(ValueError):validate_time('2026-09-30','2026-10-01T03:00:00Z','2026-10-06T00:00:00Z','2026-10-06T01:00:00Z')
        validate_time('2026-10-30','2026-10-30T21:00:00Z','2026-10-06T00:00:00Z','2026-10-30T22:00:00Z')
    def test_immutable(self):
        with TemporaryDirectory(dir=ROOT) as tmp:
            p=Path(tmp)/'event.json';self.assertTrue(immutable(p,{'a':1}));self.assertFalse(immutable(p,{'a':1}))
            with self.assertRaises(ValueError):immutable(p,{'a':2})

    def bundle(self,tmp):
        bundle=Path(tmp)/'input';bundle.mkdir()
        date='2026-10-30';captured='2026-10-30T21:00:00+00:00'
        days=[d.strftime('%Y-%m-%d') for d in pd.date_range('2025-01-01',date) if is_session(d)]
        tickers=[f'S{i}' for i in range(10)]
        pd.DataFrame([{'signal_date':date,'market_cap_rank':i+1,'ticker':t,'stable_company_id':f'C{i}',
                       'stable_security_id':t,'company_market_cap':1000-i,'source_timestamp':captured}
                      for i,t in enumerate(tickers)]).to_csv(bundle/'monthly_universe.csv',index=False)
        pd.DataFrame([{'ticker':t,'stable_security_id':t,'trade_date':day,'adjusted_close':100+j*(i+1)/100,
                       'source_timestamp':captured} for i,t in enumerate(tickers+['SPY']) for j,day in enumerate(days)]).to_csv(bundle/'daily_prices.csv',index=False)
        manifest={'signal_date':date,'captured_at':captured,'files':{f:digest(bundle/f) for f in ['monthly_universe.csv','daily_prices.csv']}}
        (bundle/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        store=Path(tmp)/'shadow';freeze(store,datetime.fromisoformat('2026-10-06T00:00:00+00:00'))
        return bundle,store

    def test_timely_signal_and_late_retry(self):
        with TemporaryDirectory(dir=ROOT) as tmp:
            bundle,store=self.bundle(tmp)
            first=generate(bundle,store,datetime.fromisoformat('2026-10-30T22:00:00+00:00'))
            self.assertTrue(first['created']);self.assertEqual(len(first['payload']['target_weights']),3)
            self.assertAlmostEqual(first['payload']['target_cash_weight'],.05)
            retry=generate(bundle,store,datetime.fromisoformat('2026-11-03T22:00:00+00:00'))
            self.assertFalse(retry['created']);self.assertEqual(first['payload'],retry['payload'])

    def test_tampered_bundle_rejected(self):
        with TemporaryDirectory(dir=ROOT) as tmp:
            bundle,store=self.bundle(tmp)
            with (bundle/'daily_prices.csv').open('a',encoding='utf-8') as handle:handle.write('\n')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                generate(bundle,store,datetime.fromisoformat('2026-10-30T22:00:00+00:00'))
            self.assertFalse((store/'signals').exists())

    def test_first_late_signal_rejected(self):
        with TemporaryDirectory(dir=ROOT) as tmp:
            bundle,store=self.bundle(tmp)
            with self.assertRaisesRegex(ValueError,'timely'):
                generate(bundle,store,datetime.fromisoformat('2026-11-03T22:00:00+00:00'))

if __name__=='__main__':unittest.main()
