"""Read already captured sources with an independently configured review key.

No online provider, no automatic approval. HMAC proves review-key possession,
not truth/completeness of the reviewer's economic claims.
"""
from pathlib import Path
import hashlib
import hmac
import json
from datetime import timezone
from src.v3_accounting.accounting import encoded, stamp
from src.v3_accounting.benchmark import definitions


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def signature(payload, key):
    if not isinstance(key,str) or len(key)<32:raise ValueError('Dedicated V3 review key required (32+ characters)')
    return hmac.new(key.encode(),encoded(payload).encode(),hashlib.sha256).hexdigest()


def read_bundle(directory, key, now):
    directory=Path(directory).resolve()
    review=json.loads((directory/'review.json').read_text(encoding='utf-8'))
    signed=review['payload']
    if not hmac.compare_digest(signature(signed,key),review['signature']):
        raise ValueError('Review signature mismatch')
    if signed.get('approved') is not True or not signed.get('reviewer') or not signed.get('coverage_note'):
        raise ValueError('Scoped review required')
    files=signed['files']
    if 'market.json' not in files or not any(name.startswith('sources/') for name in files):
        raise ValueError('Market and source originals required')
    for name,sha in files.items():
        if Path(name).is_absolute() or '..' in Path(name).parts or (name!='market.json' and not name.startswith('sources/')):
            raise ValueError('Unsupported evidence filename')
        path=(directory/name).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or digest(path)!=sha:
            raise ValueError('Evidence path/hash mismatch')
    market=json.loads((directory/'market.json').read_text(encoding='utf-8'))
    if market.get('schema_version')!=1 or market.get('price_basis')!='RAW':
        raise ValueError('Unsupported raw market schema')
    if not stamp(market['captured_at'])<=stamp(signed['reviewed_at'])<=stamp(now):
        raise ValueError('Review/capture availability mismatch')
    source_hashes={sha for name,sha in files.items() if name.startswith('sources/')}
    definitions(market,source_hashes)
    if market.get('price_source_sha256') not in source_hashes:
        raise ValueError('Missing bound raw price source')
    for action in market['actions']:
        if action.get('evidence_sha256') not in source_hashes:
            raise ValueError('Missing bound action announcement')
        canonical=stamp(action['effective_at']).astimezone(timezone.utc).isoformat()
        if action['effective_at']!=canonical:
            raise ValueError('Corporate action time must be canonical UTC')
        # No arbitrary event identifiers for an economic cash dividend.
        if action['kind']=='EX_DIVIDEND':
            expected='DIV:'+action['security_id']+':'+action['effective_at']
            if action.get('dividend_id')!=expected:
                raise ValueError('Noncanonical dividend identity')
            if not stamp(action['announced_at'])<=stamp(market['captured_at']):
                raise ValueError('Announcement unavailable')
        if action['kind']=='SPLIT' and action.get('event_key')!='SPLIT:'+action['security_id']+':'+action['effective_at']:
            raise ValueError('Noncanonical split identity')
    return market, {'review':review,'bundle_sha256':hashlib.sha256(encoded(signed).encode()).hexdigest()}


def archive_bundle(directory,evidence,store):
    """Retain exact approved bytes. Artifacts may precede a failed batch, never fills."""
    base=Path(store)/'evidence'/evidence['bundle_sha256']
    base.mkdir(parents=True,exist_ok=True)
    files=evidence['review']['payload']['files']
    for name,expected in files.items():
        data=(Path(directory)/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Evidence changed during archive')
        target=base/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if target.read_bytes()!=data:raise ValueError('Immutable evidence conflict')
        else:
            try:
                with target.open('xb') as handle:handle.write(data)
            except FileExistsError:
                if target.read_bytes()!=data:raise ValueError('Concurrent evidence conflict')
    review=base/'review.json';content=encoded(evidence['review']).encode()
    if review.exists():
        if review.read_bytes()!=content:raise ValueError('Immutable review conflict')
    else:
        try:
            with review.open('xb') as handle:handle.write(content)
        except FileExistsError:
            if review.read_bytes()!=content:raise ValueError('Concurrent review conflict')
