from pathlib import Path
from types import SimpleNamespace
import unittest

from src.v3_accounting.cloud_cycle import LeaseRPC, run_cloud_cycle
from src.v3_accounting.backup import make_snapshot, sha
from src.v3_accounting.accounting import Journal
from tests.v3 import test_runner as fixtures
from tests.v3.test_backup import BACKUP_KEY, NOW

OWNER='00000000-0000-4000-8000-000000000001'


def head(**extra):
    return {'stream':'V3_ACCOUNTING','owner':OWNER,'fence':1,'revision':2,
            'expires_at':'2026-11-05T22:05:00Z',
            'archive_sha256':'a'*64,'ledger_head_sha256':'b'*64,**extra}


class RPCtests(unittest.TestCase):
    def rpc(self, row=None, status=200, error=False):
        def post(*args,**kwargs):
            self.kwargs=kwargs
            if error: raise RuntimeError('PRIVATE-SECRET')
            return SimpleNamespace(status_code=status,json=lambda: row or head())
        return LeaseRPC('https://example.supabase.co','PRIVATE-SECRET',SimpleNamespace(post=post))

    def test_acquire_and_no_redirect(self):
        self.assertEqual(self.rpc().acquire(OWNER),head())
        self.assertFalse(self.kwargs['allow_redirects'])

    def test_invalid_owner_ttl_url(self):
        for owner,ttl in (('invalid',300),(OWNER,0),(OWNER,301),(OWNER,True)):
            with self.assertRaises(ValueError): self.rpc().acquire(owner,ttl)
        with self.assertRaises(ValueError): LeaseRPC('http://example.supabase.co','x')

    def test_error_redaction_and_denial(self):
        for rpc in (self.rpc(error=True),self.rpc(status=403)):
            with self.assertRaises(ValueError) as e: rpc.acquire(OWNER)
            self.assertNotIn('PRIVATE-SECRET',str(e.exception))

    def test_changed_head_on_renew_rejected(self):
        with self.assertRaisesRegex(ValueError,'changed'):
            self.rpc(head(revision=3)).renew(head())

    def test_publish_exact_receipt(self):
        row=head(revision=3,archive_sha256='c'*64,ledger_head_sha256='d'*64)
        self.assertEqual(self.rpc(row).publish(head(),'c'*64,'d'*64),row)
        with self.assertRaisesRegex(ValueError,'receipt'):
            self.rpc().publish(head(),'c'*64,'d'*64)


class MemoryStorage:
    def __init__(self,data): self.objects={sha(data):data}; self.uploads=0
    def download(self,digest): return self.objects[digest]
    def upload(self,data):
        self.uploads+=1; self.objects[sha(data)]=data
        return {'readback_verified':True,'archive_sha256':sha(data)}


class FakeAuthority:
    """Protocol fake only, NOT evidence of PostgreSQL isolation/security."""
    def __init__(self,receipt):
        self.state=head(archive_sha256=receipt['archive_sha256'],ledger_head_sha256=receipt['head'])
        self.held=False; self.renewals=0; self.expire_on=None; self.published=0; self.lose_response=False
    def acquire(self,owner):
        if self.held: raise ValueError('Writer busy')
        self.held=True; self.state['owner']=owner
        return dict(self.state)
    def renew(self,lease):
        self.renewals+=1
        if self.renewals==self.expire_on: raise ValueError('Expired or fenced writer')
        return dict(self.state)
    def publish(self,lease,archive,ledger):
        if lease['revision']!=self.state['revision']: raise ValueError('Stale cloud revision')
        self.state.update(revision=lease['revision']+1,archive_sha256=archive,ledger_head_sha256=ledger)
        self.published+=1
        if self.lose_response: raise ValueError('Outcome may be unknown')
        return dict(self.state)


class CycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): fixtures.IntegrationTests.setUpClass()
    @classmethod
    def tearDownClass(cls): fixtures.IntegrationTests.tearDownClass()
    def setUp(self):
        self.f=fixtures.IntegrationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.first_close()
        data,receipt=make_snapshot(self.f.store,BACKUP_KEY,fixtures.KEY,NOW)
        self.storage=MemoryStorage(data); self.rpc=FakeAuthority(receipt)
        self.destination=Path(self.f.temp.name)/'cloud-work'
        self.calls=0
    def calculate(self,store):
        self.calls+=1
        self.assertEqual(Journal(store).inspect(),Journal(self.f.store).inspect())
        # No-op cycle: already-applied evidence must not produce new fills.
    def run_cycle(self):
        return run_cloud_cycle(self.rpc,self.storage,self.destination,BACKUP_KEY,
            fixtures.KEY,self.calculate,now=NOW,owner=OWNER)
    def test_restore_before_compute_and_publish(self):
        result=self.run_cycle()
        self.assertEqual(result['status'],'PUBLISHED'); self.assertEqual(result['events'],3)
        self.assertEqual(self.calls,1); self.assertEqual(self.rpc.published,1)
    def test_real_runner_batch_extends_restored_head(self):
        from src.v3_accounting.runner import Runner
        directory,_=self.f.market('CLOSE','2026-11-03','2026-11-02T21:00:00Z')
        def calculate(store):
            Runner(store).process(directory,fixtures.KEY,now=fixtures.dt(NOW))
        result=run_cloud_cycle(self.rpc,self.storage,self.destination,BACKUP_KEY,
            fixtures.KEY,calculate,now=NOW,owner=OWNER)
        self.assertEqual(result['events'],4)
        self.assertEqual(Journal(self.f.store).inspect()['events'],3)
        self.assertEqual(Journal(self.destination).inspect()['events'],4)
    def test_calculation_failure_never_uploads(self):
        def calculate(store): raise ValueError('Incomplete reviewed evidence')
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            run_cloud_cycle(self.rpc,self.storage,self.destination,BACKUP_KEY,
                fixtures.KEY,calculate,now=NOW,owner=OWNER)
        self.assertEqual(self.storage.uploads,0); self.assertEqual(self.rpc.published,0)
    def test_second_writer_blocked_before_compute(self):
        self.rpc.held=True
        with self.assertRaisesRegex(ValueError,'busy'): self.run_cycle()
        self.assertEqual(self.calls,0); self.assertFalse(self.destination.exists())
    def test_expiry_before_compute_or_after_upload_no_publish(self):
        self.rpc.expire_on=1
        with self.assertRaisesRegex(ValueError,'Expired'): self.run_cycle()
        self.assertEqual(self.calls,0); self.assertEqual(self.rpc.published,0)
    def test_after_upload_expiry_keeps_authority_unchanged(self):
        original=dict(self.rpc.state); self.rpc.expire_on=3
        with self.assertRaisesRegex(ValueError,'Expired'): self.run_cycle()
        self.assertEqual(self.storage.uploads,1); self.assertEqual(self.rpc.published,0)
        self.assertEqual(self.rpc.state,original)
    def test_missing_seed_never_initializes(self):
        self.rpc.state.update(archive_sha256=None,ledger_head_sha256=None)
        with self.assertRaisesRegex(ValueError,'bootstrap'): self.run_cycle()
        self.assertFalse(self.destination.exists())
    def test_authority_ledger_disagreement(self):
        self.rpc.state['ledger_head_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'disagree'): self.run_cycle()
        self.assertEqual(self.calls,0)
    def test_lost_publish_response_not_recalculated(self):
        self.rpc.lose_response=True
        with self.assertRaisesRegex(ValueError,'unknown'): self.run_cycle()
        self.assertEqual(self.calls,1); self.assertEqual(self.rpc.published,1)


if __name__=='__main__': unittest.main()
