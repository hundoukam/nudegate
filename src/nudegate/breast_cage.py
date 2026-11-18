"""Rounded adult-body authoring cages with source geometric relief retained.

Only positions are authored. The caller owns source review, final intersection
proof, resource registration and game installation. SciPy is an authoring extra.
"""
from __future__ import annotations

import hashlib
import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import factorized


VERSION = "ellipsoid-residual-biharmonic-v1"
TRANSITION_REGULARIZERS = (
    (3., 0.), (6., 0.), (12., 0.), (3., .25), (6., .5), (12., 1.),
    (3., 4.), (3., 16.), (3., 32.), (3., 64.),
)


class CageError(ValueError):
    def __init__(self, reason, report=None):
        self.report = report or {}
        super().__init__(reason)


def _groups(mesh, positions):
    source = np.asarray(mesh.get("quality_reference_positions", mesh["positions"]), dtype=float)
    base = np.asarray(positions, dtype=float)
    _, first, inverse = np.unique(source, axis=0, return_index=True, return_inverse=True)
    grouped = base[first].copy()
    if not np.array_equal(grouped[inverse], base):
        raise CageError("Cage input split coincident source vertices")
    members = [[] for _ in first]
    for i, group in enumerate(inverse):
        members[group].append(i)
    locked = set(int(inverse[i]) for i in mesh["locked_vertices"])
    return grouped, first, inverse, members, locked


def _weights(values, members):
    values = np.asarray(values, dtype=float)
    return np.asarray([min(values[i] for i in group) for group in members])


def _side(mesh, grouped, members, locked, side):
    region = mesh["regions"]["chest_"+side]
    broad = _weights(region["weights"], members)
    core = _weights(region["projection_weights"], members)
    active = broad > 0
    active[list(locked)] = False
    cores = np.flatnonzero(core > 0)
    if not len(cores):
        raise CageError(side+" reviewed chest projection core is empty")
    apex = int(cores[np.argmin(grouped[cores, 2])])
    if not active[apex]:
        raise CageError(side+" reviewed apex is locked or has an unmasked duplicate")
    return active, core, cores, apex


def _feature_fit(mesh, grouped, members, active, apex, projection, wall, side, frame):
    region = mesh["regions"].get("nipple_"+side)
    if region is None:
        return {"mode": "no_reviewed_feature"}, np.zeros(len(grouped))
    nw = _weights(region["weights"], members)
    sign = -1 if side == "left" else 1
    feature_center = int(np.argmax(nw))
    dx = (grouped[:, 0]-grouped[feature_center, 0])/frame[0]
    dy = (grouped[:, 1]-grouped[feature_center, 1])/frame[1]
    radius = np.hypot(dx, dy)
    u, v = dx/.025, dy/.025
    design = np.column_stack((np.ones(len(grouped)), u, v, u*u, u*v, v*v))
    annulus = ((radius >= .019) & (radius <= .034) & (sign*grouped[:, 0] > 0)
               & (wall-grouped[:, 2] > .25*projection) & (nw < .01))
    coefficients, _, rank, _ = np.linalg.lstsq(design[annulus], grouped[annulus, 2], rcond=None)
    if rank < 6 or int(annulus.sum()) < 8:
        raise CageError(side+" LOD0 nipple carrier lacks a resolved fitting annulus")
    relief = (design@coefficients-grouped[:, 2])*nw
    relief[~active] = 0
    height, apex_height = float(max(0, relief.max())), float(relief[apex])
    if not 0 < height < .03*frame[2] or not -.03*frame[2] < apex_height <= height:
        raise CageError(side+" nipple carrier fit has an unsupported source relief")
    return {"mode": "quadratic_annulus_residual", "basis_radius": .025,
            "center_xy": grouped[feature_center, :2].tolist(), "coefficients": coefficients.tolist(),
            "annulus_vertices": int(annulus.sum()), "rank": int(rank),
            "height_max": height, "apex_height": apex_height,
            "source_mask_sha256": hashlib.sha256(np.asarray(region["weights"], dtype="<f8").tobytes()).hexdigest()}, relief


def fit_cage_basis(mesh: dict, positions: list, wall: float) -> dict:
    """Fit one corrected LOD0; lower LODs reuse these dimensions and centres."""
    grouped, first, _, members, locked = _groups(mesh, positions)
    frame = np.asarray(mesh.get("frame", [1, 1, 1]), dtype=float)
    regions = {}
    for side, sign in (("left", -1), ("right", 1)):
        active, core, cores, apex = _side(mesh, grouped, members, locked, side)
        projection = wall-float(grouped[apex, 2])
        if projection <= 0:
            raise CageError(side+" chest does not protrude from its reviewed wall")
        metric = cores[(core[cores] >= .5*max(core[cores])) & (wall-grouped[cores, 2] > .15*projection)]
        if len(metric) < 3:
            raise CageError(side+" LOD0 cannot resolve its chest contour dimensions")
        dimensions = np.ptp(grouped[metric], axis=0)
        feature, relief = _feature_fit(mesh, grouped, members, active, apex, projection, wall, side, frame)
        radii = [float(dimensions[0]/2), float(dimensions[1]/2), projection-float(relief[apex])]
        if min(radii) <= 1e-8:
            raise CageError(side+" chest cage has degenerate radii")
        regions[side] = {"source_pole": [float(grouped[apex, 0]), float(grouped[apex, 1]), wall],
                         "source_apex_vertex": int(first[apex]), "source_tip_projection": projection,
                         "carrier_radii": radii, "feature": feature}
    return {"version": VERSION, "source_lod": 0, "regions": regions}


def validate_cage_basis(basis: dict) -> None:
    if not isinstance(basis, dict) or basis.get("version") != VERSION or basis.get("source_lod") != 0:
        raise ValueError("Expected a reviewed LOD0 rounded cage basis")
    if not isinstance(basis.get("regions"), dict) or set(basis["regions"]) != {"left", "right"}:
        raise ValueError("Cage basis requires both reviewed lobes")
    for side, sign in (("left", -1), ("right", 1)):
        region = basis["regions"][side]
        for key in ("source_pole", "carrier_radii"):
            value = region.get(key)
            if (not isinstance(value, list) or len(value) != 3
                    or any(type(v) not in (int, float) or not np.isfinite(v) for v in value)):
                raise ValueError("Invalid cage "+key)
        if (sign*region["source_pole"][0] <= 0 or min(region["carrier_radii"]) <= 1e-8
                or type(region.get("source_tip_projection")) not in (int, float)
                or not np.isfinite(region["source_tip_projection"]) or region["source_tip_projection"] <= 0):
            raise ValueError("Invalid reviewed cage dimensions")
        feature = region.get("feature")
        if not isinstance(feature, dict) or feature.get("mode") not in {"no_reviewed_feature", "quadratic_annulus_residual"}:
            raise ValueError("Invalid reviewed cage feature mode")
        if feature["mode"] == "quadratic_annulus_residual":
            values = feature.get("coefficients")
            if (not isinstance(values, list) or len(values) != 6
                    or any(type(v) not in (int, float) or not np.isfinite(v) for v in values)
                    or not 0 < feature.get("height_max", 0) < .05
                    or not -.05 < feature.get("apex_height", 0) <= feature["height_max"]):
                raise ValueError("Invalid reviewed cage feature fit")


def _relief(mesh, grouped, members, active, feature, side, lod, frame):
    if feature["mode"] == "no_reviewed_feature":
        return np.zeros(len(grouped)), "no_reviewed_feature"
    region = mesh["regions"].get("nipple_"+side)
    if region is None:
        raise CageError("Resolved source nipple review is missing")
    nw = _weights(region["weights"], members)
    # Coarse native meshes cannot represent the high-detail carrier residual.
    # Their cage retains the shared full tip envelope rather than inventing it.
    if lod > 0 and int(np.count_nonzero(nw > .1)) < 8:
        return np.zeros(len(grouped)), "coarse_tip_envelope"
    cx, cy = feature["center_xy"]
    u = (grouped[:, 0]-cx)/(feature["basis_radius"]*frame[0])
    v = (grouped[:, 1]-cy)/(feature["basis_radius"]*frame[1])
    design = np.column_stack((np.ones(len(grouped)), u, v, u*u, u*v, v*v))
    relief = (design@np.asarray(feature["coefficients"])-grouped[:, 2])*nw
    relief[~active] = 0
    if lod == 0:
        digest = hashlib.sha256(np.asarray(region["weights"], dtype="<f8").tobytes()).hexdigest()
        if digest != feature["source_mask_sha256"]:
            raise CageError("LOD0 nipple review differs from cage calibration")
    if float(max(0, relief.max())) >= .03*frame[2]:
        raise CageError("Cage feature residual exceeds its reviewed range")
    if lod > 0 and float(relief.max()) <= 0:
        return np.zeros(len(grouped)), "coarse_tip_envelope"
    return relief, "preserved_source_residual"


def _front_dimensions(positions, faces, wall, projection):
    """Measure a surface cap, including edge intersections on sparse LODs."""
    plane = wall-.15*projection
    samples = []
    for face in faces:
        polygon = [positions[i] for i in face]
        clipped = []
        before = polygon[-1]
        for after in polygon:
            inside_before, inside_after = before[2] <= plane, after[2] <= plane
            if inside_before != inside_after:
                fraction = (plane-before[2])/(after[2]-before[2])
                clipped.append(before+fraction*(after-before))
            if inside_after:
                clipped.append(after)
            before = after
        samples.extend(clipped)
    if not samples:
        return np.zeros(3), 0
    samples = np.unique(np.asarray(samples), axis=0)
    return np.ptp(samples, axis=0), len(samples)


def apply_cage(mesh: dict, percent: int, wall: float, basis: dict, *,
               regularizer=(3., 0.), _radius_adjustments=None, _calibration_iteration=0) -> dict:
    """Author one positive size on the shared rounded cage; mutate no inputs."""
    validate_cage_basis(basis)
    if regularizer not in TRANSITION_REGULARIZERS:
        raise ValueError("Unreviewed cage transition regularizer")
    biharmonic, harmonic = regularizer
    grouped, first, inverse, members, locked = _groups(mesh, mesh["positions"])
    frame = np.asarray(mesh.get("frame", [1, 1, 1]), dtype=float)
    triangles = np.asarray(mesh["triangles"], dtype=int)
    lod, scale = mesh.get("body_lod", 0), 1+percent/100
    radius_adjustments = _radius_adjustments or {"left": 0., "right": 0.}
    active_all = np.zeros(len(grouped), dtype=bool)
    data_weights = np.zeros(len(grouped))
    target_displacement = np.zeros_like(grouped)
    total_relief = np.zeros(len(grouped))
    side_data, anchors, reports = {}, {}, {}
    for side, sign in (("left", -1), ("right", 1)):
        active, _, cores, apex = _side(mesh, grouped, members, locked, side)
        if np.any(active_all & active):
            raise CageError("Rounded cage lobe masks overlap")
        active_all |= active
        source = basis["regions"][side]
        relief, feature_mode = _relief(mesh, grouped, members, active, source["feature"], side, lod, frame)
        total_relief += relief
        side_data[side] = (sign, active, cores, apex, source, relief, feature_mode)
    carrier = grouped.copy()
    carrier[:, 2] += total_relief
    for side, (sign, active, cores, apex, source, relief, feature_mode) in side_data.items():
        radii = np.asarray(source["carrier_radii"])
        cx, cy, anchor_wall = source["source_pole"]
        if wall != anchor_wall:
            raise CageError("Cage wall differs from its shared calibration")
        cx = abs(cx)
        projection = source["source_tip_projection"]
        height = float(max(0, relief.max()))
        # A reviewed source may have an areolar indentation at its frontmost
        # vertex. Reserve that signed relief on the entire analytic carrier;
        # discarding the negative part would shorten the final restored shape.
        reserve = float(relief[apex])
        target_radii = np.array([radii[0]*scale, radii[1]*scale,
                                 projection*scale-reserve+radius_adjustments[side]])
        target_cx = max(cx, target_radii[0]+.006*frame[0])
        target_cy = cy-.012*frame[1]*(scale-1)
        indices = np.flatnonzero(active)
        points = carrier[indices]
        q = np.column_stack(((sign*points[:, 0]-cx)/radii[0], (points[:, 1]-cy)/radii[1],
                             (wall-points[:, 2])/radii[2]))
        unit = q/np.maximum(np.linalg.norm(q, axis=1)[:, None], 1e-12)
        target = np.column_stack((sign*(target_cx+target_radii[0]*unit[:, 0]),
                                  target_cy+target_radii[1]*unit[:, 1], wall-target_radii[2]*unit[:, 2]))
        t = np.clip((q[:, 2]-.12)/.38, 0, 1)
        weights = t*t*(3-2*t)*np.clip((1.75-np.linalg.norm(q[:, :2], axis=1))/.5, 0, 1)
        attachment = _weights(mesh["attachment_weights"], members)
        weights *= attachment[indices]
        data_weights[indices] = 30*weights
        target_displacement[indices] = target-points
        anchors[apex] = np.array([sign*target_cx, target_cy, wall-target_radii[2]])-carrier[apex]
        reports[side] = {"pivot": [float(sign*cx), float(cy), wall],
                         "base_projection": projection, "lod_input_projection": wall-float(grouped[apex, 2]),
                         "target_projection": projection*scale, "apex_vertex": int(first[apex]),
                         "source_cage_apex_vertex": source["source_apex_vertex"],
                         "base_apex_position": grouped[apex].tolist(), "source_radii": radii.tolist(),
                         "target_radii": target_radii.tolist(),
                         "target_center": [float(sign*target_cx), float(target_cy), wall],
                         "carrier_relief_reserve": reserve,
                         "carrier_radius_adjustment": radius_adjustments[side],
                         "feature_mode": feature_mode, "source_feature_height": height}
    neighbors = [set() for _ in grouped]
    for triangle in triangles:
        for a, b in zip(triangle, np.roll(triangle, -1)):
            ga, gb = int(inverse[a]), int(inverse[b])
            if ga != gb:
                neighbors[ga].add(gb)
                neighbors[gb].add(ga)
    rows, columns, values = [], [], []
    for i, adjacent in enumerate(neighbors):
        rows.append(i); columns.append(i); values.append(1.)
        for j in sorted(adjacent):
            rows.append(i); columns.append(j); values.append(-1/len(adjacent))
    laplacian = coo_matrix((values, (rows, columns)), shape=(len(grouped), len(grouped))).tocsr()
    matrix = (diags(data_weights+.03)+biharmonic*(laplacian.T@laplacian)).tocsr()
    if harmonic:
        # Positive graph energy carries compatible torso displacement into the
        # lower attachment instead of allowing a biharmonic overshoot into it.
        matrix = (matrix+harmonic*(diags([len(n) for n in neighbors])@laplacian)).tocsr()
    known = np.array(sorted(set(np.flatnonzero(~active_all)) | set(anchors)), dtype=int)
    unknown = np.array(sorted(set(np.flatnonzero(active_all))-set(anchors)), dtype=int)
    known_values = np.zeros((len(known), 3))
    for i, group in enumerate(known):
        if group in anchors:
            known_values[i] = anchors[group]
    result = carrier.copy()
    if len(unknown):
        solve = factorized(matrix[unknown][:, unknown].tocsc())
        for axis in range(3):
            rhs = ((data_weights*target_displacement[:, axis])[unknown]
                   - matrix[unknown][:, known]@known_values[:, axis])
            result[unknown, axis] += solve(rhs)
    result[known] += known_values
    carrier_result = result.copy()
    vertices = result[inverse]
    face_normals = np.cross(vertices[triangles[:, 1]]-vertices[triangles[:, 0]],
                            vertices[triangles[:, 2]]-vertices[triangles[:, 0]])
    normals = np.zeros_like(result)
    for corner in range(3):
        np.add.at(normals, inverse[triangles[:, corner]], face_normals)
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-30)
    projection_errors = {}
    for side, (sign, active, cores, apex, source, relief, feature_mode) in side_data.items():
        report = reports[side]
        feature = np.flatnonzero((relief > 1e-8) & active & (normals[:, 2] < -.2))
        feature_scale = 1.0
        if len(feature):
            required = report["target_projection"]-(wall-result[feature, 2])
            feature_scale = float(np.min(required/(-normals[feature, 2]*relief[feature])))
            if float(relief[apex]) <= 1e-10:
                feature_scale = min(1., feature_scale)
            if not .7 < feature_scale < 1.5:
                raise CageError(side+" feature/projection calibration exceeds its reviewed range", {"regions": reports})
            patch = np.flatnonzero((abs(relief) > 1e-10) & active)
            result[patch] += normals[patch]*relief[patch, None]*feature_scale
        achieved = wall-float(result[cores, 2].min())
        if not np.isclose(achieved, report["target_projection"], atol=1e-9, rtol=1e-9):
            projection_errors[side] = report["target_projection"]-achieved
        metric = np.flatnonzero(active & (data_weights >= 15))
        source_radii = np.asarray(source["carrier_radii"])
        pole = source["source_pole"]
        source_q = np.column_stack(((sign*grouped[:, 0]-abs(pole[0]))/source_radii[0],
                                    (grouped[:, 1]-pole[1])/source_radii[1],
                                    (wall-grouped[:, 2])/source_radii[2]))
        physical_region = (active & (np.linalg.norm(source_q[:, :2], axis=1) <= 1.75)
                           & (source_q[:, 2] > -.5))
        cap_faces = triangles[np.any(physical_region[inverse[triangles]], axis=1)]
        old_dimensions, _ = _front_dimensions(grouped[inverse], cap_faces, wall, report["base_projection"])
        dimensions, surface_samples = _front_dimensions(result[inverse], cap_faces, wall, achieved)
        radii = np.asarray(report["target_radii"])
        center = report["target_center"]
        q = np.column_stack(((sign*carrier_result[metric, 0]-abs(center[0]))/radii[0],
                             (carrier_result[metric, 1]-center[1])/radii[1],
                             (wall-carrier_result[metric, 2])/radii[2]))
        residual = abs(np.linalg.norm(q, axis=1)-1) if len(metric) else np.zeros(1)
        rms = float(np.sqrt(np.mean(residual**2)))
        if rms > .18:
            raise CageError(side+" rounded contour deviates from its ellipsoid objective", {"regions": reports})
        report.update({"achieved_projection": achieved, "achieved_scale": achieved/report["base_projection"],
                       "apex_position": result[apex].tolist(), "metric_vertex_count": surface_samples,
                       "metric_face_count": int(len(cap_faces)),
                       "metric_definition": "shared LOD0 physical region, surface clipped at 15% projection",
                       "contour_sample_count": int(len(metric)),
                       "base_width": float(old_dimensions[0]), "base_height": float(old_dimensions[1]),
                       "measured_width": float(dimensions[0]), "measured_height": float(dimensions[1]),
                       "measured_width_scale": float(dimensions[0]/old_dimensions[0]) if old_dimensions[0] else None,
                       "measured_height_scale": float(dimensions[1]/old_dimensions[1]) if old_dimensions[1] else None,
                       "depth_to_width": achieved/float(dimensions[0]) if dimensions[0] else None,
                       "depth_to_height": achieved/float(dimensions[1]) if dimensions[1] else None,
                       "envelope_volume_ratio": float(np.prod(dimensions[:2]/old_dimensions[:2]))*(achieved/report["base_projection"])
                           if min(old_dimensions[:2]) > 0 else None,
                       "feature_restore_scale": feature_scale,
                       "target_feature_height": report["source_feature_height"]*feature_scale,
                       "ellipsoid_rms_radial_error": rms})
    if projection_errors:
        # Source-normal relief and the carrier's new normal need not be parallel.
        # Refine whole-carrier Z radii, never a single vertex or the requested
        # projection. Each solve remains bound to the same ellipsoid objective.
        if _calibration_iteration >= 6:
            raise CageError("Rounded cage carrier could not calibrate the full requested projection",
                            {"regions": reports, "projection_errors": projection_errors})
        adjusted = {side: radius_adjustments[side]+projection_errors.get(side, 0.)
                    for side in ("left", "right")}
        if any(abs(value) > .03*frame[2] for value in adjusted.values()):
            raise CageError("Rounded cage carrier calibration exceeds reviewed relief range", {"regions": reports})
        return apply_cage(mesh, percent, wall, basis, _radius_adjustments=adjusted,
                          _calibration_iteration=_calibration_iteration+1, regularizer=regularizer)
    final = result[inverse]
    # Sample the authoring path without confusing a smooth normal turn with a
    # reversal. The independent final intersection proof remains mandatory.
    affected = np.any(active_all[inverse[triangles]], axis=1)
    faces = triangles[affected]
    base = grouped[inverse]
    previous = np.cross(base[faces[:, 1]]-base[faces[:, 0]], base[faces[:, 2]]-base[faces[:, 0]])
    minimum_cosine, minimum_area_ratio = 1.0, 1.0
    for step in range(1, 65):
        sample = base+(final-base)*(step/64)
        current = np.cross(sample[faces[:, 1]]-sample[faces[:, 0]], sample[faces[:, 2]]-sample[faces[:, 0]])
        a, b = np.linalg.norm(previous, axis=1), np.linalg.norm(current, axis=1)
        valid = a > 2e-12
        if np.any(valid):
            cosine = np.einsum("ij,ij->i", previous[valid], current[valid])/np.maximum(a[valid]*b[valid], 1e-300)
            minimum_cosine = min(minimum_cosine, float(cosine.min()))
            minimum_area_ratio = min(minimum_area_ratio, float((b[valid]/a[valid]).min()))
            if np.any(b[valid] <= 2e-12) or np.any(cosine <= 0):
                raise CageError("Cage authoring path collapsed or abruptly turned a face", {"regions": reports})
        previous = current
    positions = [list(point) for point in mesh["positions"]]
    for i, group in enumerate(inverse):
        if active_all[group] and not np.array_equal(final[i], base[i]):
            positions[i] = final[i].tolist()
    return {"positions": positions, "report": {"regions": reports, "cage_version": VERSION,
            "transition_regularizer": {"biharmonic": biharmonic, "harmonic": harmonic},
            "carrier_projection_calibration": {"iterations": _calibration_iteration,
                                                 "radius_adjustments": dict(radius_adjustments),
                                                 "requested_projection_unchanged": True},
            "sampled_flow": {"algorithm": "sampled_cage_authoring_path", "steps": 64,
                             "minimum_step_normal_cosine": minimum_cosine,
                             "minimum_step_area_ratio": minimum_area_ratio, "new_collapsed_samples": 0,
                             "scope": "sampled authoring path, not a global diffeomorphism proof"}}}
