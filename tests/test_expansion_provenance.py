"""Checkpoint dependencies, final metrics, and atomic manifest publication."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tools'))
SPEC = importlib.util.spec_from_file_location('nudegate_expansion_build',REPO/'tools/build_expansion.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class ExpansionProvenanceTests(unittest.TestCase):
    def test_dependency_bytes_are_bound_and_lod_morph_builders_are_listed(self):
        names = {path.name for path in BUILD.PIPELINE_DEPENDENCIES}
        self.assertTrue({'build_bodies.py','lod_authoring.py','morphs.py'}.issubset(names))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first,second = root/'builder.py',root/'lod.py'
            first.write_text('first');second.write_text('second')
            with patch.object(BUILD,'ROOT',root),patch.object(BUILD,'PIPELINE_DEPENDENCIES',(first,second)):
                before,_ = BUILD.pipeline_fingerprint()
                second.write_text('changed validator')
                after,_ = BUILD.pipeline_fingerprint()
            self.assertNotEqual(before,after)

    def test_family_frame_converter_and_collection_invalidate_checkpoint(self):
        family = {'id':'human_fs','frame':[1.2,1.1,1.15]}
        args = [{'id':'curvy'},50,'source','pipeline',family,'collection',{'topology':'known'},'tool']
        baseline = BUILD.checkpoint_fingerprint(*args)
        for index,value in ((4,{'id':'human_fs','frame':[1.25,1.1,1.15]}),(5,'another-collection'),(7,'changed-converter')):
            changed = copy.deepcopy(args)
            changed[index] = value
            self.assertNotEqual(BUILD.checkpoint_fingerprint(*changed),baseline)

    def test_converter_library_bytes_invalidate_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable,library = root/'Divine.exe',root/'LSLib.dll'
            executable.write_bytes(b'converter');library.write_bytes(b'version1')
            before = BUILD.tool_fingerprint(executable)
            library.write_bytes(b'version2')
            self.assertNotEqual(before,BUILD.tool_fingerprint(executable))

    def test_invalid_atomic_manifest_preserves_prior_complete_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'body-build.json'
            BUILD.atomic_json(path,{'build_status':'complete'})
            before = path.read_bytes()
            with self.assertRaises(ValueError): BUILD.atomic_json(path,{'value':float('nan')})
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(json.loads(path.read_text())['build_status'],'complete')

    def test_top_metrics_describe_final_overlay_positions(self):
        source = [[0,0,0],[1,0,0],[0,1,0]]
        final = [[0,0,0],[1,0,0],[0,1,.4]]
        mesh = SimpleNamespace(positions=source,triangles=[(0,1,2)],topology_id='fixture')
        key = (BUILD.geometry_fingerprint(source,mesh.triangles),'fixture',(1,1,1),'fixture')
        masks = {'positions':source,'locked_vertices':[]}
        base_report = {'max_displacement_metres':.1}
        proof = BUILD.SurfaceIntersectionChecker(source,mesh.triangles,topology_id='fixture').validate(final)
        profile_hash = hashlib.sha256(b'{}').hexdigest()
        with patch.dict(BUILD.SOURCE_MASKS,{key:(masks,masks)},clear=True), \
             patch.dict(BUILD.BASE_SCULPTS,{(key,'{}'):(copy.deepcopy(source),base_report)},clear=True), \
             patch.dict(BUILD.WALL_CALIBRATIONS,{('fixture',profile_hash):{}},clear=True), \
             patch.object(BUILD,'apply_breast_size',return_value={'positions':final,'report':{'quality':proof}}):
            _,report = BUILD.sculpt(mesh,{},50,None,family_id='fixture')
        self.assertEqual(report['max_displacement_metres'],.4)
        self.assertEqual(report['moved_vertices'],1)
        self.assertEqual(base_report['max_displacement_metres'],.1)


if __name__=='__main__': unittest.main()
