"""Read-only V3 cloud view; never acquires a writer lease or processes events."""
from datetime import datetime, timezone
from io import BytesIO
import json
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from src.v3_accounting.backup import BASE, PrivateStorage, restore_snapshot
from src.v3_accounting.runner import Runner


class V3DashboardError(ValueError):
    pass


def read_head(storage):
    response = storage.session.post(
        storage.url.split('/storage/v1/')[0] + '/rest/v1/rpc/v3_read_head',
        headers=storage.headers, json={}, timeout=30, allow_redirects=False)
    if response.status_code != 200:
        raise V3DashboardError('V3 read-only cloud endpoint is unavailable')
    row = response.json()
    if isinstance(row, list) and len(row) == 1:
        row = row[0]
    if not isinstance(row, dict) or row.get('stream') != 'V3_ACCOUNTING':
        raise V3DashboardError('Invalid V3 cloud head')
    revision = row.get('revision')
    if type(revision) is not int or revision < 1:
        raise V3DashboardError('No published V3 state')
    for field in ('archive_sha256', 'ledger_head_sha256'):
        digest = row.get(field)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise V3DashboardError('Invalid V3 cloud receipt')
    return row


def load_v3_dashboard(url, secret, backup_key, review_key, *, session=None):
    if not all((url, secret, backup_key, review_key)):
        raise V3DashboardError('Configure SUPABASE_URL, SUPABASE_SECRET_KEY, V3_BACKUP_HMAC_KEY and V3_REVIEW_HMAC_KEY on the server')
    if min(len(backup_key), len(review_key)) < 32 or backup_key == review_key:
        raise V3DashboardError('Independent V3 signing keys of at least 32 characters are required')
    try:
        storage = PrivateStorage(url, secret, session=session)
        head = read_head(storage)
        data = storage.download(head['archive_sha256'])
        BASE.mkdir(parents=True, exist_ok=True)
        # Disposable verification copy only; never restore over a trading store.
        with TemporaryDirectory(prefix='ui-read-', dir=BASE) as directory:
            from pathlib import Path
            destination = Path(directory) / 'verified'
            info = restore_snapshot(data, destination, backup_key, review_key, head['archive_sha256'])
            if info['head'] != head['ledger_head_sha256']:
                raise V3DashboardError('Published V3 ledger does not match the signed archive')
            inspected = Runner(destination).checked().inspect()
        # Recheck authority without a lease: reject a publication race.
        if read_head(storage) != head:
            raise V3DashboardError('V3 publication changed during verification; refresh to retry')
        with ZipFile(BytesIO(data)) as archive:
            created_at = json.loads(archive.read('manifest.json'))['payload']['created_at']
        return {'state': inspected['state'], 'events': inspected['events'],
                'revision': head['revision'], 'snapshot_created_at': created_at,
                'verified_at': datetime.now(timezone.utc).isoformat()}
    except V3DashboardError:
        raise
    except Exception:
        # Never expose response bodies, authentication headers or raw key errors.
        raise V3DashboardError('V3 verification failed; no unverified or V12 fallback data is displayed') from None


def render_v3_dashboard():
    import streamlit as st
    import pandas as pd
    from src.config import get_secret
    from src.dashboard_ui import header, money, paper_banner

    header('ISOLATED V3', 'V3 Accounting', 'Independent challenger · not the official Frozen V12 portfolio')
    paper_banner()
    st.caption('Read-only cloud view. This page cannot generate signals, place orders, or change the ledger.')
    try:
        view = load_v3_dashboard(get_secret('SUPABASE_URL'),
            get_secret('SUPABASE_SECRET_KEY') or get_secret('SUPABASE_SERVICE_ROLE_KEY'),
            get_secret('V3_BACKUP_HMAC_KEY'), get_secret('V3_REVIEW_HMAC_KEY'))
    except V3DashboardError as exc:
        st.error(str(exc))
        return
    state = view['state']
    st.caption(f"Snapshot created: {view['snapshot_created_at']} · Verified now: {view['verified_at']} · Cloud revision: {view['revision']}")
    st.caption(f"Last accounting boundary: {state.get('last_boundary') or 'Not started'} · {view['events']} verified ledger events")
    if view['events'] == 1 and not state['processed']:
        st.info('Initialized only: no V3 Forward trades or performance yet. Scheduler has not been enabled.')
    cols = st.columns(3)
    cols[0].metric('Cash', money(state['cash']))
    cols[1].metric('Dividends received', money(state['dividends_paid']))
    pending = sum(item['amount'] for item in state['receivables'].values() if not item['paid'])
    cols[2].metric('Dividends receivable', money(pending))
    st.subheader('Holdings')
    rows = [{'Security ID': name, 'Shares': item['shares'], 'Average cost': item['average_cost']}
            for name, item in state['positions'].items() if item['shares'] > 0]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    else:
        st.write('No V3 holdings. Initial cash is not investment performance.')
    st.subheader('Dividend entitlements')
    rows = [{'Dividend ID': name, **item} for name, item in state['receivables'].items()]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    else:
        st.write('No recorded V3 dividend entitlements.')
    st.caption('Only reviewed dividend entitlements are shown. Older dividends are not credited to this newly initialized account. No broker connection is implied.')
