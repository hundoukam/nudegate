"""Normal styles must respect native channel packing and protected atlas areas."""
from pathlib import Path
import copy
import struct
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid5
import xml.etree.ElementTree as ET

try:
    import numpy as np
    from PIL import Image
except ImportError:
    np = None

from nudegate.skin_styles import (rasterize_abdomen_mask, soften_packed_normal,
                                  splice_changed_bc3_blocks, verify_agb_packing,
                                  _styled_material, _material_uuid, NAMESPACE)


def packed_normal(width=64, height=64):
    y, x = np.mgrid[:height, :width]
    nx = 0.25 + 0.08 * np.sin(x / 12)
    ny = 0.10 + 0.05 * np.cos(y / 10)
    nz = np.sqrt(1 - nx * nx - ny * ny)
    image = np.zeros((height, width, 4), dtype=np.uint8)
    for channel, value in ((3, nx), (1, ny), (2, nz)):
        image[:, :, channel] = np.rint((value + 1) * 127.5).astype(np.uint8)
    return image


def fake_bc3(width, height, fill):
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<II", header, 12, height, width)
    struct.pack_into("<I", header, 28, 4)
    header[84:88] = b"DXT5"
    levels = bytearray()
    for _ in range(4):
        levels.extend(bytes([fill]) * (((width + 3) // 4) * ((height + 3) // 4) * 16))
        width, height = max(1, width // 2), max(1, height // 2)
    return bytes(header + levels)


def material_fixture():
    return ET.fromstring('''<node id="Resource">
<attribute id="ID" type="FixedString" value="original-material"/>
<attribute id="Name" type="LSString" value="native-skin"/>
<children>
<node id="ScalarParameters"><attribute id="ParameterName" value="VeinAmount"/>
<attribute id="Enabled" type="bool" value="True"/><attribute id="Value" type="float" value="0.5"/>
<attribute id="BaseValue" type="float" value="1"/><attribute id="GroupName" value="Skin"/></node>
<node id="ScalarParameters"><attribute id="ParameterName" value="TMP_BODY_ROUGH"/>
<attribute id="Enabled" type="bool" value="False"/><attribute id="Value" type="float" value="0.56"/>
<attribute id="BaseValue" type="float" value="0.56"/><attribute id="ExportAsPreset" value="False"/></node>
<node id="ScalarParameters"><attribute id="ParameterName" value="DetailNormalTiling"/>
<attribute id="Enabled" type="bool" value="False"/><attribute id="Value" type="float" value="40"/></node>
<node id="VirtualTextureParameters"><attribute id="ParameterName" value="virtualtexture"/>
<attribute id="ID" type="FixedString" value="original-vt"/><attribute id="Enabled" type="bool" value="True"/></node>
<node id="VectorParameters"><attribute id="ParameterName" value="SkinColor"/><attribute id="Value" value=".2 .3 .4 1"/></node>
<node id="Texture2DParameters"><attribute id="ParameterName" value="CancelMSK"/><attribute id="ID" value="native-mask"/></node>
<node id="TattooParameters"><attribute id="ID" value="native-tattoo"/></node>
</children></node>''')


def scalar(node,name):
    return next(item for item in node.findall('./children/node[@id="ScalarParameters"]')
                if item.find('attribute[@id="ParameterName"]').get('value')==name)


class SkinMaterialPresentationTests(unittest.TestCase):
    def test_soft_changes_only_existing_enabled_value_and_resource_references(self):
        original=material_fixture();before=ET.tostring(original)
        result,changes=_styled_material(original,'soft','private-material','private-vt')
        self.assertEqual(ET.tostring(original),before)
        expected=copy.deepcopy(original)
        expected.find('attribute[@id="ID"]').set('value','private-material')
        expected.find('./children/node[@id="VirtualTextureParameters"]/attribute[@id="ID"]').set('value','private-vt')
        for name,value in [('VeinAmount','0.15'),('TMP_BODY_ROUGH','0.62')]:
            node=scalar(expected,name)
            node.find('attribute[@id="Enabled"]').set('value','True')
            node.find('attribute[@id="Value"]').set('value',value)
        self.assertEqual(ET.tostring(result),ET.tostring(expected))
        self.assertEqual(scalar(result,'VeinAmount').find('attribute[@id="BaseValue"]').get('value'),'1')
        self.assertEqual(scalar(result,'TMP_BODY_ROUGH').find('attribute[@id="BaseValue"]').get('value'),'0.56')
        self.assertEqual(changes['VeinAmount']['before']['Value'],'0.5')
        self.assertEqual(changes['TMP_BODY_ROUGH']['after'],{'Enabled':'True','Value':'0.62'})

    def test_defined_retains_every_native_scalar_and_other_parameter(self):
        original=material_fixture();before=ET.tostring(original)
        result,changes=_styled_material(original,'defined','private-material','private-vt')
        self.assertEqual(changes,{})
        self.assertEqual(ET.tostring(original),before)
        result.find('attribute[@id="ID"]').set('value','original-material')
        result.find('./children/node[@id="VirtualTextureParameters"]/attribute[@id="ID"]').set('value','original-vt')
        self.assertEqual(ET.tostring(result),before)

    def test_soft_rejects_missing_duplicate_or_invalid_supported_parameters(self):
        for mutation in ('missing','duplicate','wrong_type','invalid_value'):
            original=material_fixture();target=scalar(original,'TMP_BODY_ROUGH')
            if mutation=='missing':original.find('children').remove(target)
            if mutation=='duplicate':original.find('children').append(copy.deepcopy(target))
            if mutation=='wrong_type':target.find('attribute[@id="Enabled"]').set('type','int32')
            if mutation=='invalid_value':target.find('attribute[@id="Value"]').set('value','NaN')
            before=ET.tostring(original)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                _styled_material(original,'soft','private-material','private-vt')
            self.assertEqual(ET.tostring(original),before)

    def test_only_soft_material_uuid_binds_the_presentation_defaults(self):
        native_key='material:original:vt'
        self.assertEqual(_material_uuid('original','vt','defined'),str(uuid5(NAMESPACE,native_key)))
        soft=_material_uuid('original','vt','soft')
        self.assertNotEqual(soft,str(uuid5(NAMESPACE,native_key)))
        with patch('nudegate.skin_styles.SOFT_SCALARS',{'VeinAmount':'0.2','TMP_BODY_ROUGH':'0.62'}):
            self.assertNotEqual(_material_uuid('original','vt','soft'),soft)
            self.assertEqual(_material_uuid('original','vt','defined'),str(uuid5(NAMESPACE,native_key)))


@unittest.skipIf(np is None, "Optional skin authoring requires NumPy and Pillow")
class SkinStyleTests(unittest.TestCase):
    def test_agb_validation_rejects_rgb_assumptions(self):
        image = packed_normal()
        self.assertLess(verify_agb_packing(image)["p99_unit_error"], 0.01)
        image[:, :, 0] = image[:, :, 3]
        with self.assertRaisesRegex(ValueError, "unused R=0"):
            verify_agb_packing(image)

    def test_softening_changes_only_selected_normal_pixels_and_reduces_slopes(self):
        original = packed_normal()
        source = original.copy()
        mask = np.zeros((64, 64), dtype=np.float32)
        mask[16:48, 16:48] = 1
        result, report = soften_packed_normal(original, mask)
        self.assertTrue(np.array_equal(original, source))
        self.assertTrue(np.array_equal(result[mask == 0], source[mask == 0]))
        self.assertTrue(np.array_equal(result[:, :, 0], source[:, :, 0]))
        self.assertGreater(report["changed_pixels"], 0)
        self.assertLess(report["masked_xy_rms_after"], report["masked_xy_rms_before"] * 0.5)
        normals = result[:, :, [3, 1, 2]].astype(float) / 127.5 - 1
        self.assertLess(np.max(abs(np.linalg.norm(normals, axis=2) - 1)), 0.01)

    def test_high_frequency_ridges_are_guarded(self):
        image = packed_normal()
        image[31, 31] = [0, 128, 155, 250]
        image[31, 32] = [0, 128, 155, 5]
        result, _ = soften_packed_normal(image, np.ones((64, 64), dtype=np.float32))
        self.assertTrue(np.array_equal(result[31, 31:33], image[31, 31:33]))

    def test_bc3_splice_preserves_untouched_blocks_and_source_header(self):
        source, recompressed = fake_bc3(8, 8, 17), fake_bc3(8, 8, 99)
        mask = np.zeros((8, 8), dtype=bool)
        mask[1, 1] = True
        result, report = splice_changed_bc3_blocks(source, recompressed, mask)
        self.assertEqual(result[:128], source[:128])
        self.assertEqual(result[128:144], recompressed[128:144])
        self.assertEqual(result[144:192], source[144:192])
        self.assertEqual(report["mips"][0]["changed_blocks"], 1)
        self.assertEqual(len(result), len(source))
        identity, _ = splice_changed_bc3_blocks(source, recompressed, np.zeros((8, 8), dtype=bool))
        self.assertEqual(identity, source)

    def test_uv_projection_excludes_back_and_respects_frame_scaling(self):
        ns = "http://www.collada.org/2005/11/COLLADASchema"
        positions = [(-.12, 1.02, -.08), (.12, 1.02, -.08), (.12, 1.26, -.08), (-.12, 1.26, -.08),
                     (-.12, 1.02, .08), (.12, 1.02, .08), (.12, 1.26, .08), (-.12, 1.26, .08)]
        coords = [(0, 0), (.5, 0), (.5, 1), (0, 1), (.5, 0), (1, 0), (1, 1), (.5, 1)]
        faces = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "body.dae"
            masks = []
            for frame, tile in ((1, 0), (2, 0), (1, 1)):
                vertices = " ".join(str(component * frame) for point in positions for component in point)
                uv = " ".join(str(component + tile) for point in coords for component in point)
                indices = " ".join(f"{index} {index}" for triangle in faces for index in triangle)
                path.write_text(f'''<COLLADA xmlns="{ns}"><library_geometries><geometry id="body"><mesh>
<source id="positions"><float_array id="positions-array" count="24">{vertices}</float_array><technique_common><accessor source="#positions-array" count="8" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="uv"><float_array id="uv-array" count="16">{uv}</float_array><technique_common><accessor source="#uv-array" count="8" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices><triangles count="4"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><p>{indices}</p></triangles>
</mesh></geometry></library_geometries></COLLADA>''', encoding="utf-8")
                mask, _ = rasterize_abdomen_mask(path, "body", (64, 64), (frame, frame, frame))
                self.assertGreater(mask[:, :32].max(), 0.9)
                self.assertEqual(mask[:, 32:].max(), 0)
                masks.append(mask)
            self.assertTrue(np.array_equal(masks[0], masks[1]))
            self.assertTrue(np.array_equal(masks[0], masks[2]))


if __name__ == "__main__":
    unittest.main()
