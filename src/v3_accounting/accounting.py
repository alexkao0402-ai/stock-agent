"""Append-only local entitlement journal. No data downloads or broker operations.

Only reviewed USD ordinary cash dividends and splits are supported. Ex-date
events must be processed before same-boundary trades. Payments use saved
entitlements, never payment-date positions. Source completeness is external.
"""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import math
import sqlite3
from contextlib import closing

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'V3-CORPORATE-ACTION-ACCOUNTING-1'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def hashed(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def number(value, positive=False):
    result = float(value)
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        raise ValueError('Invalid numeric value')
    return result


def initial(capital):
    return {'cash': number(capital, True), 'positions': {}, 'receivables': {},
            'dividends_earned': 0., 'dividends_paid': 0., 'realized_pnl': 0., 'fees': 0.,
            'processed': {}, 'last_boundary': None, 'last_phase': -1}


def apply(state, event):
    state = json.loads(encoded(state))
    key = event['event_key']
    if not isinstance(key, str) or not key:
        raise ValueError('Permanent event key required')
    if key in state['processed']:
        if state['processed'][key] != hashed(event):
            raise ValueError('Event conflict')
        return state
    boundary = stamp(event['effective_at'])
    if stamp(event['data_asof']) > stamp(event['recorded_at']) or boundary > stamp(event['data_asof']):
        raise ValueError('Future or unavailable evidence')
    if event.get('reviewed') is not True or not event.get('evidence_sha256') or len(event['evidence_sha256']) != 64:
        raise ValueError('Reviewed source evidence required')
    try:
        int(event['evidence_sha256'], 16)
    except ValueError:
        raise ValueError('Invalid evidence hash')
    kind = event['kind']
    phase = {'SPLIT': 0, 'EX_DIVIDEND': 1, 'PAY_DIVIDEND': 2, 'TRADE': 3, 'VALUATION': 4}.get(kind)
    if phase is None:
        raise ValueError('Unsupported action; review required')
    if state['last_boundary']:
        last = stamp(state['last_boundary'])
        if boundary < last or (boundary == last and phase < state['last_phase']):
            raise ValueError('Out-of-order event; rebuild reviewed isolated journal')
    security = event['security_id']
    if not isinstance(security, str) or not security:
        raise ValueError('Stable security identity required')
    position = state['positions'].get(security, {'shares': 0., 'average_cost': 0.})
    if kind == 'EX_DIVIDEND':
        dividend_id = event['dividend_id']
        if not isinstance(dividend_id, str) or not dividend_id or dividend_id in state['receivables']:
            raise ValueError('Duplicate or invalid economic dividend ID')
        if event.get('currency') != 'USD' or event.get('dividend_type') != 'ORDINARY_CASH':
            raise ValueError('Unsupported dividend convention')
        pay_at = event['pay_at']
        if stamp(pay_at) < boundary:
            raise ValueError('Pay date precedes entitlement')
        rate = number(event['amount_per_share'], True)
        amount = position['shares'] * rate
        state['receivables'][dividend_id] = {'security_id': security, 'shares_entitled': position['shares'],
            'amount_per_share': rate, 'amount': amount, 'ex_at': event['effective_at'],
            'pay_at': pay_at, 'paid': False}
        state['dividends_earned'] += amount
    elif kind == 'PAY_DIVIDEND':
        entitlement = state['receivables'].get(event['dividend_id'])
        if entitlement is None or entitlement['paid']:
            raise ValueError('Missing or already paid entitlement')
        if entitlement['security_id'] != security or boundary != stamp(entitlement['pay_at']):
            raise ValueError('Payment identity or reviewed date mismatch')
        state['cash'] += entitlement['amount']
        state['dividends_paid'] += entitlement['amount']
        entitlement['paid'] = True
    elif kind == 'SPLIT':
        ratio = number(event['ratio'], True)
        if position['shares']:
            state['positions'][security] = {'shares': position['shares'] * ratio,
                                           'average_cost': position['average_cost'] / ratio}
        # Existing entitlement is a fixed USD receivable; never scale it again.
    elif kind == 'VALUATION':
        state['last_valuation'] = {'effective_at':event['effective_at'],
                                  'equity':equity(state,event['marks']),
                                  'cash':state['cash'],
                                  'receivable':sum(r['amount'] for r in state['receivables'].values() if not r['paid']),
                                  'marks':event['marks']}
    elif kind == 'TRADE':
        quantity = float(event['quantity'])
        if not math.isfinite(quantity) or quantity == 0:
            raise ValueError('Invalid signed trade quantity')
        price = number(event['fill_price'], True)
        fee = number(event['fee'])
        shares = position['shares'] + quantity
        cash = state['cash'] - quantity * price - fee
        if shares < 0 or cash < 0:
            raise ValueError('Shorting or negative cash prohibited')
        if quantity > 0:
            cost = (position['shares'] * position['average_cost'] + quantity * price + fee) / shares
        else:
            cost = position['average_cost']
            state['realized_pnl'] += -quantity * (price - cost) - fee
        state['cash'] = cash
        state['fees'] += fee
        if shares:
            state['positions'][security] = {'shares': shares, 'average_cost': cost}
        else:
            state['positions'].pop(security, None)
    state['processed'][key] = hashed(event)
    state['last_boundary'] = event['effective_at']
    state['last_phase'] = phase
    for field in ['cash', 'dividends_earned', 'dividends_paid', 'fees']:
        number(state[field])
    if not math.isfinite(state['realized_pnl']):
        raise ValueError('Nonfinite realized P/L')
    for p in state['positions'].values():
        number(p['shares'], True); number(p['average_cost'], True)
    for r in state['receivables'].values():
        number(r['amount'])
    encoded(state)
    return state


def equity(state, marks):
    value = state['cash'] + sum(r['amount'] for r in state['receivables'].values() if not r['paid'])
    for security, position in state['positions'].items():
        value += position['shares'] * number(marks[security], True)
    return value


class Journal:
    def __init__(self, directory):
        directory = Path(directory).resolve()
        # V3 only: cannot point this layer at V2/V12 or synced reference files.
        if not directory.is_relative_to(ROOT/'shadow_forward/V3_ACCOUNTING'):
            raise ValueError('V3 isolated store required')
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory/'corporate_actions.sqlite3'
        with closing(self.connect()) as c, c:
            c.executescript('''CREATE TABLE IF NOT EXISTS journal
                (seq INTEGER PRIMARY KEY, key TEXT UNIQUE, request TEXT, state TEXT, prev TEXT, hash TEXT);
                CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON journal
                BEGIN SELECT RAISE(ABORT,'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON journal
                BEGIN SELECT RAISE(ABORT,'append-only'); END;''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def rows(self, c):
        rows = c.execute('SELECT seq,key,request,state,prev,hash FROM journal ORDER BY seq').fetchall()
        previous = 'GENESIS'
        for seq, key, request, state, prev, digest in rows:
            if prev != previous or hashed([key, request, state, prev]) != digest:
                raise ValueError('Journal integrity failure')
            previous = digest
        if rows:
            init = json.loads(rows[0][2])
            if init['version'] != VERSION or init['code_sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
                raise ValueError('Accounting version changed')
        return rows

    def write(self, event=None, capital=10000):
        if event is not None and event.get('event_key') == 'INITIALIZE':
            raise ValueError('Use initialization API')
        c = self.connect()
        try:
            with c:
                c.execute('BEGIN IMMEDIATE')
                rows = self.rows(c)
                if event is None:
                    event = {'event_key':'INITIALIZE', 'capital':number(capital, True), 'version':VERSION,
                             'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
                for row in rows:
                    if row[1] == event['event_key']:
                        if row[2] != encoded(event):
                            raise ValueError('Immutable event conflict')
                        return {'created':False, 'state':json.loads(row[3])}
                if not rows:
                    if event['event_key'] != 'INITIALIZE':
                        raise ValueError('Initialize first')
                    state = initial(event['capital'])
                else:
                    state = apply(json.loads(rows[-1][3]), event)
                previous = rows[-1][5] if rows else 'GENESIS'
                request, saved = encoded(event), encoded(state)
                c.execute('INSERT INTO journal(key,request,state,prev,hash) VALUES(?,?,?,?,?)',
                          (event['event_key'],request,saved,previous,hashed([event['event_key'],request,saved,previous])))
                return {'created':True, 'state':state}
        finally:
            c.close()

    def inspect(self):
        c = self.connect()
        try:
            rows = self.rows(c)
            return {'events':len(rows), 'state':json.loads(rows[-1][3]) if rows else None}
        finally:
            c.close()

    def batch(self, key, request, calculate):
        """One transaction for actions, simulated fills and valuation watermark."""
        if not isinstance(key,str) or not key or key == 'INITIALIZE':
            raise ValueError('Invalid batch key')
        c=self.connect()
        try:
            with c:
                c.execute('BEGIN IMMEDIATE')
                rows=self.rows(c)
                if not rows:raise ValueError('Initialize first')
                for row in rows:
                    if row[1]==key:
                        if row[2]!=encoded(request):raise ValueError('Immutable batch conflict')
                        return {'created':False,'state':json.loads(row[3])}
                state=calculate(json.loads(rows[-1][3]))
                previous=rows[-1][5]; saved=encoded(state); source=encoded(request)
                c.execute('INSERT INTO journal(key,request,state,prev,hash) VALUES(?,?,?,?,?)',
                          (key,source,saved,previous,hashed([key,source,saved,previous])))
                return {'created':True,'state':state}
        finally:c.close()
