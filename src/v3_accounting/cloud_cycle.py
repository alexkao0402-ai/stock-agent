"""Opt-in V3 cloud coordinator. No credentials discovery or automatic execution.

Requires pre-seeded authoritative cloud head; does not initialize formal capital.
RPC migration and real concurrent PostgreSQL tests remain deployment prerequisites.
"""
from contextlib import closing
from uuid import UUID, uuid4
from urllib.parse import urlparse

from src.v3_accounting.accounting import Journal
from src.v3_accounting.backup import make_snapshot, restore_snapshot


def digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid cloud digest')
    return value


def checked_head(row, owner):
    if not isinstance(row, dict) or row.get('stream') != 'V3_ACCOUNTING' or row.get('owner') != owner:
        raise ValueError('Unexpected cloud lease identity')
    for field in ('fence', 'revision'):
        if type(row.get(field)) is not int or row[field] < (1 if field == 'fence' else 0):
            raise ValueError('Invalid cloud version')
    from src.v3_accounting.accounting import stamp
    stamp(row['expires_at'])
    for field in ('archive_sha256', 'ledger_head_sha256'):
        if row.get(field) is not None: digest(row[field])
    if (row.get('archive_sha256') is None) != (row.get('ledger_head_sha256') is None):
        raise ValueError('Incomplete authoritative head')
    return dict(row)


class LeaseRPC:
    def __init__(self, url, secret, session=None):
        parsed=urlparse(url)
        if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co')
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or parsed.username or parsed.port):
            raise ValueError('Supabase HTTPS project root required')
        if not secret: raise ValueError('Server credential required')
        if session is None:
            import requests
            session=requests.Session()
        self.session=session; self.url=url.rstrip('/')+'/rest/v1/rpc/'
        self.headers={'apikey':secret,'Authorization':'Bearer '+secret}

    def call(self, name, body):
        try:
            response=self.session.post(self.url+name,json=body,headers=self.headers,
                                       timeout=30,allow_redirects=False)
        except Exception:
            # Do not expose connection URLs, headers, secret or response bodies.
            raise ValueError('Cloud RPC transport failed; outcome may be unknown') from None
        if response.status_code != 200:
            raise ValueError('Cloud RPC rejected (HTTP %s)' % response.status_code)
        try:
            row=response.json()
            if isinstance(row,list) and len(row)==1: row=row[0]
            return checked_head(row,body['p_owner'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Invalid cloud RPC response') from None

    def acquire(self, owner, ttl=300):
        if str(UUID(owner)) != owner or type(ttl) is not int or not 30<=ttl<=300:
            raise ValueError('Canonical owner UUID and bounded TTL required')
        return self.call('v3_acquire',{'p_owner':owner,'p_ttl':ttl})

    def renew(self, lease, ttl=300):
        updated=self.call('v3_renew',{'p_owner':lease['owner'],'p_fence':lease['fence'],'p_ttl':ttl})
        if any(updated[k] != lease[k] for k in ('fence','revision','archive_sha256','ledger_head_sha256')):
            raise ValueError('Authoritative head changed during lease')
        return updated

    def publish(self, lease, archive, ledger):
        result=self.call('v3_publish',{'p_owner':lease['owner'],'p_fence':lease['fence'],
            'p_revision':lease['revision'],'p_archive_sha256':digest(archive),
            'p_ledger_head_sha256':digest(ledger)})
        if (result['fence'] != lease['fence'] or result['revision'] != lease['revision']+1
            or result['archive_sha256'] != archive or result['ledger_head_sha256'] != ledger):
            raise ValueError('Publication receipt mismatch')
        return result


def chain(store):
    journal=Journal(store)
    with closing(journal.connect()) as conn:
        return [row[5] for row in journal.rows(conn)]


def run_cloud_cycle(rpc, storage, destination, backup_key, review_key, calculate, *, now, owner=None):
    """Calculate only in newly restored workspace; publication is the commit point.

    Caller supplies a reviewed Runner operation, not broker/UI side effects.
    A lost publish response is NOT retried by recalculating. Acquire and inspect
    the authority on recovery, or retry the identical RPC while lease remains valid.
    """
    owner=owner or str(uuid4())
    lease=rpc.acquire(owner)
    if lease['archive_sha256'] is None:
        raise ValueError('Reviewed initial cloud head required; no automatic bootstrap')
    data=storage.download(lease['archive_sha256'])
    info=restore_snapshot(data,destination,backup_key,review_key,lease['archive_sha256'],now)
    if info['head'] != lease['ledger_head_sha256']:
        raise ValueError('Cloud authority and signed ledger disagree')
    before=chain(destination)
    lease=rpc.renew(lease)
    calculate(destination)
    after=chain(destination)
    if after[:len(before)] != before or len(after)<len(before):
        raise ValueError('Candidate does not extend authoritative ledger')
    data,receipt=make_snapshot(destination,backup_key,review_key,now)
    lease=rpc.renew(lease)
    upload=storage.upload(data)
    if upload.get('readback_verified') is not True or upload.get('archive_sha256') != receipt['archive_sha256']:
        raise ValueError('Verified immutable upload required')
    lease=rpc.renew(lease)
    published=rpc.publish(lease,receipt['archive_sha256'],receipt['head'])
    return {'status':'PUBLISHED','revision':published['revision'],
            'archive_sha256':published['archive_sha256'],'events':receipt['events'],
            'head':receipt['head'],'scheduler_enabled':False}
