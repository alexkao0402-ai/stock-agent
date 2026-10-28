from datetime import datetime
from io import BytesIO
from pathlib import Path
import unittest
import zipfile
from types import SimpleNamespace

from src.v3_accounting.backup import make_snapshot, restore_snapshot, PrivateStorage, sha
from src.v3_accounting.accounting import Journal, ROOT
from tests.v3 import test_runner as fixtures
KEY = fixtures.KEY

BACKUP_KEY = 'SYNTHETIC-BACKUP-KEY-NOT-REAL-1234567890'
NOW = '2026-11-05T22:00:00+00:00'


class BackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.IntegrationTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.IntegrationTests.tearDownClass()

    def setUp(self):
        self.fixture = fixtures.IntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.first_close()
        self.store = self.fixture.store
        self.destination = Path(self.fixture.temp.name) / 'restored'

    def snapshot(self):
        return make_snapshot(self.store, BACKUP_KEY, KEY, NOW)

    def restore(self, data, receipt, **kwargs):
        return restore_snapshot(data, self.destination, kwargs.get('key', BACKUP_KEY), KEY,
                                kwargs.get('expected', receipt['archive_sha256']), NOW)

    def test_roundtrip_state_sources_and_retry(self):
        before = Journal(self.store).inspect()
        data, receipt = self.snapshot()
        info = self.restore(data, receipt)
        self.assertEqual(info['events'], 3)
        self.assertEqual(Journal(self.destination).inspect(), before)
        self.assertEqual(Journal(self.store).inspect(), before)
        for path in (self.store / 'evidence').rglob('*'):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (self.destination / path.relative_to(self.store)).read_bytes())
        opening, _ = self.fixture.market()
        from src.v3_accounting.runner import Runner
        result = Runner(self.destination).process(opening, KEY, signal_bundle=self.fixture.bundle,
                                                  now=datetime.fromisoformat(NOW))
        self.assertFalse(result['created'])
        self.assertEqual(Journal(self.destination).inspect()['events'], 3)

    def test_wrong_key_fails_without_destination(self):
        data, receipt = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.restore(data, receipt, key='wrong-key-' * 5)
        self.assertFalse(self.destination.exists())

    def test_receipt_required_and_wrong_hash(self):
        data, receipt = self.snapshot()
        for expected in ['', '0' * 64]:
            with self.assertRaisesRegex(ValueError, 'receipt'):
                self.restore(data, receipt, expected=expected)
        self.assertFalse(self.destination.exists())

    def test_existing_destination_never_overwritten(self):
        data, receipt = self.snapshot()
        self.destination.mkdir()
        (self.destination / 'keep.txt').write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            self.restore(data, receipt)
        self.assertEqual((self.destination / 'keep.txt').read_text(), 'preserve')

    def test_non_v3_destination_rejected(self):
        data, receipt = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'V3'):
            restore_snapshot(data, ROOT / 'shadow_forward/V12', BACKUP_KEY, KEY, receipt['archive_sha256'], NOW)

    def test_missing_source_rejected_at_backup(self):
        path = next((self.store / 'evidence').glob('*/sources/price.txt'))
        path.write_text('corrupt synthetic source')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.snapshot()

    def test_archive_tamper_and_traversal(self):
        data, receipt = self.snapshot()
        for name in ['freeze.json', '../escape.txt']:
            result = BytesIO()
            with zipfile.ZipFile(BytesIO(data)) as original, zipfile.ZipFile(result, 'w') as changed:
                for item in original.infolist():
                    changed.writestr(item.filename, b'corrupt' if item.filename == name else original.read(item))
                if name.startswith('..'):
                    changed.writestr(name, b'bad')
            altered = result.getvalue()
            with self.assertRaises(ValueError):
                self.restore(altered, receipt, expected=sha(altered))
            self.assertFalse(self.destination.exists())

    def test_secrets_are_not_allowed_in_store(self):
        (self.store / '.env').write_text('SYNTHETIC TEST SECRET')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            self.snapshot()

    def test_missing_trigger_rejected_without_repair(self):
        from contextlib import closing
        with closing(Journal(self.store).connect()) as conn, conn:
            conn.execute('DROP TRIGGER no_delete')
        with self.assertRaisesRegex(ValueError, 'triggers'):
            self.snapshot()

    def test_review_and_backup_keys_must_be_separate(self):
        with self.assertRaisesRegex(ValueError, 'independent'):
            make_snapshot(self.store, KEY, KEY, NOW)


class TransportTests(unittest.TestCase):
    def test_fixed_private_bucket_no_overwrite_and_readback(self):
        class Session:
            def post(self, url, data, **kwargs):
                self.data = data
                self.url = url
                self.kwargs = kwargs
                return SimpleNamespace(status_code=201)
            def get(self, url, **kwargs):
                return SimpleNamespace(status_code=200, content=self.data)
        session = Session()
        storage = PrivateStorage('https://synthetic.supabase.co', 'SYNTHETIC', session)
        receipt = storage.upload(b'SYNTHETIC ARCHIVE ONLY')
        self.assertTrue(receipt['readback_verified'])
        self.assertIn('/v3-accounting/snapshots/', session.url)
        self.assertEqual(session.kwargs['headers']['x-upsert'], 'false')
        self.assertFalse(session.kwargs['allow_redirects'])

    def test_cloud_corruption_and_error_do_not_leak_secret(self):
        class Session:
            def post(self, *args, **kwargs):
                return SimpleNamespace(status_code=201)
            def get(self, *args, **kwargs):
                return SimpleNamespace(status_code=200, content=b'wrong')
        with self.assertRaisesRegex(ValueError, 'hash'):
            PrivateStorage('https://synthetic.supabase.co', 'SECRET', Session()).upload(b'original')
        with self.assertRaises(ValueError):
            PrivateStorage('http://synthetic.supabase.co', 'SECRET')


if __name__ == '__main__':
    unittest.main()
