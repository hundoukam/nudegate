"""Tests for explicit, topology-preserving offline body morph authoring."""

from __future__ import annotations

import copy
import math
import unittest

from nudegate.morphs import apply_morph


def fixture() -> tuple[dict, dict]:
    mesh = {
        "topology_id": "authored-adult-body-v1",
        "positions": [[2.0, 3.0, 4.0], [6.0, 7.0, 8.0], [9, 10, 11]],
        "regions": {
            "chest_left": {"center": [1.0, 1.0, 1.0], "weights": [0.5, 1.0, 0.0]},
            "nipple_left": {"center": [0.0, 0.0, 0.0], "weights": [0.25, 0.0, 0.0]},
        },
        "locked_vertices": [1],
    }
    recipe = {"id": "shape-a", "topology_id": mesh["topology_id"],
              "region_scales": {"chest_left": [2.0, 1.0, 0.5], "nipple_left": [2.0, 2.0, 2.0]}}
    return mesh, recipe


class MorphTests(unittest.TestCase):
    def test_independent_regions_use_original_positions(self) -> None:
        mesh, recipe = fixture()
        result = apply_morph(mesh, recipe)
        # Chest delta (.5, 0, -.75) and separate nipple delta (.5, .75, 1)
        # are both computed from (2, 3, 4), never from the previous result.
        self.assertEqual(result["positions"][0], [3.0, 3.75, 4.25])
        self.assertEqual(result["report"]["moved_vertices"], 1)
        self.assertAlmostEqual(result["report"]["max_displacement"], math.sqrt(1 + .75 ** 2 + .25 ** 2))

    def test_seam_locks_and_unmasked_vertices_are_exact_copies(self) -> None:
        mesh, recipe = fixture()
        mesh["locked_vertices"] = [1, 1]
        result = apply_morph(mesh, recipe)
        self.assertEqual(result["positions"][1:], mesh["positions"][1:])
        self.assertIsInstance(result["positions"][2][0], int)
        self.assertIsNot(result["positions"][1], mesh["positions"][1])
        self.assertIsNot(result["positions"][2], mesh["positions"][2])
        self.assertEqual(result["report"]["locked_vertices"], 1)

    def test_inputs_and_external_topology_metadata_are_untouched(self) -> None:
        mesh, recipe = fixture()
        mesh["triangles"] = [[0, 1, 2]]
        mesh["skin_weights"] = [{"root": 1.0}] * 3
        before_mesh, before_recipe = copy.deepcopy(mesh), copy.deepcopy(recipe)
        result = apply_morph(mesh, recipe)
        result["positions"][0][0] = 999
        self.assertEqual(mesh, before_mesh)
        self.assertEqual(recipe, before_recipe)
        self.assertEqual(result["report"]["vertex_count"], len(mesh["positions"]))

    def test_deterministic_across_calls_and_recipe_region_order(self) -> None:
        mesh, recipe = fixture()
        first = apply_morph(mesh, recipe)
        second = apply_morph(mesh, recipe)
        recipe["region_scales"] = dict(reversed(list(recipe["region_scales"].items())))
        self.assertEqual(first, second)
        self.assertEqual(first, apply_morph(mesh, recipe))

    def test_identity_scales_do_not_move_vertices(self) -> None:
        mesh, recipe = fixture()
        recipe["region_scales"] = {"chest_left": [1, 1, 1]}
        result = apply_morph(mesh, recipe)
        self.assertEqual(result["positions"], mesh["positions"])
        self.assertEqual(result["report"]["moved_vertices"], 0)
        self.assertEqual(result["report"]["max_displacement"], 0.0)

    def test_topology_mismatch_or_missing_identifier_is_rejected(self) -> None:
        for mismatch in ("different-topology", "", None, 123):
            with self.subTest(topology=mismatch):
                mesh, recipe = fixture()
                recipe["topology_id"] = mismatch
                with self.assertRaisesRegex(ValueError, "topology_id"):
                    apply_morph(mesh, recipe)

    def test_overlap_is_rejected_including_locked_vertices(self) -> None:
        for vertex in (0, 1):
            with self.subTest(vertex=vertex):
                mesh, recipe = fixture()
                mesh["regions"]["nipple_left"]["weights"][vertex] = 0.75
                with self.assertRaisesRegex(ValueError, f"overlap at vertex {vertex}"):
                    apply_morph(mesh, recipe)

    def test_unselected_masks_do_not_contribute_to_overlap(self) -> None:
        mesh, recipe = fixture()
        mesh["regions"]["nipple_left"]["weights"] = [1.0, 1.0, 1.0]
        recipe["region_scales"] = {"chest_left": [2.0, 1.0, 1.0]}
        result = apply_morph(mesh, recipe)
        self.assertEqual(result["positions"][0], [2.5, 3.0, 4.0])

    def test_unknown_or_implicit_masks_are_rejected(self) -> None:
        for scales in ({"not-authored": [1, 1, 1]}, {}, None):
            with self.subTest(scales=scales):
                mesh, recipe = fixture()
                recipe["region_scales"] = scales
                with self.assertRaises(ValueError):
                    apply_morph(mesh, recipe)

    def test_nonfinite_positions_centers_weights_and_scales_are_rejected(self) -> None:
        for value in (float("nan"), float("inf"), -float("inf"), True, "1"):
            for target in ("position", "center", "weight", "scale"):
                with self.subTest(target=target, value=value):
                    mesh, recipe = fixture()
                    if target == "position":
                        mesh["positions"][0][0] = value
                    elif target == "center":
                        mesh["regions"]["chest_left"]["center"][0] = value
                    elif target == "weight":
                        mesh["regions"]["chest_left"]["weights"][0] = value
                    else:
                        recipe["region_scales"]["chest_left"][0] = value
                    with self.assertRaisesRegex(ValueError, "finite number"):
                        apply_morph(mesh, recipe)

    def test_out_of_range_weights_and_scales_are_rejected(self) -> None:
        for value in (-0.01, 1.01):
            with self.subTest(weight=value):
                mesh, recipe = fixture()
                mesh["regions"]["chest_left"]["weights"][0] = value
                with self.assertRaisesRegex(ValueError, r"weights must be within \[0, 1\]"):
                    apply_morph(mesh, recipe)
        for value in (0.4999, 2.0001):
            with self.subTest(scale=value):
                mesh, recipe = fixture()
                recipe["region_scales"]["chest_left"][0] = value
                with self.assertRaisesRegex(ValueError, r"scales must be within \[0.5, 2.0\]"):
                    apply_morph(mesh, recipe)

    def test_invalid_mask_sizes_and_coordinate_shapes_are_rejected(self) -> None:
        for target in ("positions", "center", "weights"):
            with self.subTest(target=target):
                mesh, recipe = fixture()
                if target == "positions":
                    mesh["positions"][0] = [1.0, 2.0]
                else:
                    mesh["regions"]["chest_left"][target] = [0.0, 0.0]
                with self.assertRaises(ValueError):
                    apply_morph(mesh, recipe)

    def test_invalid_locked_vertex_indices_are_rejected(self) -> None:
        for index in (-1, 3, True, 0.0, "0"):
            with self.subTest(index=index):
                mesh, recipe = fixture()
                mesh["locked_vertices"] = [index]
                with self.assertRaisesRegex(ValueError, "vertex ind"):
                    apply_morph(mesh, recipe)

    def test_unselected_masks_are_still_validated(self) -> None:
        mesh, recipe = fixture()
        recipe["region_scales"] = {"chest_left": [1, 1, 1]}
        mesh["regions"]["nipple_left"]["weights"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite number"):
            apply_morph(mesh, recipe)

    def test_empty_mesh_is_rejected(self) -> None:
        mesh, recipe = fixture()
        mesh["positions"] = []
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            apply_morph(mesh, recipe)

    def test_finite_inputs_that_overflow_are_rejected(self) -> None:
        mesh, recipe = fixture()
        mesh["positions"][0][0] = 1e308
        mesh["regions"]["chest_left"]["center"][0] = -1e308
        with self.assertRaisesRegex(ValueError, "arithmetic is nonfinite"):
            apply_morph(mesh, recipe)


if __name__ == "__main__":
    unittest.main()
