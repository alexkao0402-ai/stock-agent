import unittest
from unittest.mock import Mock, patch

from src.v3_dashboard import V3DashboardError, read_head, load_v3_dashboard


class ReadOnlyViewTests(unittest.TestCase):
    def test_head_is_read_only_rpc(self):
        storage = Mock(url='https://project.supabase.co/storage/v1/object/v3-accounting/snapshots/')
        row = {'stream':'V3_ACCOUNTING','revision':1,'archive_sha256':'a'*64,'ledger_head_sha256':'b'*64}
        storage.session.post.return_value.status_code = 200
        storage.session.post.return_value.json.return_value = [row]
        self.assertEqual(read_head(storage), row)
        self.assertTrue(storage.session.post.call_args.args[0].endswith('/rpc/v3_read_head'))

    def test_unpublished_and_malformed_heads_rejected(self):
        for row in ({}, {'stream':'V3_ACCOUNTING','revision':0},
                    {'stream':'V3_ACCOUNTING','revision':True},
                    {'stream':'V3_ACCOUNTING','revision':1,'archive_sha256':'x'*64}):
            storage = Mock(url='https://project.supabase.co/storage/v1/object/')
            storage.session.post.return_value.status_code = 200
            storage.session.post.return_value.json.return_value = row
            with self.assertRaises(V3DashboardError): read_head(storage)

    def test_missing_secrets_do_not_connect(self):
        with patch('src.v3_dashboard.PrivateStorage') as transport:
            with self.assertRaises(V3DashboardError): load_v3_dashboard(None,None,None,None)
            transport.assert_not_called()

    def test_failure_does_not_expose_secrets(self):
        with patch('src.v3_dashboard.PrivateStorage', side_effect=ValueError('secret-value')):
            with self.assertRaises(V3DashboardError) as caught:
                load_v3_dashboard('url','secret-value','a'*32,'b'*32)
            self.assertNotIn('secret-value',str(caught.exception))

    def test_hash_failure_has_no_local_or_v12_fallback(self):
        with patch('src.v3_dashboard.PrivateStorage') as transport, patch('src.v3_dashboard.read_head') as head:
            head.return_value = {'archive_sha256':'a'*64}
            transport.return_value.download.side_effect = ValueError('bad hash')
            with patch('src.v3_dashboard.Runner') as runner:
                with self.assertRaises(V3DashboardError):
                    load_v3_dashboard('url','secret','a'*32,'b'*32)
                runner.assert_not_called()


if __name__ == '__main__': unittest.main()
