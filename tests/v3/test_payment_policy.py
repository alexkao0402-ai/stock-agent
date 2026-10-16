import unittest
from src.v3_accounting.payment_policy import POLICY, cash_available_at, annotate_ex_dividend, validate_ex_dividend


class PaymentPolicyTests(unittest.TestCase):
    def event(self):
        return {'kind':'EX_DIVIDEND', 'effective_at':'2026-09-10T13:30:00+00:00',
                'security_id':'SYNTHETIC-ID', 'event_key':'SYNTHETIC-EX'}

    def test_nvda_date_example_not_actual_entitlement(self):
        self.assertEqual(cash_available_at('2026-10-01'), '2026-10-02T13:30:00+00:00')

    def test_weekend_and_exchange_holiday(self):
        self.assertEqual(cash_available_at('2026-09-04'), '2026-09-08T13:30:00+00:00')
        self.assertEqual(cash_available_at('2026-09-05'), '2026-09-08T13:30:00+00:00')

    def test_dst_transition(self):
        self.assertEqual(cash_available_at('2026-10-30'), '2026-11-02T14:30:00+00:00')

    def test_annotate_does_not_approve_or_mutate(self):
        original=self.event()
        result=annotate_ex_dividend(original,'2026-10-01')
        self.assertNotIn('pay_at',original)
        self.assertNotIn('reviewed',result)
        self.assertNotIn('signature',result)
        self.assertEqual(result['issuer_payment_date'],'2026-10-01')
        self.assertEqual(result['cash_policy'],POLICY)

    def test_old_same_day_cash_rejected(self):
        event=annotate_ex_dividend(self.event(),'2026-10-01')
        event['pay_at']='2026-10-01T13:30:00+00:00'
        with self.assertRaises(ValueError):validate_ex_dividend(event)

    def test_missing_policy_or_source_date_rejected(self):
        with self.assertRaises(ValueError):validate_ex_dividend(self.event())
        with self.assertRaises(ValueError):annotate_ex_dividend(self.event(),'2026-09-01')

    def test_no_overwrite_previously_reviewed_time(self):
        event={**self.event(),'pay_at':'2026-10-01T13:30:00+00:00'}
        with self.assertRaises(ValueError):annotate_ex_dividend(event,'2026-10-01')


if __name__=='__main__':unittest.main()
