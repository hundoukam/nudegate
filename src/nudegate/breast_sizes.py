"""Reviewed rounded body-volume authoring with exact identity and geometry proof."""


from __future__ import annotations


import math


import statistics


import hashlib


import json


import re


ALLOWED_PERCENTAGES = frozenset({0, 25, 50, 100, 200})


class BreastSizeError(ValueError):
    """A full requested overlay could not satisfy its protected surface bounds."""

    def __init__(self, reason: str, report: dict):
        self.report = {**report, "status": "rejected", "reason": reason}
        super().__init__(f"Breast size +{report['percent']} rejected: {reason}")


def _sequence(value: object, label: str) -> list | tuple:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} must be finite numeric data")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be finite numeric data") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite numeric data")
    return result


def _vector(value: object, label: str) -> tuple[float, float, float]:
    items = _sequence(value, label)
    if len(items) != 3:
        raise ValueError(f"{label} must have three coordinates")
    return tuple(_number(v, label) for v in items)


def author_breast_overlay_masks(mesh: dict) -> dict:
    """Author a separate front-torso transition for reviewed adult body sources.

    Call this on the original source masks, before substituting a baked base's
    positions. Base body sculpting must keep its original masks. The wider field
    supplies room for rounded enlargement while a lower, deeper wall suppresses
    unrelated belly motion. Existing attachment and seam protection always wins.
    This is a shape-authoring field, not an age or body-family classifier.
    """
    from .body_shapes import band, smooth
    if not isinstance(mesh, dict):
        raise ValueError("mesh must be an object")
    points = [_vector(p, "position") for p in _sequence(mesh.get("positions"), "positions")]
    if not points:
        raise ValueError("positions must not be empty")
    frame = _vector(mesh.get("frame", [1, 1, 1]), "frame")
    if any(not .8 <= value <= 1.4 for value in frame):
        raise ValueError("Overlay masks require a reviewed body frame")
    locked = set(_sequence(mesh.get("locked_vertices"), "locked_vertices"))
    if any(type(i) is not int or not 0 <= i < len(points) for i in locked):
        raise ValueError("Invalid protected overlay vertex")
    feather = [_number(w, "attachment weight") for w in
               _sequence(mesh.get("attachment_weights"), "attachment_weights")]
    if len(feather) != len(points) or any(not 0 <= w <= 1 for w in feather):
        raise ValueError("Attachment weights must match source vertices")
    regions = mesh.get("regions")
    if not isinstance(regions, dict):
        raise ValueError("Expected reviewed source regions")
    regions = {name: dict(value) for name, value in regions.items()}
    for side, sign in (("left", -1), ("right", 1)):
        name = "chest_" + side
        if name not in regions:
            raise ValueError("Missing reviewed " + name)
        _vector(regions[name].get("center"), name + " center")
        weights = []
        for i, point in enumerate(points):
            x, y, z = (point[k] / frame[k] for k in range(3))
            # The abdomen sits in front of the breast-wall pivot. Deepening the
            # wall below the inframammary transition leaves that surface alone.
            front = 1 - smooth(-.01, .025, z)
            weight = (band(sign*x, .006, .028, .225, .30)
                      * band(y, 1.08, 1.205, 1.435, 1.49) * front * feather[i])
            weights.append(0.0 if i in locked else weight)
        regions[name]["projection_weights"] = [
            weight if 1.27 < points[i][1] / frame[1] < 1.43 else 0.0
            for i, weight in enumerate(regions[name]["weights"])]
        regions[name]["weights"] = weights
    landmarks = [i for i, point in enumerate(points)
                 if abs(point[0]/frame[0]) < .018 and 1.27 < point[1]/frame[1] < 1.37
                 and point[2] < 0]
    if not landmarks:
        landmarks = [i for i, point in enumerate(points)
                     if abs(point[0]/frame[0]) < .03 and 1.24 < point[1]/frame[1] < 1.40
                     and point[2] < 0]
    if not landmarks:
        raise ValueError("Source has no reviewed medial torso-wall landmarks")
    from .surface_intersections import geometry_fingerprint
    return {**mesh, "regions": regions,
            "overlay_mask_review": {"version": "front-torso-volume-v2",
                                    "source_topology_id": mesh.get("topology_id"),
                                    "source_geometry_sha256": geometry_fingerprint(points, mesh["triangles"]),
                                    "wall_landmark_vertices": landmarks,
                                    "source_wall_z": statistics.median(points[i][2] for i in landmarks),
                                    "attachments_preserved": True,
                                    "projection_core_separate_from_transition": True}}


def wall_calibration_digest(record: dict) -> str:
    """Return the canonical provenance-record digest, excluding its own field."""
    if not isinstance(record, dict):
        raise ValueError("Expected a wall calibration record")
    data = {key: value for key, value in record.items() if key != "calibration_sha256"}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def calibrate_breast_wall(mesh: dict, base_positions: list, *, family_id: str,
                          profile_fingerprint: str) -> dict:
    """Bind one corrected LOD0 wall to its reviewed family and baked profile.

    The builder may reuse this JSON record for that family's LOD1--4, whose
    simplified sternum vertices need not retain anatomical wall landmarks.
    Its digest binds the record, not an external trust authority; package proof
    validation must match the anchor hashes to the actual LOD0 geometry.
    """
    from .surface_intersections import geometry_fingerprint
    if not isinstance(family_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", family_id):
        raise ValueError("Wall calibration requires an explicit body family")
    if not isinstance(profile_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", profile_fingerprint):
        raise ValueError("Wall calibration requires a SHA-256 base profile fingerprint")
    review = mesh.get("overlay_mask_review") if isinstance(mesh, dict) else None
    if not isinstance(review, dict) or review.get("version") != "front-torso-volume-v2":
        raise ValueError("Wall calibration requires separately reviewed source masks")
    source_hash = geometry_fingerprint(mesh["positions"], mesh["triangles"])
    if source_hash != review.get("source_geometry_sha256"):
        raise ValueError("Wall calibration source differs from its mask review")
    base = [_vector(point, "baked wall position") for point in _sequence(base_positions, "base_positions")]
    if len(base) != len(mesh["positions"]):
        raise ValueError("Wall calibration base vertex count differs from source")
    landmarks = _sequence(review.get("wall_landmark_vertices"), "wall landmark vertices")
    if not landmarks or any(type(i) is not int or not 0 <= i < len(base) for i in landmarks):
        raise ValueError("Wall calibration has invalid landmark indices")
    wall = float(statistics.median(base[i][2] for i in landmarks))
    if not -.5 < wall < 0:
        raise ValueError("Wall calibration lies outside the reviewed torso depth")
    record = {"schema_version": 1, "source_lod": 0, "family_id": family_id,
              "profile_sha256": profile_fingerprint,
              "source_topology_id": mesh.get("topology_id"),
              "source_geometry_sha256": source_hash,
              "baked_geometry_sha256": geometry_fingerprint(base, mesh["triangles"]),
              "source_vertex_count": len(base), "source_triangle_count": len(mesh["triangles"]),
              "frame": list(_vector(mesh.get("frame", [1, 1, 1]), "wall frame")),
              "wall_landmark_vertices": list(landmarks), "wall_z": wall}
    from .breast_cage import fit_cage_basis
    record["cage_basis"] = fit_cage_basis(mesh, base_positions, wall)
    record["calibration_sha256"] = wall_calibration_digest(record)
    return record


def _reviewed_wall_calibration(mesh: dict, source_hash: str) -> dict | None:
    record = mesh.get("wall_calibration")
    if record is None:
        return None
    if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
            or record["schema_version"] != 1 or type(record.get("source_lod")) is not int
            or record["source_lod"] != 0):
        raise ValueError("Expected a reviewed LOD0 wall calibration record")
    try:
        digest = wall_calibration_digest(record)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid wall calibration record data") from exc
    if digest != record.get("calibration_sha256"):
        raise ValueError("Wall calibration record digest differs")
    _vector(record.get("frame"), "calibration frame")
    vertex_count, triangle_count = record.get("source_vertex_count"), record.get("source_triangle_count")
    landmarks = record.get("wall_landmark_vertices")
    if (type(vertex_count) is not int or vertex_count < 1
            or type(triangle_count) is not int or triangle_count < 1
            or not isinstance(landmarks, list) or not landmarks
            or any(type(i) is not int or not 0 <= i < vertex_count for i in landmarks)):
        raise ValueError("Invalid wall calibration landmark provenance")
    if (record.get("family_id") != mesh.get("body_family_id")
            or record.get("profile_sha256") != mesh.get("base_profile_sha256")
            or record.get("frame") != list(mesh.get("frame", [1, 1, 1]))):
        raise ValueError("Wall calibration family, profile or frame differs")
    if (not isinstance(record.get("family_id"), str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", record["family_id"])
            or any(not isinstance(record.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", record[key])
                   for key in ("profile_sha256", "source_geometry_sha256", "baked_geometry_sha256"))
            or not isinstance(record.get("source_topology_id"), str) or not record["source_topology_id"]):
        raise ValueError("Wall calibration provenance is incomplete")
    lod = mesh.get("body_lod")
    if type(lod) is not int or not 0 <= lod <= 4:
        raise ValueError("Wall calibration requires an explicit body_lod in 0..4")
    if lod == 0:
        from .surface_intersections import geometry_fingerprint
        if (record["source_topology_id"] != mesh.get("topology_id")
                or record["source_geometry_sha256"] != source_hash
                or record["baked_geometry_sha256"] != geometry_fingerprint(mesh["positions"], mesh["triangles"])
                or vertex_count != len(mesh["positions"]) or triangle_count != len(mesh["triangles"])
                or record["wall_z"] != statistics.median(mesh["positions"][i][2] for i in landmarks)):
            raise ValueError("LOD0 wall calibration anchor differs from current source or baked base")
    elif record["source_topology_id"] == mesh.get("topology_id"):
        raise ValueError("A lower LOD cannot reuse the anchor topology identifier")
    wall = _number(record.get("wall_z"), "calibrated wall")
    if not -.5 < wall < 0:
        raise ValueError("Calibrated wall is outside the reviewed depth")
    return dict(record)


_SURFACE_CHECKERS = {}


def _validate_inputs(mesh, percent):
    if type(percent) is not int or percent not in ALLOWED_PERCENTAGES:
        raise ValueError('percent must be one of the integers 0, 25, 50, 100, 200')
    if not isinstance(mesh,dict):
        raise ValueError('mesh must be an object')
    raw=_sequence(mesh.get('positions'),'positions')
    if not raw:raise ValueError('positions must not be empty')
    points=[_vector(p,'position') for p in raw]
    count=len(points)
    reference=mesh.get('quality_reference_positions',raw)
    reference=[_vector(p,'quality reference position') for p in _sequence(reference,'quality_reference_positions')]
    if len(reference)!=count:raise ValueError('quality_reference_positions must match the baked position count')
    triangles=[]
    for t in _sequence(mesh.get('triangles'),'triangles'):
        tri=_sequence(t,'triangle')
        if len(tri)!=3 or any(type(i) is not int or not 0<=i<count for i in tri):
            raise ValueError('Triangles require three in-range integer indices')
        triangles.append(tuple(tri))
    if not triangles:raise ValueError('triangles must not be empty')
    locked=set()
    for i in _sequence(mesh.get('locked_vertices'),'locked_vertices'):
        if type(i) is not int or not 0<=i<count:raise ValueError('Locked vertex indices must be in-range integers')
        locked.add(i)
    frame=_vector(mesh.get('frame',[1,1,1]),'frame')
    if any(not .8<=v<=1.4 for v in frame):raise ValueError('frame must match a reviewed adult body rig')
    regions=mesh.get('regions')
    if not isinstance(regions,dict):raise ValueError('Expected reviewed body regions')
    reviewed={}
    for side,sign in [('left',-1),('right',1)]:
        r=regions.get('chest_'+side)
        if not isinstance(r,dict):raise ValueError('Missing reviewed chest_'+side)
        center=_vector(r.get('center'),'chest center')
        weights=[_number(w,'chest weight') for w in _sequence(r.get('weights'),'chest weights')]
        if len(weights)!=count or any(not 0<=w<=1 for w in weights):raise ValueError('Chest weights must match vertex count and lie in [0,1]')
        if sign*center[0]<=0 or any(w>0 and sign*p[0]<=0 for p,w in zip(points,weights)):
            raise ValueError('Chest masks must remain on their reviewed side of the midline')
        reviewed[side]=weights
        if percent:
            core=[_number(w,'projection core weight') for w in _sequence(r.get('projection_weights'),'projection core weights')]
            if len(core)!=count or any(not 0<=w<=1 for w in core):raise ValueError('Projection core weights must match source vertices')
        nipple=regions.get('nipple_'+side)
        if nipple is not None:
            weights=[_number(w,'nipple weight') for w in _sequence(nipple.get('weights'),'nipple weights')]
            if len(weights)!=count or any(not 0<=w<=1 for w in weights):raise ValueError('Nipple weights must match source vertices')
    if any(a>0 and b>0 for a,b in zip(reviewed['left'],reviewed['right'])):raise ValueError('Reviewed chest masks may not overlap')
    if percent:
        feather=[_number(w,'attachment weight') for w in _sequence(mesh.get('attachment_weights'),'attachment_weights')]
        if len(feather)!=count or any(not 0<=w<=1 for w in feather):raise ValueError('Attachment weights must match source vertices')
    return raw,reference,triangles,locked,frame,reviewed


def apply_breast_size(mesh:dict,percent:int)->dict:
    """Author one reviewed rounded cage size; +0 is an exact identity.

    Positive sizes require author_breast_overlay_masks on pristine source masks,
    then baked base positions and quality_reference_positions. A shared LOD0
    wall_calibration carries the cage basis to lower LODs. Exact 2x/3x projection
    includes original geometric nipple relief. Only positions are returned.
    """
    # Detect absent review before requesting its optional projection mask fields.
    if type(percent) is not int or percent not in ALLOWED_PERCENTAGES:
        raise ValueError('percent must be one of the integers 0, 25, 50, 100, 200')
    if percent and (not isinstance(mesh,dict) or not isinstance(mesh.get('overlay_mask_review'),dict)
                    or mesh['overlay_mask_review'].get('version')!='front-torso-volume-v2'):
        raise ValueError('Positive sizes require separately reviewed volumetric overlay masks')
    raw,reference,triangles,locked,frame,reviewed=_validate_inputs(mesh,percent)
    from .surface_intersections import SurfaceIntersectionChecker,geometry_fingerprint
    source_hash=geometry_fingerprint(reference,triangles)
    calibration=_reviewed_wall_calibration(mesh,source_hash)
    key=(source_hash,mesh.get('topology_id'))
    checker=_SURFACE_CHECKERS.get(key)
    if checker is None:
        checker=SurfaceIntersectionChecker(reference,triangles,topology_id=mesh.get('topology_id'))
        if len(_SURFACE_CHECKERS)>=16:_SURFACE_CHECKERS.pop(next(iter(_SURFACE_CHECKERS)))
        _SURFACE_CHECKERS[key]=checker
    quality=checker.check(raw,triangles=triangles,topology_id=mesh.get('topology_id'))
    report={'percent':percent,'status':'accepted','projection_scale_target':1+percent/100,
            'definition':'protrusion from reviewed medial torso-wall landmarks including source tip relief',
            'frame':list(frame),'topology_id':mesh.get('topology_id'),'vertex_count':len(raw),
            'triangle_count':len(triangles),'physics':'not included',
            'global_self_intersections':'checked against pristine source triangle pairs','quality':quality}
    if calibration is not None:
        report['wall_calibration']=calibration
        report['wall_z']=calibration['wall_z']
    if not quality['safe']:
        raise BreastSizeError('Base body introduced intersections or collapsed faces',report)
    if percent==0:
        report.update(moved_vertices=0,max_displacement_metres=0.,protected_vertices_unchanged=True,
                      unmasked_vertices_unchanged=True,guard='exact identity with actual source intersection proof')
        return {'positions':[list(p) for p in raw],'report':report}
    review=mesh['overlay_mask_review']
    if 'quality_reference_positions' not in mesh:raise ValueError('Volumetric overlays require original quality_reference_positions')
    if source_hash!=review.get('source_geometry_sha256') or review.get('source_topology_id')!=mesh.get('topology_id'):
        raise ValueError('Overlay review does not match the original source geometry')
    from .breast_cage import (apply_cage,fit_cage_basis,validate_cage_basis,CageError,
                              TRANSITION_REGULARIZERS)
    landmarks=_sequence(review.get('wall_landmark_vertices'),'wall landmark vertices')
    if not landmarks or any(type(i) is not int or not 0<=i<len(raw) for i in landmarks):raise ValueError('Invalid reviewed torso-wall landmarks')
    wall=float(calibration['wall_z']) if calibration is not None else float(statistics.median(raw[i][2] for i in landmarks))
    try:
        if calibration is not None:
            basis=calibration.get('cage_basis')
            validate_cage_basis(basis)
        else:
            if mesh.get('body_lod',0)!=0:raise ValueError('Lower LODs require a shared LOD0 cage calibration')
            basis=fit_cage_basis(mesh,raw,wall)
    except CageError as exc:
        raise BreastSizeError(str(exc),{**report,**exc.report}) from exc
    # Intrinsic cage dimensions, centre, projection and native relief do not
    # change between attempts. Only the welded transition energy is varied.
    attempts=[]
    failures=[]
    selected_result=None
    anatomical_core=[False]*len(raw)
    for side in ('left','right'):
        source_regions=mesh['regions']
        for i,weight in enumerate(source_regions['chest_'+side]['projection_weights']):
            anatomical_core[i]|=weight>0
        nipple=source_regions.get('nipple_'+side)
        if nipple is not None:
            for i,weight in enumerate(nipple['weights']):
                anatomical_core[i]|=weight>0
    for biharmonic,harmonic in TRANSITION_REGULARIZERS:
        attempt={'biharmonic':biharmonic,'harmonic':harmonic,'status':'rejected'}
        try:
            candidate=apply_cage(mesh,percent,wall,basis,regularizer=(biharmonic,harmonic))
        except CageError as exc:
            attempt.update(reason=str(exc),candidate_final_proof_evaluated=False)
            attempts.append(attempt)
            failures.append((str(exc),{**report,**exc.report,'candidate_final_proof_evaluated':False}))
            continue
        positions=candidate['positions']
        core_crossings=[]
        broad_crossings=[]
        for i,(before,after) in enumerate(zip(raw,positions)):
            selected=reviewed['left'][i]>0 or reviewed['right'][i]>0
            if (i in locked or not selected) and list(before)!=after:
                raise BreastSizeError('Cage moved a protected or unmasked vertex',report)
            if selected and before[0]*after[0]<=0:
                (core_crossings if anatomical_core[i] else broad_crossings).append(i)
        candidate_quality=checker.check(positions,triangles=triangles,topology_id=mesh.get('topology_id'))
        candidate_report={**report,**candidate['report'],'quality':candidate_quality,
                          'candidate_final_proof_evaluated':True,
                          'projection_core_midline_crossings':core_crossings,
                          'broad_torso_midline_crossings':broad_crossings}
        attempt.update(candidate_final_proof_evaluated=True,
                       introduced_intersection_count=candidate_quality['introduced_intersection_count'],
                       new_collapsed_faces=candidate_quality['new_collapsed_faces'],
                       projection_core_midline_crossings=len(core_crossings),
                       broad_torso_midline_crossings=len(broad_crossings),
                       candidate_geometry_sha256=candidate_quality['candidate_geometry_sha256'],
                       ellipsoid_rms_radial_error={s:r['ellipsoid_rms_radial_error']
                                                  for s,r in candidate['report']['regions'].items()})
        if core_crossings:
            reason='Cage crossed the reviewed anatomical breast midline'
        elif not candidate_quality['safe']:
            reason='Enlargement introduced triangle intersections or collapsed faces'
        else:
            attempt['status']='accepted'
            attempts.append(attempt)
            selected_result=(positions,candidate_report)
            break
        attempt['reason']=reason
        attempts.append(attempt)
        failures.append((reason,candidate_report))
    if selected_result is None:
        # Prefer a geometrically evaluated failure for diagnosis over a path-only
        # veto. No rejected coordinates can escape through the public API.
        evaluated=[item for item in failures if item[1].get('candidate_final_proof_evaluated')]
        if evaluated:
            reason,failed=min(evaluated,key=lambda item:(item[1]['quality']['introduced_intersection_count'],
                                                        len(item[1].get('projection_core_midline_crossings',[]))))
        else:
            reason,failed=failures[-1]
        failed['transition_regularization_attempts']=attempts
        raise BreastSizeError(reason,failed)
    positions,report=selected_result
    report.update(mode='rounded_ellipsoid_cage_v1',wall_z=wall,
                  guard='rounded ellipsoid objective, anatomical core separation and explicit triangle intersections',
                  overlay_mask_review=dict(review),cage_basis=basis,
                  transition_regularization_attempts=attempts,
                  selected_transition_regularizer=dict(report['transition_regularizer']))
    distances=[math.dist(a,b) for a,b in zip(raw,positions)]
    report.update(moved_vertices=sum(d>0 for d in distances),max_displacement_metres=max(distances),
                  protected_vertices_unchanged=True,unmasked_vertices_unchanged=True)
    return {'positions':positions,'report':report}
