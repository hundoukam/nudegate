"""Additive body studies reject unsafe inputs and retain attachment seams."""

import copy
import math
from types import SimpleNamespace
import unittest

from nudegate.expansion import (
    apply_body_details, author_expansion_masks, effective_profile,
)


def profile():
    return {"id": "study", "chest_scale": [1.1, 1, 1.2],
            "hips_scale": [1.2, 1, 1.1], "thigh_scale": [1.1, 1, 1.1],
            "strong_adjustments": {"hip_width": 1.2, "thigh_width": 1.1,
                                   "bust_width": 1.05, "bust_projection": 1.04},
            "body_details": {"belly": .03, "abs": .004}}


def detail_mesh():
    # Front belly, protected front, feathered front, back, outside the detail band.
    return {"positions": [[.04, 1.155, -.12], [-.04, 1.155, -.12],
                          [.06, 1.155, -.12], [.04, 1.155, .08], [.04, .7, -.12]],
            "locked_vertices": [1], "attachment_weights": [1, 1, 0, 1, 1],
            "frame": [1, 1, 1]}


class ExpansionTests(unittest.TestCase):
    def test_effective_profile_is_independent_and_does_not_mutate_configuration(self):
        original = profile()
        before = copy.deepcopy(original)
        normal = effective_profile(original)
        strong = effective_profile(original, strong=True)
        self.assertEqual(original, before)
        self.assertEqual(normal["chest_scale"], before["chest_scale"])
        self.assertAlmostEqual(strong["hips_scale"][0], 1.44)
        self.assertAlmostEqual(strong["chest_scale"][2], 1.248)
        self.assertNotIn("strong_adjustments", strong)
        strong["body_details"]["belly"] = 0
        strong["hips_scale"][0] = 0
        self.assertEqual(original, before)

    def test_all_strong_multipliers_are_validated_even_for_normal_frames(self):
        for key in ("hip_width", "thigh_width", "bust_width", "bust_projection"):
            for bad in (True, "1", None, math.nan, math.inf, -math.inf, .84, 1.36):
                for strong in (False, True):
                    with self.subTest(key=key, bad=bad, strong=strong):
                        value = profile()
                        value["strong_adjustments"][key] = bad
                        with self.assertRaises(ValueError):
                            effective_profile(value, strong=strong)

    def test_rejects_unknown_settings_invalid_vectors_and_excessive_final_scale(self):
        cases = []
        value = profile(); value["strong_adjustments"]["typo"] = 1; cases.append(value)
        value = profile(); value["strong_adjustments"] = []; cases.append(value)
        for vector in ([1, 1], [1, True, 1], [1, math.nan, 1], [1, 2.1, 1]):
            value = profile(); value["hips_scale"] = vector; cases.append(value)
        value = profile(); value["chest_scale"][2] = 2; cases.append(value)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                effective_profile(value, strong=True)

    def test_details_move_only_front_unprotected_vertices_and_preserve_inputs(self):
        mesh = detail_mesh()
        positions = copy.deepcopy(mesh["positions"])
        before_mesh, before_positions, configuration = copy.deepcopy(mesh), copy.deepcopy(positions), profile()
        before_config = copy.deepcopy(configuration)
        result, report = apply_body_details(mesh, positions, configuration)
        self.assertLess(result[0][2], positions[0][2])
        self.assertEqual(result[0][:2], positions[0][:2])
        self.assertEqual(result[1:], positions[1:])
        self.assertEqual(report["moved_vertices"], 1)
        self.assertTrue(report["protected_vertices_unchanged"])
        self.assertEqual((mesh, positions, configuration), (before_mesh, before_positions, before_config))

    def test_details_follow_body_frame_and_zero_is_an_identity(self):
        mesh = detail_mesh()
        base, _ = apply_body_details(mesh, mesh["positions"], profile())
        scale = [1.2, 1.1, 1.15]
        strong = copy.deepcopy(mesh)
        strong["frame"] = scale
        strong["positions"] = [[p[k]*scale[k] for k in range(3)] for p in mesh["positions"]]
        result, _ = apply_body_details(strong, strong["positions"], profile())
        for a, b in zip(base, result):
            for k in range(3):
                self.assertAlmostEqual(a[k]*scale[k], b[k])
        result, report = apply_body_details(mesh, mesh["positions"], {})
        self.assertEqual(result, mesh["positions"])
        self.assertEqual(report["moved_vertices"], 0)

    def test_details_reject_invalid_settings_frames_weights_and_positions(self):
        for setting in ({"belly": True}, {"abs": "0.001"}, {"belly": math.nan},
                        {"belly": .076}, {"abs": .009}, {"unknown": 0}, []):
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                mesh = detail_mesh()
                apply_body_details(mesh, mesh["positions"], {"body_details": setting})
        mutations = [lambda m: m.update(frame=[1, 0, 1]),
                     lambda m: m.update(frame=[1, True, 1]),
                     lambda m: m.update(attachment_weights=[1]),
                     lambda m: m["attachment_weights"].__setitem__(0, math.inf),
                     lambda m: m["locked_vertices"].append(True),
                     lambda m: m["positions"][0].__setitem__(0, math.nan)]
        for mutate in mutations:
            mesh = detail_mesh(); mutate(mesh)
            with self.subTest(mesh=mesh), self.assertRaises(ValueError):
                apply_body_details(mesh, mesh["positions"], profile())
        mesh = detail_mesh()
        with self.assertRaises(ValueError):
            apply_body_details(mesh, mesh["positions"][:-1], profile())

    def test_details_keep_coincident_uv_vertices_welded(self):
        mesh = detail_mesh()
        mesh["positions"].append(list(mesh["positions"][0]))
        mesh["attachment_weights"].append(1)
        result, _ = apply_body_details(mesh, mesh["positions"], profile())
        self.assertEqual(result[0], result[-1])
        mesh["attachment_weights"][-1] = .5
        with self.assertRaisesRegex(ValueError, "Coincident"):
            apply_body_details(mesh, mesh["positions"], profile())

    def test_expansion_masks_partition_fields_and_preserve_attachment_zones(self):
        positions, triangles = [], []
        heights = [.1, .4, .7, .9, 1.05, 1.15, 1.25, 1.35, 1.45, 1.57]
        for y in heights:
            for i in range(24):
                angle = 2*math.pi*i/24
                positions.append([.16*math.cos(angle), y, .13*math.sin(angle)])
        for row in range(len(heights)-1):
            for i in range(24):
                a, b = row*24+i, row*24+(i+1)%24
                triangles.extend([(a,b,b+24), (a,b+24,a+24)])
        source = SimpleNamespace(positions=positions, triangles=triangles, topology_id="test-torso")
        before = copy.deepcopy((positions, triangles))
        masks, _ = author_expansion_masks(source)
        self.assertTrue(masks["locked_vertices"])
        self.assertTrue(any(w > 0 for w in masks["regions"]["waist"]["weights"]))
        for i in range(len(positions)):
            weights = [masks["regions"][name]["weights"][i]
                       for name in ("chest_left", "chest_right", "waist", "hips", "thighs")]
            self.assertGreaterEqual(min(weights), 0)
            self.assertLessEqual(sum(weights), 1+1e-12)
            if i in masks["locked_vertices"]:
                self.assertEqual(sum(weights), 0)
        self.assertEqual((positions, triangles), before)


if __name__ == "__main__":
    unittest.main()
