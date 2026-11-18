"""Sizes require reviewed volume growth, exact labels and actual geometry safety."""
import copy
import math
import unittest

from nudegate.breast_sizes import (BreastSizeError, apply_breast_size, author_breast_overlay_masks,
                                  calibrate_breast_wall, wall_calibration_digest)
from nudegate.surface_intersections import geometry_fingerprint


def fixture(reviewed=True):
    positions, triangles, locked = [], [], []
    weights = {"left": [], "right": []}
    centers = {"left": [-.12,1.35,-.055], "right": [.12,1.35,-.055]}
    for side in ("left", "right"):
        offset = len(positions)
        for row in range(7):
            for col in range(7):
                x,y = (col-3)*.02,(row-3)*.02
                value = max(0,1-(x/.06)**2-(y/.06)**2)
                positions.append([centers[side][0]+x,1.35+y,-.055-.05*value])
                for which in weights:
                    weights[which].append(value if which==side else 0)
                if row in (0,6) or col in (0,6):
                    locked.append(len(positions)-1)
        for row in range(6):
            for col in range(6):
                a=offset+row*7+col
                triangles.extend([(a,a+8,a+1),(a,a+7,a+8)])
    positions.extend([[0,1.30,-.055],[0,1.36,-.055],[0,1.33,-.055],[0,0,0]])
    for side in weights:
        weights[side].extend([0]*4)
    mesh={"positions":positions,"triangles":triangles,"locked_vertices":locked,
          "regions":{"chest_"+s:{"center":centers[s],"weights":weights[s]} for s in weights},
          "attachment_weights":[1]*len(positions),"frame":[1,1,1],"topology_id":"reviewed-dome",
          "uvs":[[0,0],[1,0]],"skin_weights":{"rig":"unchanged"}}
    if reviewed:
        mesh=author_breast_overlay_masks(mesh)
        mesh["quality_reference_positions"]=copy.deepcopy(mesh["positions"])
    return mesh


class BreastSizesTests(unittest.TestCase):
    def test_zero_is_exact_identity_including_coordinate_types(self):
        mesh=fixture();result=apply_breast_size(mesh,0)
        self.assertEqual(result["positions"],mesh["positions"])
        self.assertIsNot(result["positions"],mesh["positions"])
        for old,new in zip(mesh["positions"],result["positions"]):
            self.assertIsNot(old,new)
            self.assertEqual([type(v) for v in old],[type(v) for v in new])
        self.assertEqual(result["report"]["moved_vertices"],0)
        self.assertTrue(result["report"]["quality"]["safe"])

    def test_labels_have_exact_monotonic_wall_relative_projection(self):
        mesh=fixture();previous=0
        for percent in (25,50,100,200):
            result=apply_breast_size(mesh,percent);report=result["report"]
            self.assertTrue(report["quality"]["safe"])
            for side in ("left","right"):
                r=report["regions"][side]
                self.assertAlmostEqual(r["achieved_scale"],1+percent/100,places=10)
                self.assertAlmostEqual(r["achieved_projection"],r["target_projection"],places=10)
                self.assertGreater(r["achieved_projection"],previous)
                self.assertEqual(r["base_apex_position"],mesh["positions"][r["apex_vertex"]])
            previous=report["regions"]["left"]["achieved_projection"]

    def test_extremes_grow_measured_width_and_height_instead_of_tubes(self):
        # Former constant-Z translation with 12% XY growth fails this contract.
        for percent,minimum in ((100,1.2),(200,1.7)):
            for r in apply_breast_size(fixture(),percent)["report"]["regions"].values():
                self.assertGreater(r["measured_width_scale"],minimum)
                self.assertGreater(r["measured_height_scale"],minimum)
                self.assertLess(r["depth_to_width"],1)
                self.assertLess(r["depth_to_height"],1)
                self.assertGreater(r["envelope_volume_ratio"],(1+percent/100)**1.5)
                self.assertLess(r['ellipsoid_rms_radial_error'],.08)

    def test_protected_unmasked_vertices_and_midline_are_preserved(self):
        mesh=fixture();result=apply_breast_size(mesh,200)
        for i,(old,new) in enumerate(zip(mesh["positions"],result["positions"])):
            selected=any(mesh["regions"]["chest_"+s]["weights"][i]>0 for s in ("left","right"))
            if i in mesh["locked_vertices"] or not selected:
                self.assertEqual(old,new)
            if selected:
                self.assertGreater(old[0]*new[0],0)
        flow=result["report"]["sampled_flow"]
        self.assertGreater(flow["minimum_step_normal_cosine"],0)
        self.assertEqual(flow["new_collapsed_samples"],0)

    def test_source_base_rig_uv_and_configuration_are_not_mutated(self):
        source=fixture(False);snapshot=copy.deepcopy(source)
        mesh=author_breast_overlay_masks(source)
        self.assertEqual(source,snapshot)
        mesh["quality_reference_positions"]=copy.deepcopy(source["positions"])
        snapshot=copy.deepcopy(mesh)
        first=apply_breast_size(mesh,100)
        self.assertEqual(first,apply_breast_size(mesh,100))
        self.assertEqual(mesh,snapshot)
        self.assertEqual(first["report"]["wall_z"],-.055)
        self.assertIn("reference_normal_turns",first["report"]["quality"])
        self.assertNotIn("reversed_faces",first["report"]["quality"])
        self.assertEqual(first['report']['selected_transition_regularizer'],{'biharmonic':3.,'harmonic':0.})
        self.assertEqual(len(first['report']['transition_regularization_attempts']),1)

    def test_projection_core_excludes_deep_belly_transition(self):
        source=fixture(False)
        source["positions"].append([.08,1.18,-.25]);source["attachment_weights"].append(1)
        for r in source["regions"].values():r["weights"].append(0)
        mesh=author_breast_overlay_masks(source)
        self.assertGreater(mesh["regions"]["chest_right"]["weights"][-1],0)
        self.assertEqual(mesh["regions"]["chest_right"]["projection_weights"][-1],0)
        self.assertIn("wall_landmark_vertices",mesh["overlay_mask_review"])

    def test_percentages_reviews_and_source_binding_are_strict(self):
        for bad in (-1,1,75,201,True,False,100.0,"100",None):
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,"percent must"):
                apply_breast_size(fixture(),bad)
        with self.assertRaisesRegex(ValueError,"separately reviewed"):
            apply_breast_size(fixture(False),100)
        mesh=fixture();mesh["quality_reference_positions"][0][0]+=.001
        with self.assertRaisesRegex(ValueError,"does not match"):
            apply_breast_size(mesh,100)
        mesh=fixture();mesh.pop("quality_reference_positions")
        with self.assertRaisesRegex(ValueError,"quality_reference_positions"):
            apply_breast_size(mesh,100)

    def test_invalid_positions_masks_indices_and_feather_are_rejected(self):
        mutations=[lambda m:m["positions"][0].__setitem__(0,math.nan),
                   lambda m:m["regions"]["chest_left"]["weights"].__setitem__(0,2),
                   lambda m:m["regions"]["chest_right"]["weights"].pop(),
                   lambda m:m["locked_vertices"].append(len(m["positions"])),
                   lambda m:m["triangles"].__setitem__(0,(0,True,2)),
                   lambda m:m["regions"]["chest_left"]["projection_weights"].pop(),
                   lambda m:m["attachment_weights"].__setitem__(0,math.inf)]
        for mutate in mutations:
            mesh=fixture();mutate(mesh)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):apply_breast_size(mesh,100)

    def test_coincident_vertices_weld_and_unmasked_apex_duplicates_veto(self):
        for unmasked in (False,True):
            mesh=fixture(False);mesh["positions"].append(list(mesh["positions"][24]));mesh["attachment_weights"].append(1)
            for r in mesh["regions"].values():r["weights"].append(r["weights"][24])
            mesh=author_breast_overlay_masks(mesh)
            if unmasked:mesh["regions"]["chest_left"]["weights"][-1]=0
            mesh["quality_reference_positions"]=copy.deepcopy(mesh["positions"])
            if unmasked:
                with self.assertRaisesRegex(BreastSizeError,"unmasked duplicate"):apply_breast_size(mesh,200)
            else:
                result=apply_breast_size(mesh,200)
                self.assertEqual(result["positions"][24],result["positions"][-1])

    def test_infeasible_exact_size_is_rejected_instead_of_relabelled(self):
        mesh=fixture();mesh["locked_vertices"].append(24);snapshot=copy.deepcopy(mesh)
        with self.assertRaisesRegex(BreastSizeError,"apex is locked") as caught:apply_breast_size(mesh,200)
        self.assertEqual(caught.exception.report["projection_scale_target"],3)
        self.assertEqual(caught.exception.report["status"],"rejected")
        self.assertEqual(mesh,snapshot)

    def test_actual_collision_is_rejected_despite_continuous_local_motion(self):
        mesh=fixture();offset=len(mesh["positions"])
        mesh["positions"].extend([[-.25,1.2,-.16],[-.01,1.2,-.16],[-.12,1.55,-.16]])
        mesh["triangles"].append((offset,offset+1,offset+2));mesh["attachment_weights"].extend([0]*3)
        for r in mesh["regions"].values():r["weights"].extend([0]*3);r["projection_weights"].extend([0]*3)
        mesh["quality_reference_positions"]=copy.deepcopy(mesh["positions"])
        mesh["overlay_mask_review"]["source_geometry_sha256"]=geometry_fingerprint(mesh["positions"],mesh["triangles"])
        with self.assertRaisesRegex(BreastSizeError,"triangle intersections") as caught:apply_breast_size(mesh,200)
        self.assertGreater(caught.exception.report["quality"]["introduced_intersection_count"],0)
        self.assertEqual(caught.exception.report["quality"]["source_intersection_count"],0)
        attempts=caught.exception.report['transition_regularization_attempts']
        self.assertGreater(len(attempts),1)
        self.assertTrue(all(attempt['status']=='rejected' for attempt in attempts))

    def test_wall_calibration_binds_source_baked_profile_and_zero_report(self):
        mesh=fixture()
        calibration=calibrate_breast_wall(mesh,mesh['positions'],family_id='test_family',profile_fingerprint='a'*64)
        self.assertEqual(calibration['source_geometry_sha256'],geometry_fingerprint(mesh['positions'],mesh['triangles']))
        self.assertEqual(calibration['calibration_sha256'],wall_calibration_digest(calibration))
        self.assertEqual(calibration['wall_z'],-.055)
        self.assertEqual(calibration['cage_basis']['version'],'ellipsoid-residual-biharmonic-v1')
        mesh.update(body_family_id='test_family',base_profile_sha256='a'*64,body_lod=0,wall_calibration=calibration)
        for percent in (0,100):
            report=apply_breast_size(mesh,percent)['report']
            self.assertEqual(report['wall_calibration'],calibration)
            self.assertEqual(report['wall_z'],-.055)
        self.assertEqual(calibration['calibration_sha256'],wall_calibration_digest(calibration))

    def test_lower_lod_reuses_only_matching_reviewed_anchor(self):
        anchor=fixture()
        calibration=calibrate_breast_wall(anchor,anchor['positions'],family_id='test_family',profile_fingerprint='a'*64)
        source=fixture(False);source['topology_id']='reviewed-lower-lod'
        mesh=author_breast_overlay_masks(source);mesh['quality_reference_positions']=copy.deepcopy(source['positions'])
        mesh.update(body_family_id='test_family',base_profile_sha256='a'*64,body_lod=4,wall_calibration=calibration)
        self.assertEqual(apply_breast_size(mesh,100)['report']['wall_calibration'],calibration)
        for key,value in [('body_family_id','another_family'),('base_profile_sha256','b'*64),('body_lod',False)]:
            bad={**mesh,key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):apply_breast_size(bad,0)

    def test_calibration_tampering_or_wrong_lod0_base_is_rejected(self):
        mesh=fixture()
        calibration=calibrate_breast_wall(mesh,mesh['positions'],family_id='test_family',profile_fingerprint='a'*64)
        mesh.update(body_family_id='test_family',base_profile_sha256='a'*64,body_lod=0,wall_calibration=calibration)
        bad=copy.deepcopy(mesh);bad['wall_calibration']['wall_z']-=.01
        with self.assertRaisesRegex(ValueError,'digest'):apply_breast_size(bad,0)
        bad['wall_calibration']['calibration_sha256']=wall_calibration_digest(bad['wall_calibration'])
        with self.assertRaisesRegex(ValueError,'anchor differs'):apply_breast_size(bad,0)
        bad=copy.deepcopy(mesh);bad['positions'][24][2]-=.001
        with self.assertRaisesRegex(ValueError,'anchor differs'):apply_breast_size(bad,0)

    def test_rounded_cage_keeps_actual_source_nipple_relief(self):
        source=fixture(False)
        for side,apex in [('left',24),('right',73)]:
            source['positions'][apex][2]-=.005
            weights=[0]*len(source['positions']);weights[apex]=1
            source['regions']['nipple_'+side]={'weights':weights}
        mesh=author_breast_overlay_masks(source)
        mesh['quality_reference_positions']=copy.deepcopy(source['positions'])
        for percent in (100,200):
            result=apply_breast_size(mesh,percent)
            for side in ('left','right'):
                report=result['report']['regions'][side]
                self.assertAlmostEqual(report['source_feature_height'],.005,places=10)
                tip=result['positions'][report['apex_vertex']]
                carrier_pole_z=report['target_center'][2]-report['target_radii'][2]
                self.assertGreater(carrier_pole_z-tip[2],.003)
                self.assertLess(report['ellipsoid_rms_radial_error'],.18)
                self.assertEqual(report['feature_mode'],'preserved_source_residual')

    def test_signed_areolar_indent_does_not_shorten_the_labelled_projection(self):
        source=fixture(False)
        for side,apex in [('left',24),('right',73)]:
            source['positions'][apex][2]+=.002
            source['positions'][apex+2][2]-=.0001
            weights=[0]*len(source['positions']);weights[apex]=1;weights[apex+2]=.5
            source['regions']['nipple_'+side]={'weights':weights}
        mesh=author_breast_overlay_masks(source)
        mesh['quality_reference_positions']=copy.deepcopy(source['positions'])
        for percent in (50,100,200):
            result=apply_breast_size(mesh,percent)
            for region in result['report']['regions'].values():
                self.assertLess(region['carrier_relief_reserve'],0)
                self.assertAlmostEqual(region['achieved_projection'],region['target_projection'],places=8)
                self.assertAlmostEqual(region['achieved_scale'],1+percent/100,places=8)


if __name__=="__main__":unittest.main()
