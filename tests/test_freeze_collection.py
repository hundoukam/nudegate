"""Frozen manifest metadata is hash-bound without rewriting archive records."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('nudegate_freeze_tools',Path(__file__).resolve().parents[1]/'tools/freeze_collection.py')
FREEZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FREEZE)


class FreezeCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root/'archive'
        files = {}
        for name in ('source.dae','body.dae','body.GR2'):
            path = self.root/name
            path.write_bytes(('approved '+name).encode())
            files[name] = path
        digest = lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest = self.root/'input.json'
        self.manifest.write_text(json.dumps({'families':[{'id':'human','source':str(files['source.dae']),
            'source_sha256':digest(files['source.dae']),'variants':[{'id':'plush','dae':str(files['body.dae']),
            'gr2':str(files['body.GR2']),'dae_sha256':digest(files['body.dae']),'gr2_sha256':digest(files['body.GR2'])}]}]}))

    def freeze(self):
        with patch.object(FREEZE,'ROOT',self.root),patch.object(FREEZE.subprocess,'check_output',return_value='approved-commit\n'):
            return FREEZE.freeze(self.manifest,self.output)

    def test_freeze_binds_metadata_and_identical_rerun_rewrites_nothing(self):
        self.freeze()
        before = {path.relative_to(self.output).as_posix():(path.read_bytes(),path.stat().st_mtime_ns)
                  for path in self.output.rglob('*') if path.is_file()}
        self.freeze()
        after = {path.relative_to(self.output).as_posix():(path.read_bytes(),path.stat().st_mtime_ns)
                 for path in self.output.rglob('*') if path.is_file()}
        self.assertEqual(before,after)
        self.assertEqual(FREEZE.verify(self.output)['body_files'],1)
        path = self.output/'body-build.json'
        data = json.loads(path.read_text());data['approved_source_commit']='changed-metadata'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'manifest fingerprint changed'): FREEZE.verify(self.output)

    def test_legacy_archive_binding_only_adds_sidecar(self):
        self.freeze()
        (self.output/'manifest.sha256').unlink()
        before = {path.relative_to(self.output).as_posix():path.read_bytes() for path in self.output.rglob('*') if path.is_file()}
        expected = hashlib.sha256((self.output/'body-build.json').read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'write-once manifest.sha256'): FREEZE.verify(self.output)
        FREEZE.bind_manifest(self.output,expected)
        self.assertEqual(FREEZE.verify(self.output)['body_files'],1)
        for name,data in before.items(): self.assertEqual((self.output/name).read_bytes(),data)

    def test_binding_cannot_replace_an_existing_approval(self):
        self.freeze()
        path = self.output/'body-build.json'
        path.write_text(path.read_text()+' ')
        altered = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'replace an existing archive record'): FREEZE.bind_manifest(self.output,altered)


if __name__=='__main__': unittest.main()
