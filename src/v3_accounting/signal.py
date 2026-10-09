"""Isolated forward signal preparation. No orders, fills, or production writes."""
from pathlib import Path
from datetime import datetime,timezone,time
from zoneinfo import ZoneInfo
import argparse
import hashlib
import json
import re
import math
from functools import lru_cache
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
from src.trading_calendar import is_month_end_session,next_session,session_close,is_session

STORE=ROOT/'shadow_forward/V3_ACCOUNTING/integration'
VERSION='V11-TOP3-95-SHADOW-V2-VERIFIED-IPO'
RULES={'version':VERSION,'rank_weights':{'3_1':.25,'6_1':.25,'12_1':.50},'lookbacks':[63,126,252],
       'skip_sessions':21,'top_n':3,'risk_on_exposure':.95,'stock_ma':200,'market_ma':200,
       'execution':'T+1_OPEN','commission_rate':.001,'slippage_rate':.0005,'leverage':False,
       'cash_interest':0,'tie_break':'Input market-cap rank ascending; first rank wins ties',
       'insufficient_candidates':'Equal weight across actual eligible selections; otherwise cash',
       'history_policy':'Only source-bound young listings with complete sessions since first trade are ineligible; unexplained gaps fail closed',
       'partial_momentum_policy':'Keep available formation horizons in cross-sectional ranks; missing required horizons prevent selection',
       'status':'ISOLATED_SHADOW_NOT_OFFICIAL_V12_NOT_BROKER'}

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')

@lru_cache(maxsize=48)
def _session_window(signal_date,calendar_sha256):
    # The file hash is part of the key; reuse cannot hide a calendar revision.
    return tuple(d.strftime('%Y-%m-%d') for d in pd.date_range(pd.Timestamp(signal_date)-pd.Timedelta(days=450),signal_date) if is_session(d))

def immutable(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);encoded=canonical(payload)
    if path.exists():
        if path.read_bytes()!=encoded:raise ValueError('Immutable record conflict')
        return False
    with path.open('xb') as handle:handle.write(encoded)
    return True

def freeze(store=STORE,now=None):
    path=Path(store)/'freeze.json'
    if path.exists():
        payload=json.loads(path.read_text(encoding='utf-8'))
        if payload['rules']!=RULES or payload['signal_code_sha256']!=digest(__file__):raise ValueError('Frozen rules/code mismatch')
        return payload
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Timezone required')
    payload={'rules':RULES,'frozen_at':now.isoformat(),'signal_code_sha256':digest(__file__),
             'calendar_code_sha256':digest(ROOT/'src/trading_calendar.py'),
             'qualification':'Exploratory historical screen only; statistical superiority not established'}
    immutable(path,payload);return payload

def rank_features(features,spy_bull):
    result=features.copy(deep=True)
    ranks=[]
    for horizon in ['3_1','6_1','12_1']:
        column='momentum_'+horizon
        result[column+'_rank']=result[column].rank(method='average',ascending=True,pct=True)
        ranks.append(column+'_rank')
    result['candidate_score']=.25*result[ranks[0]]+.25*result[ranks[1]]+.5*result[ranks[2]]
    result['candidate_rank']=result.candidate_score.rank(method='first',ascending=False)
    result['eligible']=result.exact_month_end_price & result.above_ma200 & result[ranks].notna().all(axis=1)
    result['selected']=False;result['target_weight']=0.
    if spy_bull:
        selected=result[result.eligible].nsmallest(3,'candidate_rank').index
        if len(selected):
            result.loc[selected,'selected']=True;result.loc[selected,'target_weight']=.95/len(selected)
    return result

def indicators(frame,signal_date):
    frame=frame[pd.to_datetime(frame.trade_date)<=pd.Timestamp(signal_date)].sort_values('trade_date')
    if frame.trade_date.duplicated().any():raise ValueError('Duplicate price dates')
    close=pd.to_numeric(frame.adjusted_close,errors='raise')
    if len(close)<253 or close.isna().any() or not np.isfinite(close).all() or (close<=0).any():raise ValueError('Incomplete or invalid history')
    if str(frame.trade_date.iloc[-1])!=signal_date:raise ValueError('Missing signal close')
    mean=float(close.iloc[-200:].mean())
    return {'exact_month_end_price':True,'above_ma200':bool(close.iloc[-1]>mean),
            'adjusted_close':float(close.iloc[-1]),'ma200':mean,
            **{'momentum_'+name:float(close.iloc[-22]/close.iloc[-(lookback+1)]-1) for name,lookback in [('3_1',63),('6_1',126),('12_1',252)]}}

def validate_time(signal_date,captured_at,frozen_at,now):
    stamps=[pd.Timestamp(v) for v in [captured_at,frozen_at,now]]
    if any(s.tzinfo is None for s in stamps):raise ValueError('Timezone required')
    captured,frozen,current=stamps
    if not is_month_end_session(signal_date):raise ValueError('Not a month-end session')
    close=pd.Timestamp(session_close(signal_date))
    opening=pd.Timestamp(datetime.combine(next_session(signal_date),time(9,30),ZoneInfo('America/New_York')))
    if not frozen<close<=captured<=current<opening:raise ValueError('Not genuine timely post-freeze forward input')
    return opening.isoformat()


def verified_indicators(frame,signal_date,listing,sessions):
    """Distinguish a verified new listing from a truncated price download.

Keep available short-horizon indicators in percentile ranks, matching research.
Missing a required 12-1 horizon prevents selection, rather than halting all stocks.
"""
    frame=frame.sort_values('trade_date');dates=frame.trade_date.tolist()
    close=pd.to_numeric(frame.adjusted_close,errors='raise')
    if not dates or frame.trade_date.duplicated().any() or close.isna().any() or not np.isfinite(close).all() or (close<=0).any():
        raise ValueError('Missing or invalid stock price history')
    if dates[-1]!=signal_date:raise ValueError('Missing signal close')
    if len(dates)>=253:
        if dates[-253:]!=sessions[-253:]:raise ValueError('Misaligned session history')
        return {**indicators(frame,signal_date),'history_status':'SUFFICIENT','history_rows':len(dates)}
    if listing is None or listing.get('first_trade_date_ms') in (None,''):
        raise ValueError('Short history lacks source-bound first-trade evidence')
    milliseconds=float(listing['first_trade_date_ms'])
    if not math.isfinite(milliseconds):raise ValueError('Invalid first-trade evidence')
    first=pd.to_datetime(milliseconds,unit='ms',utc=True).tz_convert('America/New_York').date().isoformat()
    if not is_session(first) or first>signal_date:raise ValueError('Invalid first-trade session')
    expected=[day for day in sessions if first<=day<=signal_date]
    if not expected or len(expected)>=253 or dates!=expected:
        raise ValueError('Unexplained price gap; not a verified IPO history')
    mean=float(close.iloc[-200:].mean()) if len(close)>=200 else np.nan
    return {'exact_month_end_price':True,'above_ma200':bool(len(close)>=200 and close.iloc[-1]>mean),
            'adjusted_close':float(close.iloc[-1]),'ma200':mean,
            **{'momentum_'+name:float(close.iloc[-22]/close.iloc[-(lookback+1)]-1) if len(close)>lookback else np.nan
               for name,lookback in [('3_1',63),('6_1',126),('12_1',252)]},
            'history_status':'VERIFIED_IPO_INELIGIBLE','history_rows':len(dates),
            'first_trade_session':first,'listing_evidence':'HASH_BOUND_SELECTION_DETAILS'}

def load_inputs(bundle):
    """Read-only data diagnostic; never create a signal or trading record."""
    bundle=Path(bundle).resolve();manifest_path=bundle/'manifest.json'
    m=json.loads(manifest_path.read_text(encoding='utf-8'))
    hashes=m.get('files',{})
    if not {'monthly_universe.csv','daily_prices.csv'}.issubset(hashes):raise ValueError('Required input hashes missing')
    for filename,expected in hashes.items():
        if Path(filename).name!=filename or (bundle/filename).resolve().parent!=bundle:raise ValueError('Invalid input path')
        if digest(bundle/filename)!=expected:raise ValueError('Input hash mismatch')
    date=m['signal_date']
    if not isinstance(date,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):raise ValueError('Invalid signal date format')
    captured=pd.Timestamp(m['captured_at'])
    if captured.tzinfo is None or captured<pd.Timestamp(session_close(date)):raise ValueError('Signal input unavailable at close')
    u=pd.read_csv(bundle/'monthly_universe.csv');p=pd.read_csv(bundle/'daily_prices.csv')
    u_required={'signal_date','market_cap_rank','ticker','stable_company_id','stable_security_id','company_market_cap','source_timestamp'}
    p_required={'ticker','stable_security_id','trade_date','adjusted_close','source_timestamp'}
    if not u_required.issubset(u) or not p_required.issubset(p):raise ValueError('Incomplete input schema')
    u['market_cap_rank']=pd.to_numeric(u.market_cap_rank,errors='raise')
    u['company_market_cap']=pd.to_numeric(u.company_market_cap,errors='raise')
    u=u.sort_values('market_cap_rank').reset_index(drop=True)
    if len(u)!=10 or u.market_cap_rank.tolist()!=list(range(1,11)):raise ValueError('Expected PIT top10')
    if u[list(u_required)].isna().any().any() or u.ticker.duplicated().any() or u.stable_company_id.duplicated().any() or u.stable_security_id.duplicated().any():raise ValueError('Invalid identities')
    if not u.signal_date.eq(date).all() or not np.isfinite(u.company_market_cap).all() or (u.company_market_cap<=0).any():raise ValueError('Invalid universe date/caps')
    if not u.company_market_cap.is_monotonic_decreasing:raise ValueError('Universe rank/cap conflict')
    listings={}
    if 'selection_details.json' in hashes:
        metadata=json.loads((bundle/'selection_details.json').read_text(encoding='utf-8'))
        if metadata.get('signal_date')!=date or pd.Timestamp(metadata['captured_at'])!=captured:
            raise ValueError('Listing evidence date/availability conflict')
        if not metadata.get('provider_policy') or not re.fullmatch(r'[0-9a-f]{64}',metadata.get('source_hashes',{}).get('yahoo_candidates_sha256','')):
            raise ValueError('Listing source provenance missing')
        records=metadata['selection']
        if len(records)!=len(u) or len({r['ticker'] for r in records})!=len(records):raise ValueError('Invalid listing evidence coverage')
        listings={r['ticker']:r for r in records}
        if set(listings)!=set(u.ticker):raise ValueError('Listing evidence universe conflict')
        for row in u.itertuples():
            evidence=listings[row.ticker]
            if evidence['stable_company_id']!=row.stable_company_id or evidence['stable_security_id']!=row.stable_security_id:
                raise ValueError('Listing evidence identity conflict')
            if evidence['market_cap_rank']!=row.market_cap_rank or float(evidence['company_market_cap'])!=row.company_market_cap:
                raise ValueError('Listing evidence rank/cap conflict')
    p['trade_date']=pd.to_datetime(p.trade_date).dt.strftime('%Y-%m-%d')
    if p[list(p_required)].isna().any().any():raise ValueError('Missing price fields')
    if p.trade_date.gt(date).any():raise ValueError('Future prices in signal input')
    for frame in [u,p]:
        observed=pd.to_datetime(frame.source_timestamp,utc=True,errors='raise')
        if observed.isna().any() or observed.gt(pd.Timestamp(m['captured_at'])).any():raise ValueError('Invalid data availability timestamp')
    spy=indicators(p[p.ticker.eq('SPY')],date)
    rows=[]
    # Require identical recent session coverage to SPY; missing stock dates
    # cannot silently shorten momentum formation windows.
    expected=p[p.ticker.eq('SPY')].sort_values('trade_date').trade_date.iloc[-253:].tolist()
    sessions=list(_session_window(date,digest(ROOT/'src/trading_calendar.py')))
    if expected!=sessions[-253:]:raise ValueError('SPY session calendar incomplete')
    for row in u.itertuples():
        frame=p[p.ticker.eq(row.ticker)]
        if not frame.stable_security_id.eq(row.stable_security_id).all():raise ValueError('Security identity mismatch')
        rows.append({'ticker':row.ticker,'stable_security_id':row.stable_security_id,
                     **verified_indicators(frame,date,listings.get(row.ticker),sessions)})
    ranked=rank_features(pd.DataFrame(rows),spy['above_ma200'])
    return m,manifest_path,spy,ranked


def generate(bundle,store=STORE,now=None):
    store=Path(store);now=now or datetime.now(timezone.utc)
    f=freeze(store,now)
    if f['calendar_code_sha256']!=digest(ROOT/'src/trading_calendar.py'):raise ValueError('Calendar changed after freeze')
    m,manifest_path,spy,ranked=load_inputs(bundle)
    date=m['signal_date'];target=store/'signals'/f'{date}.json'
    recorded=now.isoformat()
    if target.exists():recorded=json.loads(target.read_text(encoding='utf-8'))['recorded_at']
    if pd.Timestamp(recorded)>pd.Timestamp(now):raise ValueError('Future recorded timestamp')
    opening=validate_time(date,m['captured_at'],f['frozen_at'],recorded)
    weights={str(r.ticker):float(r.target_weight) for r in ranked[ranked.selected].itertuples()}
    details=json.loads(ranked.to_json(orient='records'))
    payload={'strategy_version':VERSION,'freeze_sha256':digest(store/'freeze.json'),'signal_date':date,
             'recorded_at':recorded,
             'source_manifest_sha256':digest(manifest_path),'data_asof':m['captured_at'],'execution_rule':'T+1_OPEN',
             'expected_execution_open':opening,'spy_bull':spy['above_ma200'],'target_weights':weights,
             'target_cash_weight':1-sum(weights.values()),'details':details,
             'status':'AWAITING_ISOLATED_SIMULATION','official_v12_mutation':False}
    created=immutable(target,payload)
    return {'path':str(target),'created':created,'payload':payload}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--init',action='store_true');parser.add_argument('--bundle')
    args=parser.parse_args()
    if args.bundle:result=generate(args.bundle)
    elif args.init:result={'freeze':freeze(),'forward_signal_count':len(list((STORE/'signals').glob('*.json')))}
    else:parser.error('Choose --init or --bundle')
    print(json.dumps(result,ensure_ascii=False,indent=2))
