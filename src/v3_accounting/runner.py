"""Isolated V3 integration. No scheduler, broker, cloud writes or data downloads."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import math
import os
from zoneinfo import ZoneInfo

from src.v3_accounting.signal import freeze, generate, RULES, VERSION as SIGNAL_VERSION, immutable
from src.paper_accounting import PortfolioState, Position, build_order_plan
from src.trading_calendar import session_open, session_close, next_session, previous_session
from src.v3_accounting.accounting import ROOT, VERSION, Journal, apply, equity, stamp, number
from src.v3_accounting.evidence import read_bundle, digest, archive_bundle
from src.v3_accounting.payment_policy import POLICY, validate_ex_dividend
from src.v3_accounting.benchmark import BENCHMARK_POLICY, process_accounts

STORE=ROOT/'shadow_forward/V3_ACCOUNTING/integration'


def dependencies():
    paths=['src/v3_accounting/accounting.py','src/v3_accounting/runner.py','src/v3_accounting/evidence.py',
           'src/v3_accounting/payment_policy.py','src/v3_accounting/benchmark.py','src/v3_accounting/signal.py','src/paper_accounting.py',
           'src/trading_calendar.py']
    return {name:digest(ROOT/name) for name in paths}


class Runner:
    def __init__(self,store=STORE):
        self.store=Path(store).resolve()
        if not self.store.is_relative_to(ROOT/'shadow_forward/V3_ACCOUNTING'):
            raise ValueError('V3 isolated store required')

    def init(self,now=None):
        now=now or datetime.now(timezone.utc)
        rules=freeze(self.store,now)
        config={'accounting_version':VERSION,'signal_version':SIGNAL_VERSION,
                'dependencies':dependencies(),'freeze_sha256':digest(self.store/'freeze.json'),
                'cash_policy':POLICY,
                'benchmark_policy':BENCHMARK_POLICY,'initial_capital':10000,
                'qualification':'ISOLATED_V3_NOT_OFFICIAL_V12','scheduler_enabled':False}
        immutable(self.store/'integration_freeze.json',config)
        Journal(self.store).write()
        return self.status()

    def checked(self):
        config=json.loads((self.store/'integration_freeze.json').read_text())
        if (config.get('benchmark_policy')!=BENCHMARK_POLICY or config.get('initial_capital')!=10000
            or config.get('cash_policy')!=POLICY or config['dependencies']!=dependencies()
            or config['freeze_sha256']!=digest(self.store/'freeze.json')):
            raise ValueError('Frozen integration dependency changed')
        freeze(self.store)
        return Journal(self.store)

    def status(self):
        path=self.store/'corporate_actions.sqlite3'
        if not path.exists():return {'status':'NOT_INITIALIZED','scheduler_enabled':False}
        journal=self.checked();info=journal.inspect()
        return {'status':'LOCAL_ONLY','events':info['events'],'scheduler_enabled':False,
                'cloud_connected':False,'broker_connected':False,'accounting_version':VERSION}

    def signal(self,bundle,now=None):
        self.checked()
        return generate(bundle,self.store,now or datetime.now(timezone.utc))

    def process(self,bundle,key,*,signal_bundle=None,now=None):
        now=now or datetime.now(timezone.utc);journal=self.checked()
        market,evidence=read_bundle(bundle,key,now.isoformat())
        date=market['date'];kind=market['kind']
        if kind not in {'OPEN','CLOSE'}:raise ValueError('Invalid market kind')
        boundary=(session_open(date) if kind=='OPEN' else session_close(date)).isoformat()
        if not stamp(boundary)<=stamp(market['data_asof'])<=stamp(market['captured_at']):
            raise ValueError('Unavailable prices')
        if stamp(market['captured_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()!=date:
            raise ValueError('Historical capture cannot be promoted')
        signal=None
        if kind=='OPEN':
            if signal_bundle is None:raise ValueError('Timely original signal required')
            signal=generate(signal_bundle,self.store,now)['payload']
            if date!=next_session(signal['signal_date']).isoformat():raise ValueError('Not T+1 execution')
        elif signal_bundle is not None:raise ValueError('Close cannot create signal')
        marks=market['marks']
        for security,price in marks.items():
            if not security:raise ValueError('Missing security identity')
            number(price,True)
        request={'market':market,'evidence':evidence,'signal':signal}
        archive_bundle(bundle,evidence,self.store)

        def calculate(state):
            latest=state.get('last_valuation')
            if latest:
                last=stamp(latest['effective_at'])
                last_date=last.astimezone(ZoneInfo('America/New_York')).date().isoformat()
                if (last_date!=date and last_date!=previous_session(date).isoformat()) or (kind=='OPEN' and last_date==date):
                    raise ValueError('Missing previous session or duplicate open')
                if last_date!=date and latest['kind']!='CLOSE':raise ValueError('Missing execution-day close')
                if last_date==date and latest['kind']=='CLOSE':raise ValueError('Duplicate session close')
            elif kind=='CLOSE':raise ValueError('No forward execution; cannot manufacture performance')
            start=state.get('last_boundary') or json.loads((self.store/'freeze.json').read_text())['frozen_at']
            coverage=market['coverage']
            if coverage.get('confirmed') is not True or stamp(coverage['from'])!=stamp(start) or stamp(coverage['through'])!=stamp(boundary):
                raise ValueError('Corporate action coverage gap')
            mapping={r['ticker']:r['stable_security_id'] for r in signal['details']} if signal else {}
            target={mapping[t]:w for t,w in signal['target_weights'].items()} if signal else {}
            if len(target)!=(len(signal['target_weights']) if signal else 0):raise ValueError('Security collision')
            required=set(state['positions'])|set(target)|{r['security_id'] for r in state['receivables'].values() if not r['paid']}
            benchmark_ids={entry['security_id'] for entry in market['benchmarks'].values()}
            if (required|set(mapping.values())) & benchmark_ids:
                raise ValueError('Stock and benchmark identity collision')
            required|=benchmark_ids
            existing=state.get('benchmarks',{})
            if latest and set(existing)!={'SPY','QQQ'}: raise ValueError('Existing benchmark accounts missing')
            for account in existing.values():
                if stamp(account['state']['last_boundary'])!=stamp(start):
                    raise ValueError('Benchmark valuation boundary mismatch')
            if not required.issubset(set(coverage['security_ids'])) or not (set(state['positions'])|set(target)|benchmark_ids).issubset(marks):
                raise ValueError('Missing required coverage or marks')
            actions=market['actions']
            phases={'SPLIT':0,'EX_DIVIDEND':1,'PAY_DIVIDEND':2}
            if any(a['kind'] not in phases for a in actions):raise ValueError('Unsupported corporate action')
            sort_key=lambda a:(stamp(a['effective_at']),phases[a['kind']])
            if actions!=sorted(actions,key=sort_key):raise ValueError('Unordered corporate actions')
            for action in actions:
                if action['security_id'] not in required or not stamp(start)<stamp(action['effective_at'])<=stamp(boundary):
                    raise ValueError('Corporate action outside reviewed scope')
                validate_ex_dividend(action)
                if action['security_id'] in benchmark_ids: continue
                normalized={**action,'reviewed':True,'data_asof':market['data_asof'],'recorded_at':evidence['review']['payload']['reviewed_at']}
                state=apply(state,normalized)
            # An unpaid due receivable must be accounted for even after selling.
            if any(not r['paid'] and stamp(r['pay_at'])<=stamp(boundary) for r in state['receivables'].values()):
                raise ValueError('Due dividend payment missing')
            benchmarks=process_accounts(existing,market,evidence,boundary,10000,
                RULES['commission_rate'],RULES['slippage_rate'])
            orders=[]
            if kind=='OPEN':
                before=equity(state,marks)
                tradable=before-sum(r['amount'] for r in state['receivables'].values() if not r['paid'])
                adjusted={s:w*before/tradable for s,w in target.items()} if tradable>0 else {}
                if target and (tradable<=0 or sum(adjusted.values())>1):
                    raise ValueError('Receivable unavailable for frozen allocation')
                positions={s:Position(p['shares'],p['average_cost']) for s,p in state['positions'].items()}
                plan=build_order_plan(PortfolioState(state['cash'],positions),marks,adjusted,
                                      commission_rate=RULES['commission_rate'],slippage_rate=RULES['slippage_rate'])
                for security,weight in target.items():
                    if not math.isclose(plan.estimated_final_shares.get(security,0),before*weight/marks[security],abs_tol=1e-7):
                        raise ValueError('Unavailable cash would clip frozen allocation')
                for order in plan.orders:
                    action={'kind':'TRADE','event_key':f'TRADE:{date}:{order.sequence}',
                            'security_id':order.ticker,'effective_at':boundary,'data_asof':market['data_asof'],
                            'recorded_at':evidence['review']['payload']['reviewed_at'],'reviewed':True,
                            'evidence_sha256':market['price_source_sha256'],
                            'quantity':order.shares if order.side=='BUY' else -order.shares,
                            'fill_price':order.estimated_fill_price,'fee':order.estimated_commission}
                    state=apply(state,action)
                    orders.append({**action,'expected_price':order.expected_price,
                                   'slippage':order.estimated_slippage_cost,'reason':'V2 frozen target / V3 accounting'})
                costs=sum(o['fee']+o['slippage'] for o in orders)
                if not math.isclose(before-equity(state,marks),costs,abs_tol=1e-7):raise ValueError('Fill reconciliation failed')
                state['latest_execution']={'date':date,'orders':orders,'costs':costs,'signal':signal}
            valuation={'kind':'VALUATION','event_key':f'{kind}-MARK:{date}','security_id':'PORTFOLIO',
                       'effective_at':boundary,'data_asof':market['data_asof'],
                       'recorded_at':evidence['review']['payload']['reviewed_at'],'reviewed':True,
                       'evidence_sha256':market['price_source_sha256'],'marks':marks}
            state=apply(state,valuation)
            state['last_valuation']['kind']=kind
            state['benchmarks']=benchmarks
            return state

        # Entire day either commits or rolls back; retries never regenerate fills.
        result=journal.batch(f'{kind}:{date}',request,calculate)
        return {'created':result['created'],'kind':kind,'date':date,
                'valuation':result['state']['last_valuation'],
                'benchmarks':{t:a['state']['last_valuation'] for t,a in result['state']['benchmarks'].items()},
                'scheduler_enabled':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','init','signal','cycle'])
    parser.add_argument('--bundle');parser.add_argument('--signal-bundle')
    args=parser.parse_args();runner=Runner()
    if args.command=='status':result=runner.status()
    elif args.command=='init':result=runner.init()
    elif args.command=='signal':result=runner.signal(args.bundle)
    else:result=runner.process(args.bundle,os.getenv('V3_REVIEW_HMAC_KEY',''),signal_bundle=args.signal_bundle)
    print(json.dumps(result,ensure_ascii=False,indent=2))
