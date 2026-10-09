import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from src.v3_accounting.accounting import ROOT, Journal, apply, initial, equity


def event(kind, key, day, **extra):
    return {'kind':kind,'event_key':key,'security_id':'COMPANY-A-CLASS-A',
            'effective_at':f'2026-10-{day:02d}T13:30:00Z',
            'data_asof':f'2026-10-{day:02d}T13:31:00Z',
            'recorded_at':f'2026-10-{day:02d}T13:32:00Z',
            'reviewed':True,'evidence_sha256':'a'*64,**extra}


def buy(key='BUY', day=1, quantity=10):
    return event('TRADE',key,day,quantity=quantity,fill_price=100,fee=0)


def ex(key='EX', day=2, dividend_id='DIV-001'):
    return event('EX_DIVIDEND',key,day,dividend_id=dividend_id,
                 amount_per_share=2,currency='USD',dividend_type='ORDINARY_CASH',
                 pay_at='2026-10-06T13:30:00Z')


def pay(key='PAY'):
    return event('PAY_DIVIDEND',key,6,dividend_id='DIV-001')


class CorporateAccountingTests(unittest.TestCase):
    def funded(self):
        return apply(initial(10000),buy())

    def test_ex_date_receivable_not_spendable_cash(self):
        before=self.funded(); after=apply(before,ex())
        self.assertEqual(after['cash'],9000)
        self.assertEqual(after['dividends_earned'],20)
        self.assertEqual(after['dividends_paid'],0)
        self.assertEqual(equity(before,{'COMPANY-A-CLASS-A':100}),10000)
        self.assertEqual(equity(after,{'COMPANY-A-CLASS-A':98}),10000)

    def test_sell_after_ex_still_receives_payment(self):
        state=apply(self.funded(),ex())
        state=apply(state,event('TRADE','SELL',3,quantity=-10,fill_price=98,fee=0))
        self.assertFalse(state['positions'])
        self.assertEqual(equity(state,{}),10000)
        state=apply(state,pay())
        self.assertEqual(state['cash'],10000)
        self.assertEqual(state['dividends_paid'],20)
        self.assertEqual(equity(state,{}),10000)

    def test_buy_after_ex_receives_no_past_dividend(self):
        state=apply(initial(10000),ex())
        state=apply(state,buy(day=3))
        before=state['cash']; state=apply(state,pay())
        self.assertEqual(state['cash'],before)
        self.assertEqual(state['dividends_paid'],0)

    def test_additional_buy_partial_sale_do_not_change_entitlement(self):
        state=apply(self.funded(),ex())
        state=apply(state,buy(key='ADD',day=3,quantity=5))
        state=apply(state,event('TRADE','TRIM',4,quantity=-2,fill_price=100,fee=0))
        before=state['cash']; state=apply(state,pay())
        self.assertEqual(state['cash']-before,20)

    def test_split_during_receivable_period_does_not_double_dividend(self):
        state=apply(self.funded(),ex())
        state=apply(state,event('SPLIT','SPLIT',3,ratio=2))
        self.assertEqual(state['positions']['COMPANY-A-CLASS-A']['shares'],20)
        self.assertEqual(state['positions']['COMPANY-A-CLASS-A']['average_cost'],50)
        self.assertEqual(equity(state,{'COMPANY-A-CLASS-A':49}),10000)
        state=apply(state,pay()); self.assertEqual(state['dividends_paid'],20)

    def test_economic_dividend_duplicate_with_different_event_key_rejected(self):
        state=apply(self.funded(),ex())
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            apply(state,ex(key='DIFFERENT-KEY'))

    def test_payment_duplicate_or_unknown_rejected(self):
        with self.assertRaisesRegex(ValueError,'Missing'): apply(self.funded(),pay())
        state=apply(apply(self.funded(),ex()),pay())
        with self.assertRaisesRegex(ValueError,'already paid'): apply(state,pay('SECOND-PAY'))
        self.assertEqual(apply(state,pay()),state)

    def test_same_boundary_trade_before_entitlement_rejected(self):
        state=apply(initial(10000),buy(day=2))
        with self.assertRaisesRegex(ValueError,'Out-of-order'): apply(state,ex())

    def test_payment_date_identity_and_future_evidence_rejected(self):
        state=apply(self.funded(),ex())
        request=pay();request['security_id']='OTHER'
        with self.assertRaisesRegex(ValueError,'identity'):apply(state,request)
        request=pay();request['effective_at']='2026-10-05T13:30:00Z'
        with self.assertRaisesRegex(ValueError,'date mismatch'):apply(state,request)
        request=ex();request['data_asof']='2026-10-07T13:30:00Z'
        with self.assertRaisesRegex(ValueError,'Future'):apply(self.funded(),request)

    def test_unreviewed_foreign_special_and_negative_values_rejected(self):
        for fields in [{'reviewed':False},{'currency':'EUR'},{'dividend_type':'SPECIAL'},
                       {'amount_per_share':-1},{'evidence_sha256':'g'*64}]:
            request=ex();request.update(fields)
            with self.assertRaises(ValueError):apply(self.funded(),request)
        with self.assertRaises(ValueError):apply(self.funded(),event('SPLIT','S',3,ratio=0))

    def test_cash_cannot_spend_receivable(self):
        state=apply(self.funded(),ex())
        with self.assertRaisesRegex(ValueError,'negative cash'):
            apply(state,buy('SPEND',3,quantity=90.1))

    def test_costs_and_dividend_total_pnl_reconcile(self):
        request=buy();request['fee']=10
        state=apply(initial(10000),request);state=apply(state,ex())
        state=apply(state,event('TRADE','SELL',3,quantity=-10,fill_price=98,fee=5))
        state=apply(state,pay())
        self.assertEqual(state['fees'],15)
        self.assertEqual(state['realized_pnl'],-35)
        self.assertEqual(state['dividends_earned'],20)
        self.assertEqual(equity(state,{})-10000,state['realized_pnl']+state['dividends_earned'])

    def test_multiple_unpaid_dividends_tracked_independently(self):
        state=apply(self.funded(),ex())
        second=ex('EX-2',3,'DIV-002');second['pay_at']='2026-10-08T13:30:00Z'
        state=apply(state,second);state=apply(state,pay())
        self.assertTrue(state['receivables']['DIV-001']['paid'])
        self.assertFalse(state['receivables']['DIV-002']['paid'])
        state=apply(state,event('PAY_DIVIDEND','PAY-2',8,dividend_id='DIV-002'))
        self.assertEqual(state['dividends_paid'],40)

    def test_same_boundary_split_then_post_split_dividend(self):
        state=apply(self.funded(),event('SPLIT','SPLIT',2,ratio=2))
        request=ex();request['amount_per_share']=1
        state=apply(state,request)
        self.assertEqual(state['receivables']['DIV-001']['shares_entitled'],20)
        self.assertEqual(state['receivables']['DIV-001']['amount'],20)


class JournalTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'shadow_forward/V3_ACCOUNTING/rehearsals';base.mkdir(parents=True,exist_ok=True)
        self.temp=TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.journal=Journal(self.temp.name);self.journal.write()

    def test_complete_cycle_reopen_retry_and_atomic_failure(self):
        for request in [buy(),ex(),event('TRADE','SELL',3,quantity=-10,fill_price=98,fee=0),pay()]:
            self.assertTrue(self.journal.write(request)['created'])
        before=self.journal.inspect();reopened=Journal(self.temp.name)
        for request in [buy(),ex(),pay()]:self.assertFalse(reopened.write(request)['created'])
        self.assertEqual(reopened.inspect(),before)
        self.assertEqual(before['events'],5)
        self.assertEqual(before['state']['cash'],10000)
        with self.assertRaises(ValueError):reopened.write(pay('ANOTHER'))
        self.assertEqual(reopened.inspect(),before)

    def test_parallel_payment_once(self):
        self.journal.write(buy());self.journal.write(ex())
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(lambda _:self.journal.write(pay()),range(2)))
        self.assertEqual(sum(r['created'] for r in result),1)
        self.assertEqual(self.journal.inspect()['state']['dividends_paid'],20)

    def test_changed_event_rejected(self):
        self.journal.write(buy());modified=buy();modified['quantity']=12
        with self.assertRaisesRegex(ValueError,'conflict'):self.journal.write(modified)
        self.assertEqual(self.journal.inspect()['events'],2)

    def test_append_only_and_hash_tamper(self):
        import sqlite3
        c=self.journal.connect()
        try:
            for sql in ['DELETE FROM journal','UPDATE journal SET key="BAD"']:
                with self.assertRaises(sqlite3.IntegrityError):c.execute(sql)
            c.execute('DROP TRIGGER no_update');c.execute('UPDATE journal SET hash="bad"');c.commit()
        finally:c.close()
        with self.assertRaisesRegex(ValueError,'integrity'):self.journal.inspect()

    def test_official_or_v2_store_rejected(self):
        for directory in [ROOT/'stock-agent-work',ROOT/'shadow_forward/V11_TOP3_95_IPO_V2',ROOT/'sources']:
            with self.assertRaisesRegex(ValueError,'isolated'):Journal(directory)


if __name__=='__main__':unittest.main()
