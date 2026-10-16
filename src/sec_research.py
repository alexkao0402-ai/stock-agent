"""Public SEC research context. Never used for trading or accounting decisions."""
from datetime import date
import math
import re
import threading
import time

import requests

from src.config import get_secret

_request_lock = threading.Lock()
_last_request = 0.0


def _get(url, agent):
    global _last_request
    # At most two requests/second per process, including concurrent page sessions.
    with _request_lock:
        time.sleep(max(0, 0.5 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
    response = requests.get(url, headers={'User-Agent': agent, 'Accept-Encoding': 'gzip, deflate'},
                            timeout=12, allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200 or len(response.content) > 20_000_000:
        raise ValueError('Unexpected SEC response')
    return response.json()


def _iso(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def filing_url(cik, accession, document=''):
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', str(accession)):
        return ''
    base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/'
    if document and re.fullmatch(r'[A-Za-z0-9_.-]+', document) and '..' not in document:
        return base + document
    return base + accession + '-index.html'


def reported_financials(facts, cik, today=None):
    """Latest reported periods, NOT TTM. Keep each fact's own period and accession."""
    today = today or date.today()
    if int(facts.get('cik', -1)) != int(cik):
        raise ValueError('SEC company identity mismatch')
    gaap = facts.get('facts', {}).get('us-gaap', {})
    definitions = [
        ('Revenue', ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'], 'USD', True),
        ('Net income', ['NetIncomeLoss', 'ProfitLoss'], 'USD', True),
        ('Diluted EPS', ['EarningsPerShareDiluted'], 'USD/shares', True),
        ('Assets', ['Assets'], 'USD', False),
        ('Liabilities', ['Liabilities'], 'USD', False),
    ]
    rows = []
    for label, tags, unit, duration in definitions:
        candidates = []
        for priority, tag in enumerate(tags):
            for fact in gaap.get(tag, {}).get('units', {}).get(unit, []):
                end, filed, start = _iso(fact.get('end')), _iso(fact.get('filed')), _iso(fact.get('start'))
                try:
                    value = float(fact['val'])
                except (KeyError, ValueError, TypeError):
                    continue
                if not math.isfinite(value) or not end or not filed or end > today or filed > today:
                    continue
                if fact.get('form') not in {'10-K', '10-Q', '10-K/A', '10-Q/A'}:
                    continue
                days = (end - start).days if start else None
                if duration and (days is None or not (60 <= days <= 380)):
                    continue
                if not duration and start:
                    continue
                url = filing_url(cik, fact.get('accn'))
                if not url:
                    continue
                # At the latest period, prefer the shortest reported duration (quarter over YTD).
                candidates.append((end, -(days or 0), filed, -priority, value, fact, url))
        if candidates:
            chosen = max(candidates, key=lambda item: item[:4])
            end, _, filed, _, value, fact, url = chosen
            rows.append({'Metric': label, 'Value': value, 'Unit': unit,
                         'Period start': fact.get('start') or 'Instant', 'Period end': end.isoformat(),
                         'Filed': filed.isoformat(), 'Form': fact['form'], 'Source': url})
    return rows


def sec_context(symbol, cached):
    """Cache successful documents; return explicit unavailable status without credentials."""
    agent = get_secret('SEC_USER_AGENT') or ''
    if not re.search(r'\b[^\s@]+@[^\s@]+\.[^\s@]+\b', agent) or '\n' in agent or '\r' in agent or 'example.com' in agent or 'example.invalid' in agent:
        return {'status': 'SEC_USER_AGENT not configured', 'financials': [], 'filings': []}
    mapping = cached('SEC ticker directory', 'directory', lambda: _get('https://www.sec.gov/files/company_tickers.json', agent), 86400)
    match = next((r for r in mapping.values() if isinstance(r, dict) and
                  str(r.get('ticker', '')).replace('.', '-') == symbol.replace('.', '-')), None)
    if not match:
        return {'status': 'No SEC ticker match', 'financials': [], 'filings': []}
    cik = int(match['cik_str'])
    submissions = cached('SEC filings', str(cik), lambda: _get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json', agent), 3600)
    if int(submissions.get('cik', -1)) != cik or symbol.replace('.', '-') not in [str(t).replace('.', '-') for t in submissions.get('tickers', [])]:
        raise ValueError('SEC company identity mismatch')
    recent = submissions.get('filings', {}).get('recent', {})
    filings = []
    for i, form in enumerate(recent.get('form', [])):
        try:
            filed = recent['filingDate'][i]
            url = filing_url(cik, recent['accessionNumber'][i], recent['primaryDocument'][i])
        except (KeyError, IndexError, TypeError):
            continue
        if form not in {'10-K', '10-Q', '8-K', '20-F', '6-K', '10-K/A', '10-Q/A'} or not url or not _iso(filed) or _iso(filed) > date.today():
            continue
        filings.append({'date': filed, 'type': form, 'title': 'SEC EDGAR company filing', 'url': url})
    filings.sort(key=lambda row: row['date'], reverse=True)
    result = {'status': 'Available', 'company': submissions.get('name') or match['title'],
              'filings': filings[:6], 'financials': []}
    # A failed financials endpoint must not hide successfully retrieved filings.
    try:
        facts = cached('SEC financials', str(cik), lambda: _get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json', agent), 21600)
        result['financials'] = reported_financials(facts, cik)
    except Exception:
        result['status'] = 'Filings available; reported financials unavailable'
    return result
