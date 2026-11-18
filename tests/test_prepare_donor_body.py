"""Preparation must not overwrite an already reviewed output stage."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SPEC=importlib.util.spec_from_file_location('prepare_donor_body',
    Path(__file__).resolve().parents[1]/'tools/prepare_donor_body.py')
TOOL=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


class PreparationOutputTests(unittest.TestCase):
    def test_existing_stage_is_rejected_before_source_read_or_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'accepted-stage';output.mkdir()
            marker=output/'accepted-marker.txt';marker.write_bytes(b'accepted stage must stay exact\n')
            arguments=['prepare_donor_body.py','--output',str(output),
                '--donor',str(Path(temporary)/'does-not-exist.npz')]
            with mock.patch.object(sys,'argv',arguments), \
                    mock.patch.object(TOOL,'load_dae') as native, \
                    mock.patch.object(TOOL,'pose_donor') as pose:
                with self.assertRaisesRegex(ValueError,'fresh output directory'):
                    TOOL.main()
                native.assert_not_called();pose.assert_not_called()
            self.assertEqual(marker.read_bytes(),b'accepted stage must stay exact\n')
            self.assertEqual(list(output.iterdir()),[marker])

    def test_existing_stage_previews_still_dispatch_without_preparing(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            for option,function in [('--blender-preview','preview'),('--blender-preview-final','preview_final')]:
                with self.subTest(option=option), \
                        mock.patch.object(sys,'argv',['prepare_donor_body.py','--output',str(output),option]), \
                        mock.patch.object(TOOL,function) as preview, \
                        mock.patch.object(TOOL,'pose_donor') as pose:
                    TOOL.main()
                    preview.assert_called_once()
                    pose.assert_not_called()


if __name__=='__main__':unittest.main()
