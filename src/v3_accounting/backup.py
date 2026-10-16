"""V3-only authenticated snapshots. No scheduler, orders, or V12 writes.

Restore requires a separately retained archive SHA256 receipt: a valid old
signature alone cannot prove freshness. Cloud access is explicit, never automatic.
"""
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
import hashlib
import hmac
import json
import os
import sqlite3
import zipfile
from urllib.parse import urlparse

from src.v3_accounting.accounting import ROOT, Journal, encoded
from src.v3_accounting.runner import Runner
from src.v3_accounting.evidence import read_bundle, signature

BASE = ROOT / 'shadow_forward/V3_ACCOUNTING'
BUCKET = 'v3-accounting'
MAX_BYTES = 40 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def isolated(path):
    path = Path(path).resolve()
    if path == BASE.resolve() or not path.is_relative_to(BASE.resolve()):
        raise ValueError('Dedicated V3 child directory required')
    return path


def allowed_file(name):
    return name in {'freeze.json', 'integration_freeze.json', 'corporate_actions.sqlite3'} or name.startswith(('signals/', 'evidence/'))


def validate_store(store, review_key, now):
    """Check pinned code, SQLite health, hash chain and bound source evidence."""
    required = ['freeze.json', 'integration_freeze.json', 'corporate_actions.sqlite3']
    if not all((store / name).is_file() for name in required):
        raise ValueError('Initialized V3 integration required')
    with closing(sqlite3.connect((store / 'corporate_actions.sqlite3').as_uri() + '?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity failure')
        triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if not {'no_update', 'no_delete'}.issubset(triggers):
            raise ValueError('Append-only triggers missing')
        # Check before Journal construction, which creates missing triggers.
    journal = Runner(store).checked()
    with closing(journal.connect()) as conn:
        rows = journal.rows(conn)
    if not rows or rows[0][1] != 'INITIALIZE':
        raise ValueError('Initialization missing')
    for row in rows[1:]:
        request = json.loads(row[2])
        evidence = request.get('evidence')
        if evidence is None:
            raise ValueError('Only integrated V3 batches supported')
        market, saved = read_bundle(store / 'evidence' / evidence['bundle_sha256'], review_key, now)
        if saved != evidence or market != request['market']:
            raise ValueError('Ledger/source evidence mismatch')
    return {'events': len(rows), 'head': rows[-1][5]}


def make_snapshot(store, backup_key, review_key, now=None):
    store = isolated(store)
    now = now or datetime.now(timezone.utc).isoformat()
    # Validate key even for an initialization-only snapshot.
    signature({}, backup_key)
    if backup_key == review_key:
        raise ValueError('Backup and review keys must be independent')
    if not (store / 'corporate_actions.sqlite3').is_file():
        raise ValueError('Initialized V3 integration required')
    database_path = store / 'corporate_actions.sqlite3'
    with closing(sqlite3.connect(database_path, timeout=30)) as lock, TemporaryDirectory(dir=BASE) as temp:
        # Hold writer exclusion while capturing DB and immutable source files.
        lock.execute('BEGIN IMMEDIATE')
        try:
            info = validate_store(store, review_key, now)
            database = Path(temp) / 'snapshot.sqlite3'
            with closing(sqlite3.connect(database_path)) as src, closing(sqlite3.connect(database)) as dst:
                src.backup(dst)
            files = {}
            for path in sorted(store.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symlinks prohibited')
                if not path.is_file():
                    continue
                name = path.relative_to(store).as_posix()
                if name in {'corporate_actions.sqlite3-wal', 'corporate_actions.sqlite3-shm',
                            'corporate_actions.sqlite3-journal'}:
                    continue
                # No env, keys, temporary outputs or unrelated files in backups.
                if not allowed_file(name):
                    raise ValueError('Unexpected store file')
                files[name] = database.read_bytes() if name == 'corporate_actions.sqlite3' else path.read_bytes()
            if sum(map(len, files.values())) > MAX_BYTES:
                raise ValueError('Snapshot exceeds size limit')
            payload = {'schema': 1, 'scope': 'V3_ACCOUNTING_ONLY', 'created_at': now,
                       **info, 'files': {n: sha(b) for n, b in files.items()}}
            manifest = {'payload': payload, 'signature': signature(payload, backup_key)}
            result = BytesIO()
            with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, data in files.items():
                    archive.writestr(name, data)
                archive.writestr('manifest.json', encoded(manifest))
            data = result.getvalue()
            return data, {'archive_sha256': sha(data), **info,
                          'object': 'snapshots/' + sha(data) + '.zip'}
        finally:
            lock.rollback()


def restore_snapshot(data, destination, backup_key, review_key, expected_sha256, now=None):
    destination = isolated(destination)
    if destination.exists():
        raise ValueError('Restore cannot overwrite an existing directory')
    if backup_key == review_key:
        raise ValueError('Backup and review keys must be independent')
    if len(data) > MAX_BYTES or not expected_sha256 or sha(data) != expected_sha256:
        raise ValueError('Archive receipt/hash mismatch')
    now = now or datetime.now(timezone.utc).isoformat()
    BASE.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=BASE) as temp:
        stage = Path(temp) / 'store'
        stage.mkdir()
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(names) != len(set(names)) or sum(i.file_size for i in entries) > MAX_BYTES:
                raise ValueError('Duplicate or oversized archive')
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or name != path.as_posix():
                    raise ValueError('Unsafe archive path')
            manifest = json.loads(archive.read('manifest.json'))
            payload = manifest['payload']
            if not hmac.compare_digest(signature(payload, backup_key), manifest['signature']):
                raise ValueError('Backup signature mismatch')
            if payload['schema'] != 1 or payload['scope'] != 'V3_ACCOUNTING_ONLY':
                raise ValueError('Invalid backup scope')
            if set(names) != set(payload['files']) | {'manifest.json'}:
                raise ValueError('Backup file inventory mismatch')
            for name, digest in payload['files'].items():
                if not allowed_file(name):
                    raise ValueError('Unexpected store file')
                content = archive.read(name)
                if sha(content) != digest:
                    raise ValueError('Backup file hash mismatch')
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        info = validate_store(stage, review_key, now)
        if info != {k: payload[k] for k in ['events', 'head']}:
            raise ValueError('Backup head mismatch')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Never use replace(): existing V3 stores must remain untouched.
        os.rename(stage, destination)
        return info


class PrivateStorage:
    """Explicit private Supabase transport; immutable content-addressed objects."""
    def __init__(self, url, secret, session=None):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co') or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or parsed.username or parsed.port:
            raise ValueError('HTTPS Supabase project root required')
        if not secret:
            raise ValueError('Server-side Supabase secret required')
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.url = url.rstrip('/') + '/storage/v1/object/' + BUCKET + '/snapshots/'
        self.headers = {'apikey': secret, 'Authorization': 'Bearer ' + secret}

    def download(self, digest):
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid archive hash')
        response = self.session.get(self.url + digest + '.zip', headers=self.headers, timeout=30, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError('Private download failed (HTTP %s)' % response.status_code)
        data = response.content
        if len(data) > MAX_BYTES or sha(data) != digest:
            raise ValueError('Cloud content hash mismatch')
        return data

    def upload(self, data):
        if len(data) > MAX_BYTES:
            raise ValueError('Snapshot exceeds size limit')
        digest = sha(data)
        response = self.session.post(self.url + digest + '.zip', data=data,
            headers={**self.headers, 'Content-Type': 'application/zip', 'x-upsert': 'false'},
            timeout=30, allow_redirects=False)
        # Only an existing identical content-addressed object may be reused.
        if response.status_code not in {200, 201, 409}:
            raise ValueError('Private upload failed (HTTP %s)' % response.status_code)
        if self.download(digest) != data:
            raise ValueError('Cloud readback mismatch')
        return {'archive_sha256': digest, 'bucket': BUCKET, 'readback_verified': True}


def publish_snapshot(store, storage, backup_key, review_key, now=None):
    data, receipt = make_snapshot(store, backup_key, review_key, now)
    return {**receipt, **storage.upload(data), 'scheduler_enabled': False}


def restore_private(storage, receipt, destination, backup_key, review_key, now=None):
    # Caller retains this receipt outside the bucket. No mutable 'latest' lookup.
    digest = receipt['archive_sha256']
    data = storage.download(digest)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        payload = json.loads(archive.read('manifest.json'))['payload']
    if {k: payload[k] for k in ['events', 'head']} != {k: receipt[k] for k in ['events', 'head']}:
        raise ValueError('External receipt head mismatch')
    info = restore_snapshot(data, destination, backup_key, review_key, digest, now)
    return info
