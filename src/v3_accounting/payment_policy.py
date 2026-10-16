"""Approved paper-only cash availability policy; not broker receipt evidence."""
from datetime import date, timezone
from zoneinfo import ZoneInfo

# Import existing calendar through V2, without editing frozen signal rules.
from src.v3_accounting.signal import next_session
from src.trading_calendar import session_open
from src.v3_accounting.accounting import stamp

POLICY = 'USD_ORDINARY_CASH_NEXT_SESSION_AFTER_ISSUER_PAYMENT_DATE_V1'


def cash_available_at(issuer_payment_date):
    day = date.fromisoformat(issuer_payment_date)
    if issuer_payment_date != day.isoformat():
        raise ValueError('Canonical issuer payment date required')
    return session_open(next_session(day)).astimezone(timezone.utc).isoformat()


def validate_ex_dividend(event):
    """Never infer payment date or rewrite reviewed events in place."""
    if event.get('kind') != 'EX_DIVIDEND':
        return
    if event.get('cash_policy') != POLICY:
        raise ValueError('Approved V3 dividend cash policy required')
    issuer_date = event.get('issuer_payment_date')
    if not isinstance(issuer_date, str):
        raise ValueError('Issuer payment date required')
    ex_day = stamp(event['effective_at']).astimezone(ZoneInfo('America/New_York')).date()
    if date.fromisoformat(issuer_date) < ex_day:
        raise ValueError('Issuer payment date precedes ex-date')
    if event.get('pay_at') != cash_available_at(issuer_date):
        raise ValueError('Cash availability must be next session after issuer payment date')


def annotate_ex_dividend(event, issuer_payment_date):
    """Draft helper only: does not sign, approve, record, or fetch anything."""
    if event.get('kind') != 'EX_DIVIDEND':
        raise ValueError('EX_DIVIDEND required')
    if any(k in event for k in ['pay_at', 'cash_policy', 'issuer_payment_date']):
        raise ValueError('Do not overwrite pre-existing payment fields')
    result = {**event, 'issuer_payment_date': issuer_payment_date, 'cash_policy': POLICY,
              'pay_at': cash_available_at(issuer_payment_date)}
    validate_ex_dividend(result)
    return result
