"""Actual near-coplanar witness and near-plane misses need exact predicates."""
import itertools
import unittest

from nudegate.surface_intersections import SurfaceIntersectionChecker


# Actual normal chubby +50 faces 12586/16360, remapped from source vertices
# 7916,7917,7918,7909. The candidate faces touch ONLY along edge7917--7918.
WITNESS_SOURCE = [
    [-.087973,1.37211,-.172163],[-.089614,1.374849,-.170342],
    [-.086339,1.372882,-.170386],[-.08808,1.375803,-.16841],
]
WITNESS_CANDIDATE = [
    [-.09166123332401929,1.3810792597756671,-.2552724068680399],
    [-.09507082129125478,1.3872842796299119,-.2529501053731923],
    [-.08869280371055047,1.3830746723985905,-.25367483615966274],
    [-.09244530326562007,1.390262057842704,-.2509436648392338],
]


class SurfacePredicateRegressions(unittest.TestCase):
    def test_actual_shared_edge_witness_is_contact_in_every_winding(self):
        for a,b in itertools.product(itertools.permutations((0,1,2)),
                                     itertools.permutations((2,1,3))):
            with self.subTest(a=a,b=b):
                report=SurfaceIntersectionChecker(WITNESS_SOURCE,[a,b]).check(WITNESS_CANDIDATE)
                self.assertTrue(report['safe'])
                self.assertEqual(report['candidate_intersection_count'],0)
                self.assertEqual(report['exact_fallback']['candidate_pairs_tested'],1)

    def test_small_signed_distance_must_not_hide_real_interior_crossing(self):
        a=[[0,0,0],[2,0,0],[0,2,0]]
        b=[[.25,.25,-.5e-9],[.75,.25,1e-8],[.25,.75,1e-8]]
        source=a+[[x,y,z+.0001] for x,y,z in b]
        report=SurfaceIntersectionChecker(source,[(0,1,2),(3,4,5)]).check(a+b)
        # The exact cut has a 33.67 mm segment inside BOTH triangles. The old
        # prefilter treated the -0.5 nm vertex as a sole touching vertex.
        self.assertEqual(report['introduced_intersection_pairs'],[[0,1]])
        self.assertFalse(report['safe'])
        self.assertEqual(report['candidate_search']['exact_fallback_pairs'],1)

    def test_distinct_parallel_planes_inside_tolerance_are_not_coplanar(self):
        a=[[0,0,0],[2,0,0],[0,2,0]]
        b=[[.2,.2,.5e-9],[.7,.2,.5e-9],[.2,.7,.5e-9]]
        report=SurfaceIntersectionChecker(a+b,[(0,1,2),(3,4,5)]).check(a+b)
        self.assertEqual(report['source_intersection_count'],0)
        self.assertEqual(report['exact_fallback']['source_pairs_tested'],1)

    def test_coplanar_adjacent_fold_still_has_positive_area(self):
        source=[[0,0,0],[2,0,0],[0,2,0],[.5,-.5,0]]
        candidate=source[:3]+[[.5,.5,0]]
        report=SurfaceIntersectionChecker(source,[(0,1,2),(1,0,3)]).check(candidate)
        self.assertEqual(report['introduced_intersection_pairs'],[[0,1]])
        self.assertGreater(report['candidate_search']['exact_fallback_pairs'],0)

    def test_source_weld_adjacency_does_not_exempt_a_split_candidate_crossing(self):
        a=[[0,0,0],[2,0,0],[0,2,0]]
        source=a+[[0,0,0],[2,0,0],[0,-1,0]]
        candidate=a+[[.25,.25,-.5e-9],[.75,.25,1e-8],[.25,.75,1e-8]]
        report=SurfaceIntersectionChecker(source,[(0,1,2),(3,4,5)]).check(candidate)
        self.assertEqual(report['welded_position_count'],4)
        self.assertEqual(report['introduced_intersection_pairs'],[[0,1]])

    def test_exact_cut_respects_explicit_segment_length_tolerance(self):
        epsilon=.001
        a=[[0,0,0],[1,0,0],[0,1,0]]
        for length,expected in ((.0005,0),(.002,1)):
            b=[[.25,.25,-epsilon*.5],[.25+length,.25,epsilon*.5],
               [.25-length,.25,epsilon*.5]]
            with self.subTest(length=length):
                checker=SurfaceIntersectionChecker(a+b,[(0,1,2),(3,4,5)],tolerance=epsilon)
                self.assertEqual(len(checker.source_pairs),expected)


if __name__=='__main__':
    unittest.main()
