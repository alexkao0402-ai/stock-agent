"""Capture observations into V3 quarantine, never approve or trade.

Yahoo chart is an unofficial observation source, not complete action coverage.
Issuer content is retained as untrusted evidence; no AI/automatic signing.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse, quote
from zoneinfo import ZoneInfo

from src.v3_accounting.accounting import ROOT, encoded
from src.v3_accounting.runner import session_open, session_close
from src.v3_accounting.payment_policy import POLICY

QUEUE = ROOT / 'shadow_forward/V3_ACCOUNTING/quarantine'
LIMIT = 5 * 1024 * 1024
NY = ZoneInfo('America/New_York')
ISSUER_HOSTS = {'investor.nvidia.com', 'www.sec.gov', 'data.sec.gov'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def public_issuer(url, allowed_hosts):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname not in allowed_hosts or parsed.username
            or parsed.password or parsed.port or parsed.query or parsed.fragment):
        raise ValueError('Explicitly allowed HTTPS issuer URL without credentials/query required')
    return url


def fetch(session, url, *, params=None, secret=''):
    """Bounded response, no redirect or logging of API-key query strings."""
    try:
        response = session.get(url, params=params, timeout=25, allow_redirects=False,
            stream=True, headers={'User-Agent': 'stock-agent-v3-source-review/1.0'})
        try:
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > LIMIT:
                    return None, 'RESPONSE_TOO_LARGE'
            if secret and secret.encode() in data:
                return None, 'SECRET_ECHO_REJECTED'
            return bytes(data), None if response.status_code == 200 else 'HTTP_' + str(response.status_code)
        finally:
            response.close()
    except Exception:
        return None, 'NETWORK_ERROR'


def inspect_prices(data, ticker, trade_date, kind, instrument_type='EQUITY'):
    if instrument_type not in {'EQUITY','ETF'} or (instrument_type=='ETF' and ticker not in {'SPY','QQQ'}):
        raise ValueError('Explicit supported instrument type required')
    result = json.loads(data)['chart']['result'][0]
    meta = result['meta']
    if (meta.get('symbol') != ticker or meta.get('currency') != 'USD'
            or meta.get('instrumentType') != instrument_type
            or meta.get('exchangeTimezoneName') != 'America/New_York'):
        raise ValueError('Price identity/currency/type/timezone mismatch')
    timestamps = result['timestamp']
    quotes = result['indicators']['quote'][0]
    indexes = [i for i, t in enumerate(timestamps)
               if datetime.fromtimestamp(t, timezone.utc).astimezone(NY).date().isoformat() == trade_date]
    if len(indexes) != 1:
        raise ValueError('Missing or duplicate target-session bar')
    field = 'open' if kind == 'OPEN' else 'close'
    value = float(quotes[field][indexes[0]])
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Invalid price')
    return {'date': trade_date, 'kind': kind, 'field': field, 'observed_price': value,
            'price_basis': 'PROVIDER_UNADJUSTED_FIELD_REQUIRES_REVIEW',
            'reported_events': result.get('events', {}),
            'coverage_confirmed': False}


def inspect_dividends(data, ticker=None):
    payload = json.loads(data)
    if any(k in payload for k in ['Information', 'Note', 'Error Message']):
        raise ValueError('Provider restriction or error')
    if ticker is not None and payload.get('symbol') != ticker:
        raise ValueError('Dividend symbol mismatch')
    rows = payload['data']
    if not isinstance(rows, list):
        raise ValueError('Dividend schema mismatch')
    seen, valid, issues, duplicate_dates = set(), [], [], set()
    for i, row in enumerate(rows):
        try:
            ex = date.fromisoformat(row['ex_dividend_date'])
            if ex in seen:
                duplicate_dates.add(row['ex_dividend_date'])
                raise ValueError('Duplicate')
            seen.add(ex)
            pay = date.fromisoformat(row['payment_date'])
            declaration = date.fromisoformat(row['declaration_date'])
            date.fromisoformat(row['record_date'])
            amount = float(row['amount'])
            if pay < ex or declaration > ex or not math.isfinite(amount) or amount <= 0:
                raise ValueError('Invalid')
            valid.append(row)
        except (KeyError, ValueError, TypeError):
            issues.append({'index': i, 'reason': 'MISSING_INVALID_OR_DUPLICATE_DIVIDEND_FIELDS'})
    valid = [row for row in valid if row['ex_dividend_date'] not in duplicate_dates]
    # Even a successful empty list does not establish absence of events.
    return {'count': len(rows), 'candidates': valid, 'row_issues': issues, 'coverage_confirmed': False,
            'currency_verified': False, 'payment_time_confirmed': False}


def capture(ticker, security_id, trade_date, kind, issuer_urls=(), *, alpha_key='',
            session=None, clock=None, queue=QUEUE, allowed_hosts=ISSUER_HOSTS,instrument_type='EQUITY'):
    queue = Path(queue).resolve()
    if not queue.is_relative_to(QUEUE.resolve()):
        raise ValueError('V3 quarantine only')
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,11}', ticker) or not security_id or kind not in {'OPEN', 'CLOSE'}:
        raise ValueError('Explicit ticker, security identity and OPEN/CLOSE required')
    if instrument_type not in {'EQUITY','ETF'} or (instrument_type=='ETF' and ticker not in {'SPY','QQQ'}):
        raise ValueError('Explicit supported instrument type required')
    day = date.fromisoformat(trade_date)
    urls = [public_issuer(url, allowed_hosts) for url in issuer_urls]
    clock = clock or (lambda: datetime.now(timezone.utc))
    started = clock()
    if started.tzinfo is None:
        raise ValueError('Timezone required')
    boundary = session_open(trade_date) if kind == 'OPEN' else session_close(trade_date)
    if boundary > started:
        raise ValueError('Session price boundary not yet available')
    if session is None:
        import requests
        session = requests.Session()
    raw, sources, observations = {}, [], {}
    reasons = ['SECURITY_IDENTITY_REVIEW_REQUIRED', 'ACTION_COVERAGE_REVIEW_REQUIRED',
               'PAYMENT_DATE_SOURCE_REVIEW_REQUIRED']

    def collect(name, url, params=None, secret=''):
        data, error = fetch(session, url, params=params, secret=secret)
        captured = clock().isoformat()
        source = {'file': name, 'url': url, 'captured_at': captured, 'error': error}
        if data is not None:
            raw[name] = data
            source['sha256'] = sha(data)
        sources.append(source)
        if error:
            reasons.append(name + ':' + error)
            return None
        return data

    begin = datetime.combine(day, datetime.min.time(), NY)
    prices = collect('sources/yahoo_chart.json', 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(ticker),
        {'period1': int(begin.timestamp()), 'period2': int((begin + timedelta(days=1)).timestamp()),
         'interval': '1d', 'events': 'div,splits'})
    if prices is not None:
        try:
            observations['price'] = inspect_prices(prices, ticker, trade_date, kind,instrument_type)
        except Exception:
            reasons.append('PRICE_SCHEMA_OR_IDENTITY_INVALID')
    if alpha_key:
        dividends = collect('sources/alpha_dividends.json', 'https://www.alphavantage.co/query',
                            {'function': 'DIVIDENDS', 'symbol': ticker, 'apikey': alpha_key}, alpha_key)
        if dividends is not None:
            try:
                observations['dividends'] = inspect_dividends(dividends, ticker)
                if observations['dividends']['row_issues']:
                    reasons.append('DIVIDEND_RECORDS_INCOMPLETE_REQUIRES_SCOPED_REVIEW')
            except Exception:
                reasons.append('DIVIDEND_SCHEMA_OR_DATES_REQUIRE_REVIEW')
    else:
        reasons.append('ALPHAVANTAGE_KEY_MISSING')
    if not urls:
        reasons.append('ISSUER_ORIGINAL_MISSING')
    for i, url in enumerate(urls):
        collect(f'sources/issuer_{i}.original', url)
    completed = clock()
    if completed < started:
        raise ValueError('Capture clock moved backwards')
    historical = started.astimezone(NY).date() != day or completed.astimezone(NY).date() != day
    if historical:
        reasons.append('HISTORICAL_RETRIEVAL_NOT_FORWARD')
    if 'dividends' in observations:
        candidates = observations['dividends']['candidates']
        if any(date.fromisoformat(row['declaration_date']) > completed.astimezone(NY).date() for row in candidates):
            reasons.append('FUTURE_DECLARATION_REQUIRES_REVIEW')
        by_ex = {row['ex_dividend_date']: float(row['amount']) for row in candidates}
        try:
            events = observations.get('price', {}).get('reported_events', {}).get('dividends', {})
            for event in events.values():
                ex = datetime.fromtimestamp(event['date'], timezone.utc).astimezone(NY).date().isoformat()
                if ex not in by_ex or not math.isclose(float(event['amount']), by_ex[ex], rel_tol=1e-8, abs_tol=1e-8):
                    reasons.append('YAHOO_ALPHA_DIVIDEND_MISMATCH')
        except Exception:
            reasons.append('YAHOO_DIVIDEND_EVENT_INVALID')
    draft = {'schema_version': 1, 'status': 'PENDING_REVIEW', 'approved': False,
             'cash_policy': POLICY,
             'ticker': ticker, 'claimed_security_id': security_id, 'identity_verified': False,
             'claimed_instrument_type':instrument_type,
             'date': trade_date, 'kind': kind, 'capture_started_at': started.isoformat(),
             'captured_at': completed.isoformat(), 'historical_retrieval': historical,
             'forward_eligible': False, 'sources': sources, 'observations': observations,
             'review_required': reasons, 'scheduler_enabled': False}
    content = encoded(draft).encode()
    directory = queue / sha(content)
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in {**raw, 'draft.json': content}.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError('Immutable capture conflict')
        else:
            with target.open('xb') as handle:
                handle.write(data)
    return {'status': 'PENDING_REVIEW', 'directory': str(directory), 'sources_saved': len(raw),
            'review_required': reasons, 'forward_eligible': False, 'scheduler_enabled': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', required=True)
    parser.add_argument('--security-id', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--kind', choices=['OPEN', 'CLOSE'], required=True)
    parser.add_argument('--instrument-type', choices=['EQUITY','ETF'], default='EQUITY')
    parser.add_argument('--issuer-url', action='append', default=[])
    parser.add_argument('--env-file')
    args = parser.parse_args()
    from dotenv import dotenv_values
    cfg = dotenv_values(args.env_file) if args.env_file else {}
    try:
        result = capture(args.ticker, args.security_id, args.date, args.kind, args.issuer_url,
                         alpha_key=cfg.get('ALPHAVANTAGE_API_KEY') or '',instrument_type=args.instrument_type)
        print(json.dumps(result, indent=2))
    except Exception as error:
        print(json.dumps({'status': 'FAILED', 'error_type': type(error).__name__}))
        raise SystemExit(1)
