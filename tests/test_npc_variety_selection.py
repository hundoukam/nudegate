import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build_npc_variety import ELF_BODY, SOURCE_BODY, plan_assignments


class NpcVarietySelectionTests(unittest.TestCase):
    def test_named_aliases_share_shape_across_original_human_and_elf_materials(self):
        rules = {"adults": [{"template_id": "original", "body_seed": "minthara"},
                           {"template_id": "placed", "body_seed": "minthara", "donor_profile": "mercy"},
                           {"template_id": "custom", "body_seed": "other"}]}
        rows = [{"template_id": "original", "body_set_visual": SOURCE_BODY},
                {"template_id": "placed", "body_set_visual": ELF_BODY},
                {"template_id": "custom", "body_set_visual": "unique-body"}]
        plan, native = plan_assignments(rows, rules, {"juno", "mercy"}, [])
        self.assertEqual(plan, {"original": (SOURCE_BODY, "mercy"), "placed": (ELF_BODY, "mercy")})
        self.assertEqual(native, {})

    def test_donor_pin_on_an_incompatible_body_stops_build(self):
        rules = {"adults": [{"template_id": "strong", "expected_name": "Example", "donor_profile": "mercy"}]}
        with self.assertRaisesRegex(ValueError, "matching body set"):
            plan_assignments([{"template_id": "strong", "body_set_visual": "unique-strong"}],
                             rules, {"mercy"}, [])
