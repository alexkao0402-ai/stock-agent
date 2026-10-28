"""Isolated best-effort display cache; no strategy or ledger state."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


class ResearchCache:
    def __init__(self, root=None, now=None):
        self.root = Path(root or 'cache/market_research_v1')
        self.now = now or time.time
        self.metadata = []

    def get(self, section, key, loader, ttl=900):
        path = self.root / (hashlib.sha256(f'{section}:{key}'.encode()).hexdigest() + '.json')
        now = self.now()
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        stamp = saved.get('saved_at', 0)
        age = now - stamp if isinstance(stamp, (int, float)) else float('inf')
        valid = 0 <= age <= 7 * 86400 and bool(saved.get('data'))
        def record(status):
            self.metadata.append({'Data': section, 'Status': status,
                                  'Retrieved at (UTC)': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(stamp)) if valid else ''})
        if valid and age < ttl:
            record('Cached')
            return saved['data']
        retry = saved.get('retry_after', 0)
        if isinstance(retry, (int, float)) and now < retry <= now + 300:
            if valid:
                record('Stale backup (refresh failed)')
                return saved['data']
            raise RuntimeError('Provider temporarily unavailable (retry cooldown)')
        try:
            data = loader()
            if not data:
                raise ValueError('No data returned')
        except Exception:
            saved['retry_after'] = now + 120
            self._save(path, saved)
            if valid:
                record('Stale backup (refresh failed)')
                return saved['data']
            raise
        self._save(path, {'saved_at': now, 'data': data})
        stamp, valid = now, True
        record('Fresh')
        return data

    def _save(self, path, value):
        temp = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.root, delete=False) as handle:
                temp = handle.name
                json.dump(value, handle, allow_nan=False)
            os.replace(temp, path)
        except (OSError, ValueError, TypeError):
            pass  # Read-only filesystems must not break the research view.
        finally:
            if temp:
                try:
                    os.unlink(temp)
                except OSError:
                    pass
