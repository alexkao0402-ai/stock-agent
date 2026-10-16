"""Display-only daily prices. Never imported by trading/accounting runners."""
from datetime import datetime, timezone
import math
import re
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from src.config import get_secret
from src.stock_data import _request_json


def price_failure(exc):
    message = str(exc).lower()
    if 'premium' in message:
        return 'Paid access required'
    if 'rate' in message or '429' in message or 'limit' in message:
        return 'Rate limited'
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return 'Connection failed'
    return 'Provider unavailable'


def completed_rows(rows, now=None):
    """Conservative US daily-close view; exclude today's still-forming bar."""
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    result = {}
    for row in rows:
        try:
            day = datetime.strptime(str(row['date']), '%Y-%m-%d').date()
            close = float(row['close'])
        except (TypeError, ValueError, KeyError):
            continue
        if not math.isfinite(close) or close <= 0 or day > local.date():
            continue
        if day == local.date() and (local.hour, local.minute) < (16, 15):
            continue
        result[day.isoformat()] = {'date': day.isoformat(), 'close': close}
    return [result[key] for key in sorted(result)][-180:]


def yahoo_daily(symbol):
    # Do not reuse the strategy's adjusted-price cache as a quoted closing price.
    frame = yf.Ticker(symbol).history(period='1y', auto_adjust=False, actions=False,
                                      raise_errors=True, timeout=12)
    if not isinstance(frame, pd.DataFrame) or frame.empty or 'Close' not in frame:
        raise ValueError('No daily prices returned')
    return [{'date': pd.Timestamp(index).strftime('%Y-%m-%d'), 'close': row['Close']}
            for index, row in frame.iterrows()]


def alpha_daily(symbol):
    data = _request_json({'function': 'TIME_SERIES_DAILY', 'symbol': symbol,
                          'outputsize': 'compact', 'apikey': get_secret('ALPHAVANTAGE_API_KEY')},
                         retries=0, timeout=12)
    metadata = data.get('Meta Data', {})
    if str(metadata.get('2. Symbol', '')).upper() != symbol:
        raise ValueError('Price response symbol mismatch')
    daily = data.get('Time Series (Daily)', {})
    return [{'date': day, 'close': value.get('4. close')}
            for day, value in daily.items() if isinstance(value, dict)]


def market_prices(symbol, cache, now=None):
    if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.\-^]{0,14}', symbol):
        raise ValueError('Invalid ticker')
    statuses = []
    backup = None
    providers = [('Yahoo Finance', lambda: yahoo_daily(symbol), 3600)]
    if get_secret('ALPHAVANTAGE_API_KEY'):
        providers.append(('Alpha Vantage', lambda: alpha_daily(symbol), 21600))
    for provider, loader, ttl in providers:
        try:
            def load():
                rows = completed_rows(loader(), now)
                if not rows:
                    raise ValueError('No completed daily prices')
                return rows
            rows = completed_rows(cache.get('Raw daily prices / ' + provider, symbol, load, ttl), now)
            if not rows:
                raise ValueError('No completed daily prices')
            stale = cache.metadata and 'Stale' in cache.metadata[-1].get('Status', '')
            local_day = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York')).date()
            old = (local_day - datetime.strptime(rows[-1]['date'], '%Y-%m-%d').date()).days > 4
            if stale or old:
                statuses.append({'Data': 'Prices', 'Provider': provider, 'Status': 'Stale backup'})
                if backup is None or rows[-1]['date'] > backup[0][-1]['date']:
                    backup = rows, provider
                continue
            statuses.append({'Data': 'Prices', 'Provider': provider, 'Status': 'Available'})
            return pd.DataFrame(rows), provider, statuses
        except Exception as exc:
            statuses.append({'Data': 'Prices', 'Provider': provider, 'Status': price_failure(exc)})
    if backup:
        return pd.DataFrame(backup[0]), backup[1], statuses
    return pd.DataFrame(columns=['date', 'close']), 'Unavailable', statuses
