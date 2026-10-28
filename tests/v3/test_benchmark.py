import unittest
from src.v3_accounting.benchmark import open_benchmark, apply_benchmark
from tests.v3.test_accounting import event
from src.v3_accounting.payment_policy import annotate_ex_dividend
from src.v3_accounting.accounting import equity


class BenchmarkTests(unittest.TestCase):
    def opened(self, ticker='SPY'):
        return open_benchmark(10000, ticker, 'ETF-ID', 100,
            event('TRADE', 'ENTRY', 1, security_id='ETF-ID'),
            v3_execution_at='2026-10-01T13:30:00Z', commission=.001, slippage=.0005)

    def test_both_accounts_same_capital_costs_and_start(self):
        spy=self.opened(); qqq=self.opened('QQQ')
        self.assertEqual(spy['state'], qqq['state'])
        self.assertLess(equity(spy['state'], {'ETF-ID':100}),10000)
        self.assertGreater(spy['state']['fees'],0)
        self.assertAlmostEqual(spy['entry_fill']['fee'],spy['state']['fees'])
        self.assertGreater(spy['entry_fill']['slippage'],0)
        self.assertLess(spy['state']['cash'],1e-6)

    def test_wrong_start_and_saved_fill_rejected(self):
        for extra in ({'effective_at':'2026-10-02T13:30:00Z'}, {'quantity':1}):
            with self.assertRaises(ValueError):
                open_benchmark(10000,'SPY','ETF-ID',100,
                    event('TRADE','ENTRY',1,security_id='ETF-ID',**extra),
                    v3_execution_at='2026-10-01T13:30:00Z',commission=.001,slippage=.0005)

    def test_dividend_receivable_then_cash_no_reinvestment(self):
        account=self.opened(); shares=account['state']['positions']['ETF-ID']['shares']
        ex=annotate_ex_dividend(event('EX_DIVIDEND','EX',2,security_id='ETF-ID',
            dividend_id='DIV-ETF',amount_per_share=1,currency='USD',
            dividend_type='ORDINARY_CASH'),'2026-10-05')
        before=account['state']['cash']; account=apply_benchmark(account,ex)
        self.assertEqual(account['state']['cash'],before)
        pay=event('PAY_DIVIDEND','PAY',6,security_id='ETF-ID',dividend_id='DIV-ETF')
        account=apply_benchmark(account,pay)
        self.assertAlmostEqual(account['state']['cash']-before,shares)
        self.assertEqual(account['state']['positions']['ETF-ID']['shares'],shares)
        self.assertEqual(apply_benchmark(account,pay),account)

    def test_split_and_no_rebalance_or_other_security(self):
        account=self.opened(); shares=account['state']['positions']['ETF-ID']['shares']
        account=apply_benchmark(account,event('SPLIT','SPLIT',2,security_id='ETF-ID',ratio=2))
        self.assertEqual(account['state']['positions']['ETF-ID']['shares'],shares*2)
        for e in (event('TRADE','BUY',3,security_id='ETF-ID'),event('SPLIT','BAD',3,ratio=2)):
            with self.assertRaises(ValueError): apply_benchmark(account,e)


if __name__=='__main__': unittest.main()
