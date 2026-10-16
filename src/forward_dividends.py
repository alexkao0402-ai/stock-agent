"""Reviewed ordinary USD cash-dividend accounting for V12, separate from V3.

Entitlements are fixed at pre-ex-date shares. Payment is a separate append-only
event, never inferred from current holdings or treated as spendable cash early.
Unsupported corporate actions still fail closed.
"""
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

from src.paper_ledger import LedgerEvent, deterministic_event_id
from src.trading_calendar import is_session, session_close, session_open
from src.v12_live_signal import FROZEN_VERSION

REGISTRY = Path(__file__).resolve().parents[1] / 'config/v12_reviewed_dividends.json'


def positive(value):
    if isinstance(value, bool):
        raise ValueError('Invalid boolean dividend value')
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Invalid dividend amount or quantity')
    return value


def load_reviews(now, path=REGISTRY):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    result = {}
    for action in raw['actions']:
        action = dict(action)
        identifier = action['action_id']
        ex_date = date.fromisoformat(action['ex_date'])
        if ex_date > now.date():
            continue
        pay_date = date.fromisoformat(action['pay_date'])
        reviewed = datetime.fromisoformat(action['reviewed_at'])
        if reviewed.tzinfo is None or reviewed > now or pay_date <= ex_date or not is_session(ex_date):
            raise ValueError('Invalid dividend review dates')
        if action.get('kind') != 'ORDINARY_CASH' or action.get('currency') != 'USD' or not action.get('reviewer'):
            raise ValueError('Unsupported or unreviewed dividend')
        if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', action['ticker']):
            raise ValueError('Invalid dividend ticker')
        source = urlparse(action['source_url'])
        if source.scheme != 'https' or source.hostname != 'www.sec.gov' or not source.path.startswith(f"/Archives/edgar/data/{int(action['issuer_cik'])}/"):
            raise ValueError('Dividend issuer source mismatch')
        if not re.fullmatch(r'[0-9a-f]{64}', action['source_sha256']):
            raise ValueError('Missing dividend source fingerprint')
        action['amount_per_share'] = positive(action['amount_per_share'])
        if identifier in result or any(a['ticker'] == action['ticker'] and a['ex_date'] == action['ex_date'] for a in result.values()):
            raise ValueError('Duplicate dividend review')
        action['review_sha256'] = hashlib.sha256(json.dumps(action, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        result[identifier] = action
    return result


def dividend_book(rows):
    """Validate journal references and immutable amounts before replay."""
    entitlements, paid = {}, set()
    for row in rows:
        payload = row.get('payload') or {}
        if row['event_type'] == 'DIVIDEND_ENTITLEMENT':
            key = row['event_id']
            amount = positive(payload['eligible_shares']) * positive(payload['amount_per_share'])
            if key in entitlements or not math.isclose(amount, positive(payload['amount']), abs_tol=1e-9):
                raise ValueError('Invalid or duplicate dividend entitlement')
            if payload['pay_date'] <= payload['ex_date']:
                raise ValueError('Invalid dividend payment date')
            entitlements[key] = row
        elif row['event_type'] == 'DIVIDEND_PAYMENT':
            key = payload['entitlement_id']
            prior = entitlements.get(key)
            if not prior or key in paid or prior['portfolio_id'] != row['portfolio_id'] or prior['ticker'] != row['ticker']:
                raise ValueError('Invalid or duplicate dividend payment')
            if payload['payment_date'] < prior['payload']['pay_date'] or not math.isclose(positive(payload['amount']), prior['payload']['amount'], abs_tol=1e-9):
                raise ValueError('Premature or changed dividend payment')
            paid.add(key)
    return entitlements, paid


def receivable(rows, portfolio_id):
    entitlements, paid = dividend_book(rows)
    return sum(row['payload']['amount'] for key, row in entitlements.items()
               if key not in paid and row['portfolio_id'] == portfolio_id)


def eligible_shares(rows, portfolio_id, ticker, ex_date):
    # Fills at ex-date open do not earn this dividend; selling at that open retains it.
    shares = {}
    for row in rows:
        if row['portfolio_id'] != portfolio_id:
            continue
        payload = row.get('payload') or {}
        effective = str(payload.get('execution_date') or row.get('data_asof') or '')[:10]
        if not effective or effective >= ex_date:
            continue
        symbol = row['ticker']
        if row['event_type'] == 'FILL':
            quantity = positive(row['quantity'])
            if row['action'] not in {'BUY', 'SELL'}:
                raise ValueError('Invalid fill side')
            shares[symbol] = shares.get(symbol, 0) + (quantity if row['action'] == 'BUY' else -quantity)
        elif row['event_type'] == 'SPLIT':
            shares[symbol] = shares.get(symbol, 0) * positive(payload['ratio'])
        elif row['event_type'] == 'TICKER_CHANGE':
            shares[payload['new_ticker']] = shares.pop(symbol, 0)
    if any(value < -1e-8 for value in shares.values()):
        raise ValueError('Negative dividend eligible shares')
    return max(shares.get(ticker, 0), 0)


def assert_reviewed_history(rows, reviews):
    """Never silently accept an old published valuation missing a reviewed accrual."""
    entitlements, _ = dividend_book(rows)
    for action in reviews.values():
        affected = {r['portfolio_id'] for r in rows if r['event_type'] == 'VALUATION_SNAPSHOT'
                    and str(r['payload'].get('valuation_date', '')) >= action['ex_date']}
        for portfolio_id in affected:
            shares = eligible_shares(rows, portfolio_id, action['ticker'], action['ex_date'])
            if shares <= 1e-9:
                continue
            key = deterministic_event_id(FROZEN_VERSION, portfolio_id, action['action_id'], 'DIVIDEND_ENTITLEMENT')
            if key not in entitlements:
                raise RuntimeError('Published valuation lacks reviewed entitlement; explicit append-only restatement review required')
            if entitlements[key]['payload'] != {**action, 'eligible_shares': shares, 'amount': shares * action['amount_per_share']}:
                raise RuntimeError('Reviewed history conflicts with immutable entitlement')


def prepare_dividends(rows, valuation_date, observations, reviews, now):
    """Prepare events without writing. Caller commits them with all valuations."""
    entitlements, paid = dividend_book(rows)
    portfolios = sorted({r['portfolio_id'] for r in rows if r['event_type'] == 'INITIALIZE'})
    reviewed = {(r['ticker'], r['ex_date']): r for r in reviews.values()}
    for ticker, observation in observations.items():
        split, dividend = float(observation.get('split', 0)), float(observation.get('dividend', 0))
        if not math.isfinite(split) or not math.isfinite(dividend) or split != 0:
            raise RuntimeError(f'corporate action requires reviewed split handling for {ticker}')
        if dividend:
            action = reviewed.get((ticker, valuation_date))
            if not action or not math.isclose(dividend, action['amount_per_share'], abs_tol=1e-9):
                raise RuntimeError(f'corporate action requires matching reviewed dividend for {ticker} on {valuation_date}')
    prepared = []
    recorded = now.astimezone(timezone.utc).isoformat(timespec='seconds')
    for action in reviews.values():
        if action['ex_date'] > valuation_date:
            continue
        ticker = action['ticker']
        if any(row['event_type'] == 'DIVIDEND' and row['ticker'] == ticker and
               str(row.get('data_asof', ''))[:10] == action['ex_date'] for row in rows):
            raise RuntimeError('Legacy dividend overlaps reviewed entitlement; manual reconciliation required')
        for portfolio_id in portfolios:
            shares = eligible_shares(rows, portfolio_id, ticker, action['ex_date'])
            if shares <= 1e-9:
                continue
            key = deterministic_event_id(FROZEN_VERSION, portfolio_id, action['action_id'], 'DIVIDEND_ENTITLEMENT')
            payload = {**action, 'eligible_shares': shares, 'amount': shares * action['amount_per_share']}
            if key in entitlements:
                if entitlements[key]['payload'] != payload:
                    raise RuntimeError('Reviewed dividend conflicts with immutable entitlement')
            else:
                if action['ex_date'] != valuation_date:
                    raise RuntimeError('Missing earlier dividend entitlement; chronological recovery required')
                observation = observations.get(ticker)
                if not observation or not math.isclose(float(observation.get('dividend', 0)), action['amount_per_share'], abs_tol=1e-9):
                    raise RuntimeError('Reviewed dividend not corroborated by ex-date observation')
                prepared.append(LedgerEvent(key, portfolio_id, 'DIVIDEND_ENTITLEMENT', FROZEN_VERSION,
                    session_open(action['ex_date']).isoformat(), 'REVIEWED_CASH_DIVIDEND', action['ex_date'],
                    ticker=ticker, reason='Reviewed pre-ex-date entitlement; not spendable cash', payload=payload, created_at=recorded))
            if key not in paid and action['pay_date'] <= valuation_date:
                if now < session_close(valuation_date):
                    raise ValueError('Dividend payment cannot be recorded before the accounting close')
                prepared.append(LedgerEvent(deterministic_event_id(key, 'DIVIDEND_PAYMENT'), portfolio_id,
                    'DIVIDEND_PAYMENT', FROZEN_VERSION, session_close(valuation_date).isoformat(),
                    'REVIEWED_PAY_DATE_CLOSE', valuation_date, ticker=ticker,
                    reason='Simulated gross USD dividend paid; no broker confirmation implied',
                    payload={'entitlement_id': key, 'payment_date': valuation_date, 'amount': payload['amount']}, created_at=recorded))
    return prepared
