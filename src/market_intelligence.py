"""Best-effort research context only; never an input to Frozen V12 or V3."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import yfinance as yf

from src.config import get_secret
from src.stock_data import _request_json, DataProviderError
from src.market_prices import market_prices
from src.sec_research import sec_context
from src.research_cache import ResearchCache


def valid_symbol(symbol):
    return isinstance(symbol, str) and bool(re.fullmatch(r'[A-Z0-9^][A-Z0-9.\-^]{0,14}', symbol))


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _link(value):
    return value if isinstance(value, str) and urlparse(value).scheme in {'https', 'http'} and urlparse(value).hostname else ''


def _failure(exc):
    text = str(exc).lower()
    if 'premium' in text:
        return 'Paid access required'
    if 'rate' in text or '429' in text or 'limit' in text:
        return 'Rate limited'
    if 'invalid' in text and 'key' in text:
        return 'Invalid API key'
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return 'Connection failed'
    return 'Provider unavailable'


def yahoo_overview(info):
    if not isinstance(info, dict) or not any(info.get(k) is not None for k in ('longName','marketCap','trailingEps','totalRevenue')):
        return {}
    gross_margin = _number(info.get('grossMargins'))
    return {
        '公司名稱': info.get('longName') or info.get('shortName'),
        '產業別': info.get('industry'), '市值': _number(info.get('marketCap')),
        '本益比': _number(info.get('trailingPE')), '每股盈餘': _number(info.get('trailingEps')),
        '毛利率': None if gross_margin is None else gross_margin * 100,
        '營收(近12個月)': _number(info.get('totalRevenue')),
        '營業利益率': _number(info.get('operatingMargins')),
        '股價淨值比': _number(info.get('priceToBook')),
        '52週最高價': _number(info.get('fiftyTwoWeekHigh')),
        '52週最低價': _number(info.get('fiftyTwoWeekLow')),
        '公司簡介': info.get('longBusinessSummary'),
    }


def normalize_news(items):
    rows, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        content = item.get('content') or item
        if not isinstance(content, dict):
            continue
        link = content.get('canonicalUrl') or content.get('clickThroughUrl') or {}
        url = _link(link.get('url') if isinstance(link, dict) else link) or _link(content.get('link') or content.get('url'))
        title = content.get('title')
        if not title or not url or url in seen:
            continue
        seen.add(url)
        provider = content.get('provider') or {}
        date = content.get('pubDate') or content.get('time_published') or ''
        if not date and isinstance(content.get('providerPublishTime'), (int, float)):
            date = datetime.fromtimestamp(content['providerPublishTime'], timezone.utc).isoformat()
        rows.append({'title':str(title), 'url':url, 'source':(provider.get('displayName') if isinstance(provider, dict) else str(provider)) or content.get('source') or 'Yahoo Finance',
                     'time_published':str(date), 'summary':content.get('summary') or '',
                     'overall_sentiment_label':'Not scored'})
    return rows


def relevant_news(items, symbol, company=None, now=None):
    """Conservative headline matching, not verification of the publisher's claims."""
    now = now or datetime.now(timezone.utc)
    # Only a verified provider company name may supply aliases. Do not invent a name from a ticker.
    name = re.sub(r'\b(incorporated|corporation|company|limited|inc|corp|ltd|plc)\b\.?', '', company or '', flags=re.I)
    name = re.sub(r'\s+', ' ', name).strip(' ,.-')
    aliases = [name] if len(name) >= 4 else []
    aliases += {'GOOG': ['Alphabet', 'Google'], 'GOOGL': ['Alphabet', 'Google'],
                'META': ['Meta Platforms'], 'NVDA': ['NVIDIA']}.get(symbol, [])
    ambiguous = {'apple', 'meta', 'block', 'target', 'gap', 'visa', 'cat', 'cost', 'all', 'on'}
    rows, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not _link(item.get('url')):
            continue
        title = str(item.get('title') or '')
        # RSS titles often append a publisher. Do not match a company mentioned only as publisher.
        headline = title.rsplit(' - ', 1)[0]
        raw_date = str(item.get('time_published') or '')
        try:
            published = datetime.strptime(raw_date, '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc) if re.fullmatch(r'\d{8}T\d{6}', raw_date) else datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        age = (now - published).total_seconds()
        if not 0 <= age <= 7 * 86400:
            continue
        escaped = re.escape(symbol)
        strong_ticker = re.search(r'(?:\$|\bNASDAQ\s*:\s*|\bNYSE\s*:\s*)' + escaped + r'\b|\(' + escaped + r'\)', headline, re.I)
        # Unknown/common-word tickers must use explicit $/exchange/parenthesis notation.
        unambiguous_tickers = {'NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'GOOGL', 'TSLA', 'AVGO', 'NFLX', 'INTC'}
        plain_ticker = symbol in unambiguous_tickers and re.search(r'(?<![\w])' + escaped + r'(?![\w])', headline)
        match = next((alias for alias in aliases if re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', headline, re.I)
                      and (alias.lower() not in ambiguous or re.search(r'\b(stock|shares|earnings|revenue|iphone|ipad|macbook|ceo|dividend)\b', headline, re.I))), None)
        if not (strong_ticker or plain_ticker or match):
            continue
        fingerprint = re.sub(r'\W+', '', headline).lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rows.append({**item, 'time_published': published.astimezone(timezone.utc).isoformat(),
                     'relevance_reason': f'Headline matches {match or symbol}'})
    rows.sort(key=lambda row: row['time_published'], reverse=True)
    return rows[:10]


def search_news(symbol, company):
    response = requests.get('https://news.google.com/rss/search', params={
        'q':f'("{company or symbol}" OR "{symbol}") stock when:7d',
        'hl':'en-US','gl':'US','ceid':'US:en'}, timeout=15, allow_redirects=False)
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError('Oversized news feed')
    rows, seen = [], set()
    for item in ET.fromstring(response.content).findall('./channel/item'):
        title, url = item.findtext('title'), _link(item.findtext('link'))
        if not title or not url or url in seen:
            continue
        seen.add(url)
        date = item.findtext('pubDate') or ''
        try:
            date = parsedate_to_datetime(date).isoformat()
        except (ValueError, TypeError):
            pass
        rows.append({'title':title, 'url':url, 'source':item.findtext('source') or 'Google News search',
                     'time_published':date, 'summary':'', 'overall_sentiment_label':'Not scored'})
    rows.sort(key=lambda row:row['time_published'], reverse=True)
    return rows[:10]


def normalize_filings(raw):
    items = raw.get('filings', []) if isinstance(raw, dict) else raw
    return [{'date':str(item.get('date') or item.get('filingDate') or '')[:10],
             'type':str(item.get('type') or item.get('formType') or 'SEC Filing'),
             'title':str(item.get('title') or item.get('description') or 'Company filing'),
             'url':_link(item.get('edgarUrl') or item.get('url'))}
            for item in (items if isinstance(items, list) else [])[:6] if isinstance(item, dict)]


def market_payload(symbol):
    if not valid_symbol(symbol):
        raise ValueError('Enter a valid ticker, for example NVDA, AAPL or BRK-B')
    statuses = []
    cache = ResearchCache()
    def fetch(section, provider, fn, empty):
        try:
            result = fn() if isinstance(empty, pd.DataFrame) else cache.get(section + ' / ' + provider, symbol, fn)
            available = not result.empty if isinstance(result, pd.DataFrame) else bool(result)
            statuses.append({'Data':section,'Provider':provider,'Status':'Available' if available else 'No data'})
            return result
        except Exception as exc:
            statuses.append({'Data':section,'Provider':provider,'Status':_failure(exc)})
            return empty

    prices, price_source, price_status = market_prices(symbol, cache)
    statuses.extend(price_status)
    ticker = yf.Ticker(symbol)
    overview = fetch('Fundamentals','Yahoo Finance',lambda:yahoo_overview(ticker.get_info()),{})
    fundamentals_source = 'Yahoo Finance' if overview else 'Unavailable'
    if not overview and get_secret('ALPHAVANTAGE_API_KEY'):
        def alpha_overview():
            data = _request_json({'function':'OVERVIEW','symbol':symbol,'apikey':get_secret('ALPHAVANTAGE_API_KEY')}, retries=0)
            if not data.get('Symbol'):
                return {}
            gross, revenue = _number(data.get('GrossProfitTTM')), _number(data.get('RevenueTTM'))
            return {'公司名稱':data.get('Name'),'市值':_number(data.get('MarketCapitalization')),
                    '本益比':_number(data.get('PERatio')),'每股盈餘':_number(data.get('EPS')),
                    '毛利率':gross/revenue*100 if gross is not None and revenue else None,
                    '營業利益率':_number(data.get('OperatingMarginTTM'))}
        overview = fetch('Fundamentals','Alpha Vantage',alpha_overview,{})
        if overview:
            fundamentals_source = 'Alpha Vantage'
    try:
        sec = sec_context(symbol, cache.get)
        statuses.append({'Data': 'SEC research', 'Provider': 'SEC EDGAR', 'Status': sec.get('status', 'Provider unavailable')})
    except Exception as exc:
        sec = {}
        statuses.append({'Data': 'SEC research', 'Provider': 'SEC EDGAR', 'Status': _failure(exc)})
    if not overview.get('公司名稱') and sec.get('company'):
        overview = {**overview, '公司名稱': sec['company']}
    if fundamentals_source == 'Unavailable' and sec.get('financials'):
        fundamentals_source = 'SEC EDGAR (reported financials; valuation metrics unavailable)'
    company = sec.get('company') or overview.get('公司名稱')
    news = fetch('News','Yahoo Finance',lambda:relevant_news(normalize_news(ticker.get_news(count=10)), symbol, company),[])
    news_source = 'Yahoo Finance' if news else 'Unavailable'
    if not news:
        news = fetch('News','Google News search',lambda:relevant_news(search_news(symbol, company), symbol, company),[])
        if news:
            news_source = 'Google News search'
    if not news and get_secret('ALPHAVANTAGE_API_KEY'):
        def alpha_news():
            data = _request_json({'function':'NEWS_SENTIMENT','tickers':symbol,'limit':10,'apikey':get_secret('ALPHAVANTAGE_API_KEY')}, retries=0)
            return relevant_news(normalize_news(data.get('feed',[])), symbol, company)
        news = fetch('News','Alpha Vantage',alpha_news,[])
        if news:
            news_source = 'Alpha Vantage'
    def earnings():
        frame = ticker.get_earnings_dates(limit=4)
        if not isinstance(frame, pd.DataFrame):
            return []
        return [{'date':pd.Timestamp(index).strftime('%Y-%m-%d'),
                 'estimate':_number(row.get('EPS Estimate')),'reported':_number(row.get('Reported EPS')),
                 'surprise':_number(row.get('Surprise(%)'))} for index,row in frame.head(4).iterrows()]
    earnings_rows = fetch('Earnings dates','Yahoo Finance',earnings,[])
    # Recheck cached headlines against the current clock (old news must not look fresh).
    news = relevant_news(news, symbol, company)
    filings = sec.get('filings') or fetch('SEC / company filings','Yahoo Finance',lambda:normalize_filings(ticker.get_sec_filings()),[])
    return {'prices':prices, 'overview':overview, 'news':news, 'earnings':earnings_rows,
            'filings':filings,'source':price_source, 'fundamentals_source':fundamentals_source,
            'news_source':news_source if news else 'Unavailable','provider_status':statuses,
            'reported_financials': sec.get('financials', []), 'cache_status': cache.metadata,
            'fetched_at':datetime.now(timezone.utc).isoformat()}
