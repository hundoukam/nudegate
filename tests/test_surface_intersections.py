"""Geometric acceptance must catch folds without banning legitimate rotations."""

from __future__ import annotations

import copy
import json
import math
import unittest

import numpy as np

from nudegate.surface_intersections import (SurfaceIntersectionChecker,
                                           SurfaceIntersectionError, geometry_fingerprint)


def independent(a, b):
    return a + b, [(0, 1, 2), (3, 4, 5)]


class SurfaceIntersectionsTests(unittest.TestCase):
    def test_disjoint_and_coplanar_disjoint_are_clear(self):
        a = [[0, 0, 0], [2, 0, 0], [0, 2, 0]]
        for b in ([[3, 3, 0], [4, 3, 0], [3, 4, 0]],
                  [[0, 0, 1], [2, 0, 1], [0, 2, 1]]):
            positions, faces = independent(a, b)
            report = SurfaceIntersectionChecker(positions, faces).check(positions)
            self.assertTrue(report['safe'])
            self.assertEqual(report['source_intersection_pairs'], [])

    def test_introduced_noncoplanar_crossing_and_exception_report(self):
        a = [[0, 0, 0], [2, 0, 0], [0, 2, 0]]
        b = [[.25, .25, -1], [.75, .25, 1], [.25, .75, 1]]
        candidate, faces = independent(a, b)
        source = a + [[x, y, z + 3] for x, y, z in b]
        checker = SurfaceIntersectionChecker(source, faces)
        report = checker.check(candidate)
        self.assertFalse(report['safe'])
        self.assertEqual(report['introduced_intersection_pairs'], [[0, 1]])
        self.assertEqual(report['source_intersection_count'], 0)
        with self.assertRaises(SurfaceIntersectionError) as raised:
            checker.validate(candidate)
        self.assertEqual(raised.exception.report, report)

    def test_positive_coplanar_overlap_including_containment(self):
        a = [[0, 0, 0], [2, 0, 0], [0, 2, 0]]
        for b in ([[.2, .2, 0], [.7, .2, 0], [.2, .7, 0]],
                  [[.4, -.5, 0], [1.4, .5, 0], [.4, 1.5, 0]]):
            positions, faces = independent(a, b)
            checker = SurfaceIntersectionChecker(positions, faces)
            self.assertEqual(checker.check(positions)['source_intersection_pairs'], [[0, 1]])
            # Reversing the second winding must not change the intersection.
            reversed_checker = SurfaceIntersectionChecker(positions, [faces[0], (3, 5, 4)])
            self.assertEqual(reversed_checker.check(positions)['source_intersection_pairs'], [[0, 1]])

    def test_point_and_boundary_edge_only_contacts_are_clear(self):
        a = [[0, 0, 0], [2, 0, 0], [0, 2, 0]]
        for b in ([[0, 0, 0], [-1, 0, 0], [0, -1, 0]],
                  [[0, 0, 0], [0, -1, 1], [0, -1, -1]],
                  [[.5, 0, 0], [1.5, 0, 0], [1, -1, 0]]):
            positions, faces = independent(a, b)
            self.assertEqual(SurfaceIntersectionChecker(positions, faces).check(positions)
                             ['source_intersection_count'], 0)

    def test_shared_vertex_does_not_hide_crossing_away_from_vertex(self):
        positions = [[0, 0, 0], [2, 0, 0], [0, 2, 0], [1, 1, -1], [1, 1, 1]]
        faces = [(0, 1, 2), (0, 3, 4)]
        self.assertEqual(SurfaceIntersectionChecker(positions, faces).check(positions)
                         ['source_intersection_pairs'], [[0, 1]])

    def test_shared_edge_touch_allowed_but_coplanar_fold_rejected(self):
        source = [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, -1, 1]]
        faces = [(0, 1, 2), (1, 0, 3)]
        checker = SurfaceIntersectionChecker(source, faces)
        self.assertEqual(checker.check(source)['source_intersection_count'], 0)
        candidate = copy.deepcopy(source)
        candidate[3] = [.5, .5, 0]
        report = checker.check(candidate)
        self.assertEqual(report['introduced_intersection_pairs'], [[0, 1]])
        self.assertFalse(report['safe'])

    def test_uv_split_edge_weld_and_new_fold(self):
        source, faces = independent([[0, 0, 0], [2, 0, 0], [0, 2, 0]],
                                    [[2, 0, 0], [0, 0, 0], [0, -1, 1]])
        checker = SurfaceIntersectionChecker(source, faces)
        self.assertEqual(checker.check(source)['welded_position_count'], 4)
        self.assertEqual(checker.check(source)['source_intersection_count'], 0)
        candidate = copy.deepcopy(source)
        candidate[5] = [.5, .5, 0]
        self.assertEqual(checker.check(candidate)['introduced_intersection_pairs'], [[0, 1]])

    def test_weld_checks_neighbor_hash_cells(self):
        # The two near positions straddle a cell boundary, with an unrelated
        # minimum establishing the hash origin at zero.
        positions = [[0, 0, 0], [.99, 1, 0], [1.01, 1, 0], [2, 0, 0], [2, 2, 0]]
        checker = SurfaceIntersectionChecker(positions, [(0, 1, 3), (0, 2, 4)],
                                             weld_tolerance=.05)
        self.assertEqual(checker.welded_vertices[1], checker.welded_vertices[2])

    def test_baseline_pairs_are_disclosed_and_new_pairs_are_not_exempted(self):
        source = [[0, 0, 0], [2, 0, 0], [0, 2, 0],
                  [.25, .25, -1], [.75, .25, 1], [.25, .75, 1],
                  [4, 4, -1], [4.5, 4, 1], [4, 4.5, 1]]
        faces = [(0, 1, 2), (3, 4, 5), (6, 7, 8)]
        checker = SurfaceIntersectionChecker(source, faces)
        baseline = checker.check(source)
        self.assertTrue(baseline['safe'])
        self.assertEqual(baseline['source_intersection_pairs'], [[0, 1]])
        candidate = copy.deepcopy(source)
        for i in (6, 7, 8):
            candidate[i][0] -= 3.75
            candidate[i][1] -= 3.75
        report = checker.check(candidate)
        self.assertIn([0, 2], report['introduced_intersection_pairs'])
        self.assertEqual(report['source_intersection_pair_sha256'], baseline['source_intersection_pair_sha256'])
        self.assertFalse(report['safe'])
        for i in (3, 4, 5):
            candidate[i][0] += 10
        self.assertEqual(checker.check(candidate)['resolved_intersection_pairs'], [[0, 1]])

    def test_new_collapse_rejected_existing_collapse_disclosed(self):
        source = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [2, 0, 0]]
        checker = SurfaceIntersectionChecker(source, [(0, 1, 2), (0, 1, 3)])
        report = checker.check([[0, 0, 0], [1, 0, 0], [.5, 0, 0], [2, 0, 0]])
        self.assertEqual(report['source_collapsed_faces'], 1)
        self.assertEqual(report['new_collapsed_face_indices'], [0])
        self.assertFalse(report['safe'])

    def test_legitimate_over_90_degree_turn_is_reported_and_allowed(self):
        source = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        candidate = [[0, 0, 0], [1, 0, 0], [0, -.5, math.sqrt(.75)]]
        report = SurfaceIntersectionChecker(source, [(0, 1, 2)]).validate(candidate)
        self.assertEqual(report['reference_normal_turns'], 1)
        self.assertEqual(report['reference_normal_turn_face_indices'], [0])
        self.assertTrue(report['safe'])

    def test_fixed_topology_finite_inputs_and_source_immutability(self):
        positions = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        faces = [(0, 1, 2)]
        before = copy.deepcopy(positions)
        checker = SurfaceIntersectionChecker(positions, faces, topology_id='fixture')
        report = checker.check(positions, triangles=faces, topology_id='fixture')
        json.dumps(report, allow_nan=False)
        self.assertEqual(positions, before)
        with self.assertRaises(ValueError):
            checker.check(positions, triangles=[(0, 2, 1)])
        with self.assertRaises(ValueError):
            checker.check(positions, topology_id='other')
        with self.assertRaises(ValueError):
            checker.check([[0, 0, 0], [1, 0, 0], [0, float('nan'), 0]])
        with self.assertRaises(ValueError):
            checker.check(positions[:2])
        with self.assertRaises(ValueError):
            checker.source[0, 0] = 5

    def test_bvh_matches_separate_pair_checks_with_active_triangle_filter(self):
        rng = np.random.default_rng(42)
        source = rng.uniform(-1, 1, size=(45, 3))
        faces = np.arange(45).reshape(-1, 3)
        checker = SurfaceIntersectionChecker(source, faces)
        expected = set()
        for i in range(len(faces)):
            for j in range(i + 1, len(faces)):
                vertices = source[np.concatenate((faces[i], faces[j]))]
                single = SurfaceIntersectionChecker(vertices, [(0, 1, 2), (3, 4, 5)])
                if single.source_pairs:
                    expected.add((i, j))
        self.assertEqual(checker.source_pairs, expected)
        candidate = source.copy()
        candidate[:6] += [.2, -.4, .3]
        report = checker.check(candidate)
        full = SurfaceIntersectionChecker(candidate, faces)
        self.assertEqual(report['candidate_intersection_pairs'], [list(pair) for pair in sorted(full.source_pairs)])

    def test_geometry_fingerprint_binds_positions_topology_and_report(self):
        positions = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
        faces = [(0, 1, 2), (0, 1, 3)]
        original = copy.deepcopy(positions)
        fingerprint = geometry_fingerprint(positions, faces)
        checker = SurfaceIntersectionChecker(positions, faces)
        report = checker.check(positions)
        self.assertEqual(report['source_geometry_sha256'], fingerprint)
        self.assertEqual(report['candidate_geometry_sha256'], fingerprint)
        changed = copy.deepcopy(positions)
        changed[3][2] += .1
        self.assertNotEqual(geometry_fingerprint(changed, faces), fingerprint)
        self.assertNotEqual(geometry_fingerprint(positions, [(0, 2, 1), faces[1]]), fingerprint)
        self.assertNotEqual(geometry_fingerprint(positions, faces[::-1]), fingerprint)
        report = checker.check(changed)
        self.assertEqual(report['candidate_geometry_sha256'], geometry_fingerprint(changed, faces))
        self.assertEqual(report['source_geometry_sha256'], fingerprint)
        self.assertEqual(positions, original)
        self.assertEqual(checker.check(positions)['candidate_geometry_sha256'], fingerprint)


if __name__ == '__main__':
    unittest.main()
