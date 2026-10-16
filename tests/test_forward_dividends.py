from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_forward_valuation import _ledger
from src.forward_dividends import eligible_shares, dividend_book, load_reviews, assert_reviewed_history
from src.forward_execution import portfolio_state_from_ledger, execute_target_weights
from src.forward_valuation import record_daily_valuations
from scripts.run_v12_forward_automation import pending_valuation_dates


class ReviewedDividendsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ledger = _ledger(Path(directory.name) / 'ledger.sqlite3')
        self.action = {'action_id': 'fixture-AAPL-dividend', 'ticker': 'AAPL', 'ex_date': '2026-09-02',
                       'pay_date': '2026-10-02', 'amount_per_share': .25, 'review_sha256': 'test-fixture'}
        self.reviews = {'fixture': self.action}
        self.shares = portfolio_state_from_ledger(self.ledger, 'V12_T1').positions['AAPL'].shares
        self.cash = portfolio_state_from_ledger(self.ledger, 'V12_T1').cash

    def value(self, day, dividend=0, split=0, price=210, reviews=None):
        return record_daily_valuations(self.ledger, valuation_date=day,
            observation_fetcher=lambda tickers, d: {t: {'close': price, 'dividend': dividend, 'split': split} for t in tickers},
            recorded_at=datetime.fromisoformat(day + 'T23:00:00+00:00'),
            reviewed_dividends=self.reviews if reviews is None else reviews)

    def payload(self):
        return [r['payload'] for r in self.ledger.events() if r['event_type'] == 'VALUATION_SNAPSHOT'][-1]

    def test_ex_date_accrues_but_does_not_credit_cash(self):
        self.value('2026-09-02', dividend=.25)
        p = self.payload()
        self.assertAlmostEqual(p['cash'], self.cash)
        self.assertAlmostEqual(p['dividends_receivable'], self.shares * .25)
        self.assertEqual(p['dividends'], 0)
        self.assertAlmostEqual(p['portfolio_equity'], p['cash'] + p['market_value'] + p['dividends_receivable'])
        self.assertEqual(len([r for r in self.ledger.events() if r['event_type'] == 'DIVIDEND_ENTITLEMENT']), 1)

    def test_repeat_ex_date_is_identical(self):
        self.value('2026-09-02', dividend=.25)
        before = self.ledger.events()
        self.assertEqual(self.value('2026-09-02', dividend=.25), [])
        self.assertEqual(self.ledger.events(), before)

    def test_payment_transfers_receivable_not_new_profit(self):
        self.value('2026-09-02', dividend=.25)
        before_equity = self.payload()['portfolio_equity']
        self.value('2026-10-02')
        p = self.payload()
        self.assertAlmostEqual(p['cash'], self.cash + self.shares * .25)
        self.assertEqual(p['dividends_receivable'], 0)
        self.assertAlmostEqual(p['portfolio_equity'], before_equity)
        self.assertAlmostEqual(portfolio_state_from_ledger(self.ledger,'V12_T1').cash, p['cash'])
        before = self.ledger.events()
        self.assertEqual(self.value('2026-10-02'), [])
        self.assertEqual(self.ledger.events(), before)

    def test_cash_not_credited_before_pay_date(self):
        self.value('2026-09-02', dividend=.25)
        self.value('2026-10-01')
        self.assertAlmostEqual(self.payload()['cash'], self.cash)
        self.assertGreater(self.payload()['dividends_receivable'], 0)

    def test_sell_before_payment_retains_fixed_entitlement(self):
        self.value('2026-09-02', dividend=.25)
        execute_target_weights(self.ledger, portfolio_id='V12_T1', signal_date='2026-09-30',
            execution_rule='T+1_OPEN', target_weights={}, raw_open_prices={'AAPL': 210},
            execution_date='2026-10-01', recorded_at=datetime(2026,10,1,23,tzinfo=timezone.utc))
        cash = portfolio_state_from_ledger(self.ledger,'V12_T1').cash
        self.value('2026-10-02')
        self.assertAlmostEqual(self.payload()['cash'], cash + self.shares * .25)
        self.assertEqual(self.payload()['positions'], {})

    def test_ex_date_open_buy_not_eligible_and_sell_is_eligible(self):
        rows = [dict(r) for r in self.ledger.events()]
        for r in rows:
            if r['event_type'] == 'FILL':
                r['payload'] = {**r['payload'], 'execution_date': '2026-09-02'}
        self.assertEqual(eligible_shares(rows,'V12_T1','AAPL','2026-09-02'), 0)
        rows = [dict(r) for r in self.ledger.events()]
        rows.append({'portfolio_id':'V12_T1','event_type':'FILL','ticker':'AAPL','action':'SELL',
                     'quantity':self.shares,'payload':{'execution_date':'2026-09-02'}})
        self.assertEqual(eligible_shares(rows,'V12_T1','AAPL','2026-09-02'), self.shares)

    def test_unreviewed_mismatch_split_and_nonfinite_fail_atomically(self):
        for dividend, split in ((.3, 0), (.25, 2), (float('nan'), 0)):
            before = self.ledger.events()
            with self.subTest(dividend=dividend, split=split), self.assertRaises(RuntimeError):
                self.value('2026-09-02', dividend=dividend, split=split)
            self.assertEqual(self.ledger.events(), before)

    def test_missing_provider_corroboration_is_not_approved(self):
        before = self.ledger.events()
        with self.assertRaisesRegex(RuntimeError,'corroborated'):
            self.value('2026-09-02')
        self.assertEqual(self.ledger.events(), before)

    def test_changed_review_and_late_missing_entitlement_fail(self):
        with self.assertRaisesRegex(RuntimeError,'chronological recovery'):
            self.value('2026-09-03')
        self.value('2026-09-02', dividend=.25)
        self.action['pay_date'] = '2026-10-05'
        with self.assertRaisesRegex(RuntimeError,'conflicts'):
            self.value('2026-09-03')

    def test_atomic_write_failure_rolls_back_entitlement_and_valuation(self):
        before = self.ledger.events()
        original = self.ledger.append_batch
        with patch.object(self.ledger,'append_batch',side_effect=lambda events: original(events,_fail_after_inserts=1)):
            with self.assertRaisesRegex(RuntimeError,'simulated crash'):
                self.value('2026-09-02', dividend=.25)
        self.assertEqual(self.ledger.events(), before)

    def test_payment_missing_entitlement_is_rejected(self):
        row = {'event_type':'DIVIDEND_PAYMENT','event_id':'x','portfolio_id':'V12_T1','ticker':'AAPL',
               'payload':{'entitlement_id':'missing','amount':5,'payment_date':'2026-10-02'}}
        with self.assertRaises(ValueError): dividend_book([row])

    def test_registry_contains_verified_mu_review_and_no_future_review(self):
        self.assertEqual(load_reviews(datetime(2026,9,2,tzinfo=timezone.utc)), {})
        reviews = load_reviews(datetime(2026,10,16,tzinfo=timezone.utc))
        action = reviews['MU-2026-10-14-ORDINARY-USD']
        self.assertEqual(action['amount_per_share'], .15)
        self.assertEqual(action['pay_date'], '2026-10-29')
        with self.assertRaises(ValueError): load_reviews(datetime(2026,10,15,20,tzinfo=timezone.utc))

    def test_already_published_day_without_entitlement_cannot_be_silently_accepted(self):
        self.value('2026-09-02', reviews={})
        with self.assertRaisesRegex(RuntimeError,'restatement'):
            assert_reviewed_history(self.ledger.events(), self.reviews)


class ValuationRecoveryTests(unittest.TestCase):
    def ledger(self, last):
        class Rows:
            def events(self): return [{'event_type':'VALUATION_SNAPSHOT','payload':{'valuation_date':last}}]
        return Rows()

    def test_recovers_only_missing_completed_sessions(self):
        self.assertEqual(pending_valuation_dates(self.ledger('2026-10-13'),'2026-10-15'), ['2026-10-14','2026-10-15'])
        self.assertEqual(pending_valuation_dates(self.ledger('2026-10-15'),'2026-10-15'), [])

    def test_weekends_skipped_and_month_end_or_large_gap_fails(self):
        self.assertEqual(pending_valuation_dates(self.ledger('2026-10-09'),'2026-10-12'), ['2026-10-12'])
        for last, current in [('2026-09-29','2026-10-01'),('2026-10-01','2026-10-15'),('2026-10-15','2026-10-14')]:
            with self.subTest(last=last), self.assertRaises(RuntimeError): pending_valuation_dates(self.ledger(last),current)

    def test_past_unexecuted_order_blocks_recovery(self):
        with patch('src.forward_execution.due_portfolio_targets',return_value=[{'pending':True}]):
            with self.assertRaisesRegex(RuntimeError,'Missing past execution'):
                pending_valuation_dates(self.ledger('2026-10-13'),'2026-10-15')
