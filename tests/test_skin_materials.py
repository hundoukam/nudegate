"""Soft skin presentation must stay inside private, explicitly supported materials."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from uuid import UUID
import xml.etree.ElementTree as ET

from nudegate.skin_materials import create_soft_materials


MATERIAL = "11111111-1111-4111-8111-111111111111"
UNREQUESTED = "22222222-2222-4222-8222-222222222222"
VT = "33333333-3333-4333-8333-333333333333"


def node(identifier: str, **values: str) -> ET.Element:
    result = ET.Element("node", {"id": identifier})
    for key, value in values.items():
        kind = "bool" if key == "Enabled" else "float" if key in {"Value", "BaseValue"} else "FixedString"
        ET.SubElement(result, "attribute", {"id": key, "type": kind, "value": value})
    return result


def attrs(element: ET.Element) -> dict[str, str]:
    return {attribute.get("id"): attribute.get("value") for attribute in element.findall("attribute")}


def semantic(element: ET.Element) -> tuple:
    return (element.tag, tuple(sorted(element.attrib.items())), (element.text or "").strip(),
            tuple(semantic(child) for child in element))


def material(identifier: str) -> ET.Element:
    result = node("Resource", ID=identifier, Name="NativeSkin", MaterialType="18",
                  SourceFile="Public/Shared/Assets/Materials/Characters/CHAR_Skin_Body.lsf",
                  DiffusionProfileUUID="", _OriginalFileVersion_="144678138029277484")
    children = ET.SubElement(result, "children")
    children.extend([
        node("ScalarParameters", ParameterName="VeinAmount", Enabled="True", Value="0.5",
             BaseValue="1", ExportAsPreset="True", GroupName="02Skin Properties"),
        node("ScalarParameters", ParameterName="TMP_BODY_ROUGH", Enabled="False", Value="0.56",
             BaseValue="0.56", ExportAsPreset="True", GroupName="TMP"),
        node("ScalarParameters", ParameterName="MelaninAmount", Enabled="True", Value="0.3"),
        node("ScalarParameters", ParameterName="TattooIntensity", Enabled="True", Value="0.75"),
        node("VirtualTextureParameters", ParameterName="virtualtexture", VTBankID=VT, Enabled="True"),
        node("Texture2DParameters", ParameterName="DetailNormalMap", TextureResourceID=VT, Enabled="True"),
        node("Vector3Parameters", ParameterName="SkinColor", Value="0.2 0.4 0.6"),
    ])
    return result


class SkinMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source.lsx"
        self.output = self.base / "generated"
        self.root = ET.Element("save")
        region = ET.SubElement(self.root, "region", {"id": "MaterialBank"})
        self.resources = ET.SubElement(ET.SubElement(region, "node", {"id": "MaterialBank"}), "children")
        self.original = material(MATERIAL)
        self.resources.extend([self.original, material(UNREQUESTED)])
        self.save()

    def save(self):
        ET.ElementTree(self.root).write(self.source, encoding="utf-8", xml_declaration=True)

    def build(self, **kwargs):
        return create_soft_materials(kwargs.get("source_banks", [self.source]),
                                     kwargs.get("material_ids", [MATERIAL]),
                                     kwargs.get("output", self.output))

    def test_only_private_id_and_two_scalar_defaults_change(self):
        report = self.build()
        output = ET.parse(report["output"]).getroot()
        clones = output.findall('./region[@id="MaterialBank"]/node[@id="MaterialBank"]/children/node[@id="Resource"]')
        self.assertEqual(len(clones), 1)
        clone = clones[0]
        private_id = report["material_map"][MATERIAL]
        self.assertNotEqual(private_id, MATERIAL)
        self.assertEqual(UUID(private_id).version, 5)
        self.assertEqual(attrs(clone)["ID"], private_id)
        restored = copy.deepcopy(clone)
        restored.find('attribute[@id="ID"]').set("value", MATERIAL)
        originals = {attrs(item).get("ParameterName"): item
                     for item in self.original.findall('./children/node[@id="ScalarParameters"]')}
        for item in restored.findall('./children/node[@id="ScalarParameters"]'):
            parameter = attrs(item).get("ParameterName")
            if parameter in {"VeinAmount", "TMP_BODY_ROUGH"}:
                actual = attrs(item)
                self.assertEqual(actual["Enabled"], "True")
                self.assertEqual(actual["Value"], "0.15" if parameter == "VeinAmount" else "0.62")
                for key in ("Enabled", "Value"):
                    item.find(f'attribute[@id="{key}"]').set("value", attrs(originals[parameter])[key])
        self.assertEqual(semantic(restored), semantic(self.original))
        self.assertFalse(report["muscle_normal_maps_changed"])

    def test_source_files_and_unrequested_materials_remain_unchanged(self):
        source = self.source.read_bytes()
        report = self.build()
        self.assertEqual(self.source.read_bytes(), source)
        self.assertEqual(set(report["material_map"]), {MATERIAL})
        self.assertEqual(attrs(self.resources[1])["ID"], UNREQUESTED)
        second = self.build(output=self.base / "second")
        self.assertEqual(report["material_map"], second["material_map"])

    def test_missing_supported_scalar_is_rejected_without_output(self):
        children = self.original.find("children")
        children.remove(next(item for item in children if attrs(item).get("ParameterName") == "TMP_BODY_ROUGH"))
        self.save()
        with self.assertRaisesRegex(ValueError, "TMP_BODY_ROUGH"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_missing_scalar_value_does_not_invent_an_attribute(self):
        parameter = self.original.find('./children/node[@id="ScalarParameters"]')
        parameter.remove(parameter.find('attribute[@id="Enabled"]'))
        self.save()
        with self.assertRaisesRegex(ValueError, "existing Enabled and Value"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_unknown_requested_id_and_duplicate_scalar_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            self.build(material_ids=[VT])
        children = self.original.find("children")
        children.append(copy.deepcopy(children[0]))
        self.save()
        with self.assertRaisesRegex(ValueError, "exactly one existing scalar VeinAmount"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_ambiguous_source_definitions_are_rejected(self):
        other = self.base / "conflict.lsx"
        changed = copy.deepcopy(self.root)
        changed.find('.//attribute[@id="SourceFile"]').set("value", "OtherShader.lsf")
        ET.ElementTree(changed).write(other, encoding="utf-8", xml_declaration=True)
        with self.assertRaisesRegex(ValueError, "Conflicting material definitions"):
            self.build(source_banks=[self.source, other])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
