"""Render crops use source topology and grow the view around actual geometry."""
import importlib.util
import math
from pathlib import Path
import unittest


_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'render_attachment_review.py'
_SPEC = importlib.util.spec_from_file_location('attachment_review_under_test', _PATH)
review = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(review)


class AttachmentReviewTests(unittest.TestCase):
    def test_crop_is_a_static_source_face_set_even_when_growth_leaves_old_window(self):
        source = [[-.10, 1.20, -.08], [.10, 1.20, -.08], [0., 1.40, -.13],
                  [0., 1.10, -.01], [.32, 1.30, -.01]]
        triangles = [(0, 1, 2), (0, 1, 3), (1, 2, 4)]
        selected = review.source_face_indices(triangles, source, [1., 1., 1.])
        self.assertEqual(selected, [0])
        grown = [list(point) for point in source]
        grown[0] = [-.45, 1.05, -.30]
        grown[1] = [.45, 1.05, -.30]
        grown[2] = [0., 1.60, -.45]
        # This is the old bug: reselecting against grown coordinates loses the lobe.
        self.assertEqual(review.source_face_indices(triangles, grown, [1., 1., 1.]), [])
        # Rendering keeps the original indices and fits ALL their actual vertices.
        display = [(x, z, y) for x, y, z in grown]
        self.assertEqual(review.selected_view_bounds(display, triangles, selected, 0., 0.),
                         [-.45, .45, 1.05, 1.60])

    def test_crop_uses_canonical_frame_without_mutating_inputs(self):
        source = [[-.2, 2.4, -.08], [.2, 2.4, -.08], [0., 2.8, -.13]]
        before = [list(point) for point in source]
        triangles = [(0, 1, 2)]
        self.assertEqual(review.source_face_indices(triangles, source, [2., 2., 3.]), [0])
        self.assertEqual(source, before)

    def test_fit_bounds_include_every_selected_corner_after_combined_rotation(self):
        vertices = [(-.5, -.4, -.3), (.6, -.2, .4), (0., .1, .6), (99., 99., 99.)]
        triangles = [(0, 1, 2), (1, 2, 3)]
        angles = (math.radians(-38), math.pi / 2)
        bounds = review.selected_view_bounds(vertices, triangles, [0], *angles)
        for vertex in vertices[:3]:
            x, _, z = review.rotate_display(vertex, *angles)
            self.assertLessEqual(bounds[0], x)
            self.assertGreaterEqual(bounds[1], x)
            self.assertLessEqual(bounds[2], z)
            self.assertGreaterEqual(bounds[3], z)
        self.assertLess(max(abs(value) for value in bounds), 1.)
        with self.assertRaisesRegex(ValueError, 'empty'):
            review.selected_view_bounds(vertices, triangles, [], *angles)

    def test_display_rotation_matches_render_object_order(self):
        rotated = review.rotate_display((1., 2., 3.), math.pi / 2, math.pi / 2)
        for actual, expected in zip(rotated, (3., 1., 2.)):
            self.assertAlmostEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
