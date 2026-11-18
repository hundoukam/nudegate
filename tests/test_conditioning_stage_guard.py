import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT=Path(__file__).resolve().parents[1]


class ConditioningStageGuardTests(unittest.TestCase):
    def test_both_schemas_refuse_chained_stages_before_loading_or_writing_geometry(self):
        # Even a second configuration that correctly fingerprints the current
        # stage cannot reset an earlier 150 nm adjustment to a new 200 nm budget.
        for schema in (1,2):
            for evidence in ('report','sidecar'):
                with self.subTest(schema=schema,evidence=evidence),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);source=root/'conditioned';source.mkdir();output=root/'second-pass'
                    names=['body_prepared.npz','neck_geometry.npz','body_payload.json','posed_dense.npz','report.json']
                    if schema==1:names.append('global-pose-surface-audit.json')
                    for name in names:(source/name).write_bytes(b'original geometry marker')
                    report={'post_neck_numeric_conditioning':{'displacement_m':1.5e-7}} if evidence=='report' else {}
                    (source/'report.json').write_text(json.dumps(report))
                    if evidence=='sidecar':(source/'numeric-conditioning-config.json').write_text('{}')
                    before={p.name:p.read_bytes() for p in source.iterdir()}
                    config={'schema_version':schema,'source_stage':str(source),
                        'no_predicate_or_pair_exceptions':True,'requires_fresh_global_audits_and_actual_reexport':True,
                        'expected_source_file_sha256':{name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in names}}
                    config_path=root/'case.json';config_path.write_text(json.dumps(config))
                    result=subprocess.run([sys.executable,str(ROOT/'tools/condition_donor_float32.py'),
                        '--config',str(config_path),'--output',str(output)],capture_output=True,text=True)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('Already-conditioned source stage',result.stderr)
                    self.assertFalse(output.exists())
                    self.assertEqual(before,{p.name:p.read_bytes() for p in source.iterdir()})


if __name__=='__main__':unittest.main()
