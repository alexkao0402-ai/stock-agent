"""Pure benchmark primitives; no journal initialization, approvals or cloud writes.

100% initial buy-and-hold allocation, net of entry costs. Dividend cash is held,
not reinvested. Caller must provide reviewed ETF identity and raw OPEN evidence.
"""
from src.v3_accounting.accounting import initial, apply, number, stamp, equity
from src.v3_accounting.payment_policy import POLICY, validate_ex_dividend

BENCHMARK_POLICY = 'ETF_BUY_HOLD_DIVIDENDS_CASH_V1'


def open_benchmark(capital, ticker, security_id, raw_open, event,
                   *, v3_execution_at, commission, slippage, pre_entry_state=None):
    if ticker not in {'SPY', 'QQQ'} or not security_id:
        raise ValueError('Reviewed SPY/QQQ identity required')
    if event.get('kind') != 'TRADE' or event.get('security_id') != security_id:
        raise ValueError('Matching trade evidence required')
    if stamp(event['effective_at']) != stamp(v3_execution_at):
        raise ValueError('Benchmark must start at V3 execution boundary')
    capital = number(capital, True)
    price = number(raw_open, True)
    commission = number(commission); slippage = number(slippage)
    if commission >= 1 or slippage >= 1:
        raise ValueError('Cost rates must be fractions below one')
    fill = price * (1 + slippage)
    quantity = capital / (fill * (1 + commission))
    fee = quantity * fill * commission
    # A tiny reserve prevents binary rounding from becoming negative cash.
    quantity *= (1 - 1e-12)
    fee = quantity * fill * commission
    if any(field in event for field in ('quantity', 'fill_price', 'fee')):
        raise ValueError('Do not overwrite saved fill fields')
    base=initial(capital) if pre_entry_state is None else pre_entry_state
    if base['positions'] or base['cash']!=capital or base['dividends_earned']!=0:
        raise ValueError('Benchmark entry requires untouched initial capital')
    entry={**event, 'quantity':quantity,'fill_price':fill,'fee':fee}
    state = apply(base,entry)
    return {'ticker': ticker, 'security_id': security_id,
            'initial_capital': capital, 'start_at': v3_execution_at,
            'policy': BENCHMARK_POLICY, 'cash_policy': POLICY,
            'commission_rate': commission, 'slippage_rate': slippage,
            'entry_fill':{**entry,'expected_price':price,'slippage':quantity*(fill-price),
                          'reason':'Initial buy-and-hold benchmark allocation'},
            'state': state}


def apply_benchmark(account, event):
    if account.get('policy') != BENCHMARK_POLICY or account.get('cash_policy') != POLICY:
        raise ValueError('Benchmark policy changed')
    if event.get('security_id') != account['security_id']:
        raise ValueError('Benchmark identity mismatch')
    if event.get('kind') not in {'SPLIT', 'EX_DIVIDEND', 'PAY_DIVIDEND', 'VALUATION'}:
        raise ValueError('Buy-and-hold benchmark cannot rebalance')
    validate_ex_dividend(event)
    return {**account, 'state': apply(account['state'], event)}


def definitions(market, source_hashes):
    entries=market.get('benchmarks')
    if not isinstance(entries,dict) or set(entries)!={'SPY','QQQ'}:
        raise ValueError('Reviewed SPY and QQQ benchmark definitions required')
    ids=[]
    for ticker,entry in entries.items():
        if (not isinstance(entry,dict) or entry.get('instrument_type')!='ETF'
            or entry.get('currency')!='USD' or not isinstance(entry.get('security_id'),str)
            or not entry['security_id'] or entry.get('identity_source_sha256') not in source_hashes):
            raise ValueError('Bound USD ETF identity source required')
        ids.append(entry['security_id'])
    if len(set(ids))!=2: raise ValueError('Benchmark security identity collision')
    return entries


def process_accounts(existing, market, evidence, boundary, capital, commission, slippage):
    """Return both candidate states; caller commits alongside V3 in ONE batch."""
    results={}
    review_at=evidence['review']['payload']['reviewed_at']
    for ticker,definition in market['benchmarks'].items():
        security=definition['security_id']
        account=existing.get(ticker)
        if account:
            if account.get('definition')!=definition:
                raise ValueError('Benchmark identity definition changed')
            base=account['state']
        else:
            if market['kind']!='OPEN': raise ValueError('Benchmark needs initial OPEN')
            base=initial(capital)
        for action in market['actions']:
            if action['security_id']!=security: continue
            validate_ex_dividend(action)
            normalized={**action,'reviewed':True,'data_asof':market['data_asof'],'recorded_at':review_at}
            base=apply(base,normalized)
        if any(not r['paid'] and stamp(r['pay_at'])<=stamp(boundary) for r in base['receivables'].values()):
            raise ValueError('Benchmark due dividend payment missing')
        if account is None:
            trade={'kind':'TRADE','event_key':f'BENCHMARK-ENTRY:{ticker}:{market["date"]}',
                   'security_id':security,'effective_at':boundary,'data_asof':market['data_asof'],
                   'recorded_at':review_at,'reviewed':True,'evidence_sha256':market['price_source_sha256']}
            account=open_benchmark(capital,ticker,security,market['marks'][security],trade,
                v3_execution_at=boundary,commission=commission,slippage=slippage,pre_entry_state=base)
            account['definition']=definition
        else:
            account={**account,'state':base}
        mark={'kind':'VALUATION','event_key':f'BENCHMARK-MARK:{ticker}:{market["kind"]}:{market["date"]}',
              'security_id':security,'effective_at':boundary,'data_asof':market['data_asof'],
              'recorded_at':review_at,'reviewed':True,'evidence_sha256':market['price_source_sha256'],
              'marks':market['marks']}
        account=apply_benchmark(account,mark)
        account['state']['last_valuation']['kind']=market['kind']
        results[ticker]=account
    return results
