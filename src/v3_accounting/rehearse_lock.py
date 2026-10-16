"""Explicit REAL RPC lock rehearsal. No publication, trades or key output.

Requires empty authority. Only increments fences/lease timestamps on V3 lock.
Two independent HTTP sessions compete. Use reviewed .env explicitly.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from threading import Barrier
from uuid import uuid4

import requests
from dotenv import dotenv_values
from src.v3_accounting.cloud_cycle import LeaseRPC


def run(env_path):
    config=dotenv_values(env_path)
    sessions=[requests.Session(),requests.Session()]
    rpcs=[LeaseRPC(config.get('SUPABASE_URL',''),config.get('SUPABASE_SECRET_KEY',''),s) for s in sessions]
    owners=[str(uuid4()),str(uuid4())]
    checks=[]
    start=Barrier(2)
    def expect_rejected(i,name,body,expected):
        response=sessions[i].post(rpcs[i].url+name,json=body,headers=rpcs[i].headers,
            timeout=30,allow_redirects=False)
        if response.status_code!=400 or response.json().get('message')!=expected:
            raise ValueError('Expected specific PostgreSQL rejection not observed')
    def acquire(i):
        start.wait(timeout=10)
        try: return i,rpcs[i].acquire(owners[i],30),None
        except ValueError as e: return i,None,str(e)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(acquire,[0,1]))
        winners=[r for r in results if r[1] is not None]
        losers=[r for r in results if r[1] is None]
        if len(winners)!=1 or len(losers)!=1:
            raise ValueError('Expected exactly one competing writer')
        i,lease,_=winners[0]; j=1-i
        if lease['archive_sha256'] is not None or lease['revision']!=0:
            raise ValueError('Nonempty authority; stop rehearsal without publishing')
        checks.append('two independent connections: exactly one winner')
        expect_rejected(j,'v3_acquire',{'p_owner':owners[j],'p_ttl':30},'Writer busy')
        lease=rpcs[i].renew(lease,30)
        checks.append('valid owner renewal preserves head')
        expect_rejected(i,'v3_renew',{'p_owner':owners[i],'p_fence':lease['fence']+1,'p_ttl':30},
                        'Expired or fenced writer')
        checks.append('wrong fencing token rejected')
        # Never publish a synthetic hash, even as an expiry probe.
        print('Competition passed; waiting 32 seconds for real server expiry.',flush=True)
        time.sleep(32)
        newer=rpcs[j].acquire(owners[j],30)
        if newer['fence']<=lease['fence']: raise ValueError('Fence did not advance')
        checks.append('expired lease reacquired with higher fence')
        expect_rejected(i,'v3_renew',{'p_owner':owners[i],'p_fence':lease['fence'],'p_ttl':30},
                        'Expired or fenced writer')
        checks.append('stale owner renewal rejected')
        if newer['archive_sha256'] is not None or newer['ledger_head_sha256'] is not None or newer['revision']!=0:
            raise ValueError('Rehearsal mutated publication head')
        checks.append('no archive or ledger publication; revision remains zero')
        return {'scope':'V3_LOCK_ONLY_REAL_RPC','passed':checks,
                'checked_at':datetime.now(timezone.utc).isoformat(),
                'revision':0,'scheduler_enabled':False,'formal_account_initialized':False}
    finally:
        for s in sessions: s.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--env',required=True)
    args=parser.parse_args()
    result=run(Path(args.env))
    print(json.dumps(result,indent=2))
