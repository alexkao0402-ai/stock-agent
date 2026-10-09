"""Signal algorithm parity and source-tree isolation, without runtime writes."""
import ast
import hashlib
from pathlib import Path
import unittest
from uuid import uuid4

from src.v3_accounting import signal, accounting
from src.v3_accounting.runner import Runner, dependencies, STORE


class PackagingTests(unittest.TestCase):
    def test_signal_functions_equal_frozen_v2_ast(self):
        # Original mirror functions, with ONLY the calendar pathname normalized.
        tree=ast.parse(Path(signal.__file__).read_text(encoding='utf-8'))
        functions=[ast.dump(n,include_attributes=False) for n in tree.body
                   if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
        self.assertEqual(len(functions),11)
        self.assertEqual(hashlib.sha256('\n'.join(functions).encode()).hexdigest(),
                         'ee9a98396081ffa911bae9d0591351579a74d0664014f377f6054cb9c200c33b')
        rule=next(n for n in tree.body if isinstance(n,ast.Assign)
                  and any(isinstance(t,ast.Name) and t.id=='RULES' for t in n.targets))
        self.assertEqual(hashlib.sha256(ast.dump(rule,include_attributes=False).encode()).hexdigest(),
                         '665fc8f89b9d34ccf795ad9a4acfcfcf495d248cd604b339e31fe551c634b1f2')

    def test_repo_root_and_no_mirror_dependency(self):
        root=Path(__file__).resolve().parents[2]
        self.assertEqual(accounting.ROOT,root)
        self.assertEqual(signal.ROOT,root)
        self.assertEqual(signal.STORE,STORE)
        for name in dependencies():
            self.assertTrue((root/name).is_file())
            self.assertNotIn('stock-agent-work',name)
        # Source transport adaptation must not fall back to parent mirror modules.
        self.assertTrue(Path(signal.__file__).resolve().is_relative_to(root/'src/v3_accounting'))

    def test_status_does_not_initialize_and_rejects_production_locations(self):
        isolated=accounting.ROOT/'shadow_forward/V3_ACCOUNTING'/('status-test-'+uuid4().hex)
        result=Runner(isolated).status()
        self.assertEqual(result['status'],'NOT_INITIALIZED')
        self.assertFalse(isolated.exists())
        for path in [accounting.ROOT/'paper_ledger',accounting.ROOT/'src',
                     accounting.ROOT/'shadow_forward/V11_TOP3_95_IPO_V2']:
            with self.assertRaises(ValueError): Runner(path)


if __name__=='__main__': unittest.main()
