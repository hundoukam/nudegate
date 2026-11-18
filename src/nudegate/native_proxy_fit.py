"""Offline fitting of an unchanged native cloth topology to a donor surface.

Only the native patch and an optional disposable lookup mesh are transported.
The donor surface is read-only. Analytic sampled Jacobians and independent
surface checks do not establish global injectivity or runtime cloth behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import xml.etree.ElementTree as ET

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from .donor_body import closest_triangles, vertex_normals
from .donor_flow import CompactVelocityField, FlowResult
from .surface_intersections import SurfaceIntersectionChecker

VERSION = 'native-proxy-connected-surface-compact-flow-v1'


def anterior_pole_seeds(native_positions, donor_positions, left_support, right_support, *,
                        support_minimum=.05, side_threshold=.018, depth_fade_fraction=.75,
                        sternum_locked_fraction=.10, sternum_fade_fraction=.25):
    """Guide face selection using each donor's own authored anterior poles.

    These are query seeds only. They never replace the original native field
    controls or edit the donor. Gates use the original native patch dimensions.
    """
    arrays = [np.asarray(value, dtype=np.float64) for value in (native_positions, donor_positions)]
    if any(value.ndim != 2 or value.shape[1:] != (3,) or not len(value)
           or not np.isfinite(value).all() for value in arrays):
        raise ValueError('Pole coordinates must be finite nonempty N by 3 points')
    p, donor = arrays
    support_minimum = _finite_number(support_minimum, 'support_minimum')
    side_threshold = _finite_number(side_threshold, 'side_threshold')
    fractions = [_finite_number(value, name, positive=True) for value, name in
        ((depth_fade_fraction, 'depth_fade_fraction'), (sternum_locked_fraction, 'sternum_locked_fraction'),
         (sternum_fade_fraction, 'sternum_fade_fraction'))]
    if support_minimum < 0 or side_threshold < 0 or any(value > 1 for value in fractions):
        raise ValueError('Invalid anterior pole gate parameters')
    halfwidth, rear, depth = float(abs(p[:, 0]).max()), float(p[:, 2].max()), float(np.ptp(p[:, 2]))
    if halfwidth <= side_threshold or depth <= 0:
        raise ValueError('Native pole patch needs both lateral and anterior extent')
    depth_fade, locked, lateral_fade = fractions[0]*depth, fractions[1]*halfwidth, fractions[2]*halfwidth
    seeds, records = p.copy(), []
    def smooth(value):
        value = np.clip(value, 0, 1)
        return value*value*(3-2*value)
    for side, sign, support in [('left', 1, left_support), ('right', -1, right_support)]:
        support = np.asarray(support, dtype=np.float64)
        if support.shape != (len(donor),) or not np.isfinite(support).all() or np.any(support < 0):
            raise ValueError('Each authored side needs finite nonnegative donor support')
        original = np.flatnonzero(p[:, 0]*sign > side_threshold)
        targets = np.flatnonzero((support > support_minimum) & (donor[:, 0]*sign > side_threshold))
        if not len(original) or not len(targets):
            raise ValueError('Missing original native or authored donor pole on '+side)
        native_id = int(original[np.argmin(p[original, 2])])
        donor_id = int(targets[np.argmin(donor[targets, 2])])
        delta = donor[donor_id]-p[native_id]
        selected = np.flatnonzero(p[:, 0]*sign > 0)
        gate = smooth((rear-p[selected, 2])/depth_fade)*smooth((abs(p[selected, 0])-locked)/lateral_fade)
        seeds[selected] += delta*gate[:, None]
        records.append({'side': side, 'source_native_proxy_vertex_id': native_id,
            'donor_source_vertex_id': donor_id, 'native_anterior_pole': p[native_id].tolist(),
            'donor_anterior_pole': donor[donor_id].tolist(), 'seed_pole_delta': delta.tolist()})
    return seeds, {'native_patch_halfwidth_m': halfwidth, 'native_patch_rear_z_m': rear,
        'native_patch_depth_m': depth, 'depth_fade_m': depth_fade,
        'sternum_locked_halfwidth_m': locked, 'sternum_fade_m': lateral_fade,
        'pole_support_minimum': support_minimum, 'poles': records,
        'maximum_seed_offset_m': float(np.linalg.norm(seeds-p, axis=1).max()),
        'purpose': 'Face-selection seeds only; original native controls and donor coordinates stay unchanged'}


def _geometry(positions, triangles, name):
    p = np.asarray(positions)
    t = np.asarray(triangles)
    if p.dtype.kind not in 'iuf' or p.ndim != 2 or p.shape[1:] != (3,) or not len(p):
        raise ValueError(name + ' positions must be nonempty numeric N by 3')
    p = np.asarray(p, dtype=np.float64)
    if (not np.isfinite(p).all() or t.dtype.kind not in 'iu' or t.ndim != 2
            or t.shape[1:] != (3,) or not len(t) or np.any(t < 0) or np.any(t >= len(p))):
        raise ValueError(name + ' has invalid coordinates or triangle indices')
    t = np.asarray(t, dtype=np.int64)
    area = np.linalg.norm(np.cross(p[t[:, 1]]-p[t[:, 0]], p[t[:, 2]]-p[t[:, 0]]), axis=1)
    if np.any(area <= 1e-12):
        raise ValueError(name + ' contains a collapsed triangle')
    return p, t


def _finite_number(value, name, *, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(name + ' must be finite')
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(name + ' must be finite' + (' and positive' if positive else ''))
    return value


def _surface_proof(source, triangles, candidate, topology_id):
    checker = SurfaceIntersectionChecker(source, triangles, topology_id=topology_id)
    if checker.source_pairs or np.any(checker.source_area <= checker.area_tolerance):
        raise ValueError('Original native ' + topology_id + ' requires an intersection-free, uncollapsed source')
    proof = checker.check(candidate)
    if not proof['safe']:
        raise ValueError('Native ' + topology_id + ' fit introduces intersections or collapsed faces')
    return proof


@dataclass(frozen=True)
class NativeProxyFit:
    flow: FlowResult
    control_points: np.ndarray
    control_velocities: np.ndarray
    targets: np.ndarray
    target_source_face_ids: np.ndarray
    target_barycentrics: np.ndarray
    target_normal_agreement: np.ndarray
    source_component_labels: np.ndarray
    field_parameters: dict
    report: dict

    def field(self):
        return CompactVelocityField(self.control_points, self.control_velocities, **self.field_parameters)


def fit_native_proxy(native_positions, native_triangles, donor_positions, donor_triangles,
                     donor_breast_support, *, radius=.02, stabilizer=.05, neighbours=96,
                     normal_penalty=.0002, minimum_normal_agreement=.1, side_threshold=.018,
                     steps=64, moving_centres=False, time_sample_fraction=.5,
                     minimum_jacobian=.01, projection_seed_positions=None):
    """Target original native points at one existing connected donor skin surface.

    Candidate faces are the nearest ``neighbours`` triangle centroids, scored
    by exact point-to-triangle squared distance plus a normal penalty. This is
    a correspondence heuristic, not an exact all-face nearest-surface search.
    Optional projection seeds guide face selection only; the flow always acts
    on the unchanged original native controls. Donor coordinates never change.
    """
    p, t = _geometry(native_positions, native_triangles, 'Native proxy')
    donor, faces = _geometry(donor_positions, donor_triangles, 'Donor')
    support = np.asarray(donor_breast_support)
    if (support.shape != (len(donor),) or support.dtype.kind not in 'biuf'
            or not np.isfinite(support).all() or np.any(support < 0) or not np.any(support > 0)):
        raise ValueError('Donor breast support must have finite nonnegative mass on source vertices')
    if isinstance(neighbours, (bool, np.bool_)) or not isinstance(neighbours, (int, np.integer)) or neighbours < 1:
        raise ValueError('neighbours must be a positive integer')
    normal_penalty = _finite_number(normal_penalty, 'normal_penalty')
    minimum_normal_agreement = _finite_number(minimum_normal_agreement, 'minimum_normal_agreement')
    side_threshold = _finite_number(side_threshold, 'side_threshold')
    minimum_jacobian = _finite_number(minimum_jacobian, 'minimum_jacobian', positive=True)
    if normal_penalty < 0 or not -1 <= minimum_normal_agreement <= 1 or side_threshold < 0:
        raise ValueError('Invalid correspondence score or side parameters')
    if projection_seed_positions is None:
        seeds = p
    else:
        seeds = np.asarray(projection_seed_positions, dtype=np.float64)
        if seeds.shape != p.shape or not np.isfinite(seeds).all():
            raise ValueError('Projection seeds must be finite native N by 3 points')
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(len(donor),)*2)
    count, labels = connected_components(graph, directed=False)
    components = np.unique(labels[support > 0])
    if len(components) != 1:
        raise ValueError('Authored breast support spans disconnected donor islands')
    component = int(components[0])
    if np.count_nonzero(labels == component) != np.bincount(labels).max():
        raise ValueError('Authored breast support is not on the main connected donor skin')
    allowed = np.flatnonzero(np.all(labels[faces] == component, axis=1))
    tri = donor[faces[allowed]]
    centres = tri.mean(1)
    cross = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
    face_normal = cross/np.linalg.norm(cross, axis=1, keepdims=True)
    normals = vertex_normals(p, t)
    _, candidates = cKDTree(centres).query(seeds, k=min(int(neighbours), len(tri)))
    if candidates.ndim == 1:
        candidates = candidates[:, None]
    bary, squared = closest_triangles(seeds[:, None, :], tri[candidates])
    agreement = np.einsum('ij,ikj->ik', normals, face_normal[candidates])
    score = squared + normal_penalty*(1-agreement)
    wrong_side = (p[:, None, 0]*centres[candidates, 0] < 0) & (abs(p[:, None, 0]) > side_threshold)
    score = np.where(wrong_side | (agreement < minimum_normal_agreement), np.inf, score)
    if not np.isfinite(score.min(1)).all():
        raise ValueError('No same-side agreeing donor face for one or more native points')
    choice = np.argmin(score, axis=1)
    rows = np.arange(len(p))
    selected = candidates[rows, choice]
    selected_bary = bary[rows, choice]
    targets = np.einsum('ni,nij->nj', selected_bary, tri[selected])
    velocities = targets-p
    parameters = {'radius': radius, 'stabilizer': stabilizer, 'moving_centres': moving_centres}
    field = CompactVelocityField(p, velocities, **parameters)
    flow = field.flow(p, steps=steps, time_sample_fraction=time_sample_fraction)
    determinants = np.linalg.det(flow.jacobians)
    if not np.isfinite(determinants).all() or determinants.min() <= minimum_jacobian:
        raise ValueError('Proxy sampled analytic Jacobian is singular, folded or below its guard')
    proof = _surface_proof(p, t, flow.positions, 'cloth-proxy')
    report = {'algorithm': VERSION, 'source_body_components': int(count),
        'selected_original_body_component': component,
        'source_body_component_vertices': int(np.count_nonzero(labels == component)),
        'all_author_breast_vertices_on_selected_component': True,
        'all_proxy_targets_on_same_original_body_component': True,
        'projection_seeds_used': projection_seed_positions is not None,
        'projection_seed_maximum_offset_m': float(np.linalg.norm(seeds-p, axis=1).max()),
        'neighbours': int(neighbours), 'normal_penalty': normal_penalty,
        'minimum_required_normal_agreement': minimum_normal_agreement, 'side_threshold_m': side_threshold,
        'target_normal_agreement_minimum': float(agreement[rows, choice].min()),
        'maximum_control_displacement_m': float(np.linalg.norm(velocities, axis=1).max()),
        'maximum_proxy_displacement_m': float(np.linalg.norm(flow.positions-p, axis=1).max()),
        'minimum_proxy_jacobian_determinant': float(determinants.min()),
        'minimum_jacobian_guard': minimum_jacobian, 'flow_report': flow.report,
        'global_original_proxy_surface_proof': proof, 'passed': True,
        'scope': 'Offline sampled rest-shape fit; no global injectivity proof or runtime physics claim'}
    return NativeProxyFit(flow, p.copy(), velocities, targets, allowed[selected], selected_bary,
        agreement[rows, choice], labels, parameters, report)


def fit_disposable_lookup(fit, positions, triangles):
    """Sample exactly the proxy's field on a read-only native render lookup."""
    p, t = _geometry(positions, triangles, 'Native lookup')
    flow = fit.field().flow(p, steps=fit.flow.report['steps'],
        time_sample_fraction=fit.flow.report['time_sample_fraction'])
    determinant = np.linalg.det(flow.jacobians)
    if not np.isfinite(determinant).all() or determinant.min() <= fit.report['minimum_jacobian_guard']:
        raise ValueError('Lookup sampled analytic Jacobian is below its guard')
    return flow, _surface_proof(p, t, flow.positions, 'disposable-render-lookup')


def exact_surface_distances(query, positions, triangles, *, chunk_size=32):
    """Exact minimum over every supplied triangle, in memory-bounded chunks."""
    p, t = _geometry(positions, triangles, 'Distance surface')
    q = np.asarray(query, dtype=np.float64)
    if q.ndim != 2 or q.shape[1:] != (3,) or not np.isfinite(q).all():
        raise ValueError('Distance query must have finite N by 3 coordinates')
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
        raise ValueError('chunk_size must be a positive integer')
    result = np.empty(len(q))
    for start in range(0, len(q), chunk_size):
        end = min(start+chunk_size, len(q))
        _, distance = closest_triangles(q[start:end, None, :], p[t][None, :, :, :])
        result[start:end] = np.sqrt(distance.min(1))
    return result


def verify_only_position_arrays_changed(reference, authored, geometry_ids):
    """Compare complete native XML after excluding only named position text."""
    parser = lambda: ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    roots = [ET.parse(path, parser=parser()).getroot() for path in (reference, authored)]
    ns = {'c': 'http://www.collada.org/2005/11/COLLADASchema'}
    for root in roots:
        for geometry_id in geometry_ids:
            mesh = root.find("c:library_geometries/c:geometry[@id='%s']/c:mesh" % geometry_id, ns)
            if mesh is None:
                raise ValueError('Missing expected native geometry')
            source = mesh.find('c:vertices/c:input[@semantic="POSITION"]', ns).get('source')[1:]
            array = mesh.find("c:source[@id='%s']/c:float_array" % source, ns)
            if array is None:
                raise ValueError('Missing expected native position array')
            array.text = 'PERMITTED_POSITION_VALUES_ONLY'
    if ET.tostring(roots[0]) != ET.tostring(roots[1]):
        raise ValueError('Unrelated native XML, topology, UV, paint, skin or rig record changed')
    return True
