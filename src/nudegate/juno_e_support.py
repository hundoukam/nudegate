"""Restore Juno E's source torso/anatomy while retaining its reviewed limb pose.

This is an explicit offline pose correction. The shoulder patch may restore
proximal upper-arm rows with majority arm weights; elbow/wrist skin, hands,
feet, collar and every point outside the source-derived field stay unchanged.
It neither sculpts the donor nor edits its original skin or triangles.
"""
from __future__ import annotations

import numpy as np

from .donor_body import _limb_root, normalized_deform_weights


PROFILE = 'juno-e-original-support-proximal-axilla-v1'
SOURCE_SHA256 = 'c1cd05fab1e7f7073392bf3883f613bd6ef4dc0817929a0839723555ade0765d'
BASELINE_POSE_SHA256 = '5ca55ad28db1c3ad2079f98924bb8264f54ac5ca0d99670bbc50a116254c6976'
SCALE = 1.165


def _smooth(value):
    value = np.clip(value, 0., 1.)
    return value * value * (3. - 2. * value)


def _descends(name, roots, bones):
    seen = set()
    while name and name not in seen:
        if name in roots:
            return True
        seen.add(name)
        name = bones.get(name, {}).get('parent')
    return False


def _point(bones, name, end='head'):
    return np.asarray(bones[name]['posed_' + end + '_world'], float)[[0, 2, 1]] * SCALE


def _distance_field(source, support, inner, fade):
    from scipy.spatial import cKDTree
    if not support.any() or not np.isfinite([inner, fade]).all() or inner < 0 or fade <= 0:
        raise ValueError('Invalid source support or distance fade')
    distances = cKDTree(source[support]).query(source)[0]
    return 1. - _smooth((distances - inner) / fade)


def _restore_positions(source, previous, protection):
    """Keep both constant regions bit exact rather than recomputing zero moves."""
    if (source.shape != previous.shape or source.ndim != 2 or source.shape[1] != 3
            or protection.shape != (len(source),) or not np.isfinite(source).all()
            or not np.isfinite(previous).all() or not np.isfinite(protection).all()
            or np.any(protection < 0) or np.any(protection > 1)):
        raise ValueError('Invalid source restoration coordinates or field')
    active = protection > 0
    full = protection == 1
    corrected = previous.copy()
    corrected[active] = source[active] + (previous - source)[active] * (1. - protection[active, None])
    corrected[full] = source[full]
    return corrected


def _proximal_axis_gate(axial_fraction, breast_mass):
    """Keep real breast geometry, while a weak paint tail follows arm posing."""
    axial_gate = 1. - _smooth((np.asarray(axial_fraction) - .25) / .25)
    breast_gate = _smooth((np.asarray(breast_mass) - .25) / .25)
    return 1. - (1. - axial_gate) * (1. - breast_gate)


def local_neck_cut(native):
    """Flatten only the low central neck rim, preserving the outer arm cut.

    The original fixed curvature raised this wider donor's lateral rim above
    parts of the sloping native collar. Place its base half one native collar
    height-span below the lowest collar sample. Radius limits come from that
    same collar; the original cut is bit exact beyond the outer limit.
    """
    from .donor_body import native_collar, _cut_height
    collar = native['positions'][native_collar(native)]
    radius = float(np.max(abs(collar[:, 0])))
    low, high = float(collar[:, 1].min()), float(collar[:, 1].max())
    if not .04 < radius < .08 or not .03 < high - low < .08:
        raise ValueError('E local neck cut requires the reviewed sloping native collar')
    base = low - .5 * (high - low)
    inner, outer = 1.75 * radius, 2.75 * radius

    def cut_height(x, cut):
        x = np.asarray(x, float)
        central = cut + .5 * x * x
        original = _cut_height(x, 1.52)
        fraction = _smooth((abs(x) - inner) / (outer - inner))
        mixed = central + (original - central) * fraction
        # Clamped constant regions are exact copies, including floating bits.
        return np.where(fraction == 1., original, np.where(fraction == 0., central, mixed))

    report = {'native_collar_min_y_m': low, 'native_collar_max_y_m': high,
        'native_collar_half_width_m': radius, 'central_base_y_m': base,
        'central_base_formula': 'native minimum collar Y minus half its vertical span',
        'central_curvature': .5, 'central_full_half_width_m': inner,
        'original_cut_exact_from_abs_x_m': outer,
        'original_outer_cut_base_y_m': 1.52,
        'blend': 'C1 smoothstep between source-independent native collar radius multiples 1.75 and 2.75',
        'scope': 'local head clipping and neck bridge only; original retained donor positions unchanged'}
    return cut_height, base, report


def validate_source(metadata):
    if (metadata.get('id') != 'juno_e' or metadata.get('key_overrides') != {'Chubby': 1}
            or metadata.get('npz_sha256') != SOURCE_SHA256
            or metadata['vertex_group_validation']['active_vertex_group_rigs'] != ['G9_Rig']):
        raise ValueError('Expected the fingerprinted original Juno E Chubby=1 capture')
    rigs = [rig for rig in metadata['rigs'] if rig['name'] == 'G9_Rig']
    if len(rigs) != 1 or len(rigs[0]['bones']) != 693:
        raise ValueError('Juno E active source rig changed')
    bones = {bone['name']: bone for bone in rigs[0]['bones']}
    expected = ['DEF-spine'] + ['DEF-spine.%03d' % number for number in range(1, 8)]
    if sorted(name for name in bones if name.startswith('DEF-spine')) != sorted(expected):
        raise ValueError('Juno E requires its original eight-spine G9 hierarchy')
    parents = {'l_breast': 'DEF-spine.003', 'r_breast': 'DEF-spine.003',
        'l_breast2': 'l_breast', 'r_breast2': 'r_breast',
        'DEF-shoulder.L': 'ORG-shoulder.L', 'DEF-shoulder.R': 'ORG-shoulder.R',
        'genitals': 'DEF-spine', 'genit.front': 'genitals', 'vagina': 'genit.front',
        'anus_01': 'genitals', 'anus_02': 'anus_01', 'DEF-spine.005': 'DEF-spine.004'}
    for name, parent in parents.items():
        if bones.get(name, {}).get('parent') != parent or not bones[name]['deform']:
            raise ValueError('Juno E reviewed source-support hierarchy changed: ' + name)
    return bones


def restore_original_support(posed, arrays, metadata):
    """Return a separate, topology-preserving candidate and explicit guards.

    Geometry acceptance still requires independent full surface/ancestry audits.
    No contact pairs enter this field, and no safety result is inferred from it.
    """
    validate_source(metadata)
    weights, names, bones, normalization = normalized_deform_weights(arrays, metadata)
    source = np.asarray(arrays['positions'], float)[:, [0, 2, 1]] * SCALE
    previous = posed['positions']
    if (not np.array_equal(posed['scaled_source_positions'], source)
            or not np.array_equal(posed['triangles'], arrays['triangles'][:, [0, 2, 1]])
            or not np.array_equal(posed['source_vertex_ids'], np.arange(len(source)))):
        raise ValueError('Juno E pose reference or source vertex/triangle identity changed')
    if len(source) != 40256 or len(posed['triangles']) != 80308:
        raise ValueError('Juno E original source geometry count differs')

    def mass(predicate):
        columns = [index for index, name in enumerate(names) if predicate(name)]
        return weights[:, columns].sum(1)

    limbs = {name: _limb_root(name, bones) for name in names}
    arm_mass = mass(lambda name: limbs[name] is not None and limbs[name][0] in ('upper_arm', 'forearm', 'hand'))
    distal_arm_mass = mass(lambda name: limbs[name] is not None and limbs[name][0] in ('forearm', 'hand'))
    distal = mass(lambda name: limbs[name] is not None and limbs[name][0] in ('hand', 'foot', 'toe')) > 0
    breast_groups = [name for name in names if _descends(name, {'l_breast', 'r_breast'}, bones)]
    thorax_groups = [name for name in names if name in breast_groups
        or name in ('DEF-spine.003', 'DEF-shoulder.L', 'DEF-shoulder.R')]
    thorax_mass = mass(lambda name: name in thorax_groups)
    anatomy_groups = [name for name in names if _descends(name, {'genitals'}, bones)]
    anatomy_mass = mass(lambda name: name in anatomy_groups)
    breast_mass = mass(lambda name: name in breast_groups)
    thorax_support = thorax_mass >= .25
    anatomy_support = anatomy_mass > 1e-6
    shoulder_lengths = [float(np.linalg.norm(_point(bones, name, 'tail') - _point(bones, name)))
        for name in ('DEF-shoulder.L', 'DEF-shoulder.R')]
    anatomy_lengths = [float(np.linalg.norm(_point(bones, name, 'tail') - _point(bones, name)))
        for name in ('vagina', 'anus_01', 'anus_02')]
    shoulder_fade = float(np.mean(shoulder_lengths))
    anatomy_fade = float(np.mean(anatomy_lengths))
    if not .08 < shoulder_fade < .13 or not .015 < anatomy_fade < .04:
        raise ValueError('Juno E source-support dimensions differ from reviewed controls')
    anatomy_bounds = [source[anatomy_support].min(0), source[anatomy_support].max(0)]
    if max(abs(anatomy_bounds[0][0]), abs(anatomy_bounds[1][0])) > .1:
        raise ValueError('Juno E source anatomy support leaks outside central pelvis')

    torso = _distance_field(source, thorax_support, 0., shoulder_fade)
    neighborhoods = []
    endpoint_protection = np.zeros(len(source), bool)
    for side in ('L', 'R'):
        arm_points = [_point(bones, 'DEF-' + part + '.' + side) for part in ('upper_arm', 'forearm', 'hand')]
        a, elbow, wrist = arm_points
        direction = elbow - a
        axial_fraction = (source - a) @ direction / float(direction @ direction)
        side_mass = mass(lambda name: limbs[name] is not None and limbs[name][1] == side
            and limbs[name][0] in ('upper_arm', 'forearm', 'hand'))
        selected = side_mass > 0
        # Proximal shoulder crease is original donor geometry. The mask is zero
        # halfway along the source upper-arm axis, well before its elbow skin.
        # A large breast can extend beyond the shoulder's projected axis.
        # Only real breast-majority rows bypass the proximal-arm gate; tiny
        # positive breast tails on arm skin do not freeze the limb surface.
        torso[selected] *= _proximal_axis_gate(axial_fraction[selected], breast_mass[selected])
        for parts in (('upper_arm', 'forearm', 'hand'), ('thigh', 'shin', 'foot')):
            points = [_point(bones, 'DEF-' + part + '.' + side) for part in parts]
            radius = .25 * min(np.linalg.norm(points[1] - points[0]), np.linalg.norm(points[2] - points[1]))
            for label, point in zip(('mid', 'distal'), points[1:]):
                members = np.linalg.norm(source - point, axis=1) <= radius
                endpoint_protection |= members
                neighborhoods.append({'side': side, 'source_chain': list(parts), 'endpoint': label,
                    'source_joint': point.tolist(), 'radius_m': float(radius),
                    'source_vertex_ids': np.flatnonzero(members).tolist(), 'vertex_count': int(members.sum())})

    torso[endpoint_protection] = 0.
    pelvis = _distance_field(source, anatomy_support, .25 * anatomy_fade, anatomy_fade)
    protection = 1. - (1. - torso) * (1. - pelvis)
    # .005 is the G9 neck base. .004 is still chest and must not freeze axilla.
    neck = source[:, 1] >= _point(bones, 'DEF-spine.005')[1]
    fixed = distal | neck | endpoint_protection | (distal_arm_mass >= .5)
    protection[fixed] = 0.
    corrected = _restore_positions(source, previous, protection)
    difference = corrected - previous
    changed = np.any(corrected != previous, axis=1)
    full = protection == 1
    if not np.array_equal(corrected[fixed], previous[fixed]):
        raise ValueError('Juno E source restoration changed protected joint skin')
    if not np.array_equal(corrected[~(protection > 0)], previous[~(protection > 0)]):
        raise ValueError('Juno E source restoration changed outside geometry')
    dominant_breast = breast_mass >= .5
    if not np.array_equal(corrected[dominant_breast], source[dominant_breast]):
        raise ValueError('Juno E source restoration changed dominant authored breast tissue')
    for row in neighborhoods:
        ids = row['source_vertex_ids']
        row['positions_bit_equal_to_reviewed_v3'] = bool(np.array_equal(corrected[ids], previous[ids]))
        row['restoration_delta_max_m'] = float(np.linalg.norm(difference[ids], axis=1).max(initial=0))
    result = {key: value.copy() for key, value in posed.items()}
    result.update(positions=corrected, pose_displacement=corrected - source,
        source_torso_pose_protection=torso, source_pelvic_pose_protection=pelvis,
        source_pose_protection=protection, source_restoration_displacement=difference)
    report = {'profile': PROFILE, 'normalization': normalization,
        'method': 'original source semantic torso/anatomy support; source-distance C1 fade and proximal source-upper-arm-axis fade',
        'source_scale': SCALE, 'source_translation': [0., 0., 0.],
        'thoracic_group_names': thorax_groups, 'thoracic_mass_minimum': .25,
        'anatomical_group_names': anatomy_groups, 'anatomical_mass_minimum': 1e-6,
        'thoracic_support_vertices': int(thorax_support.sum()), 'anatomical_support_vertices': int(anatomy_support.sum()),
        'shoulder_control_lengths_m': shoulder_lengths, 'shoulder_distance_fade_m': shoulder_fade,
        'anatomy_control_lengths_m': anatomy_lengths, 'anatomy_full_source_margin_m': .25 * anatomy_fade,
        'anatomy_distance_fade_m': anatomy_fade, 'anatomy_source_bounds': [value.tolist() for value in anatomy_bounds],
        'source_upper_arm_axis_full_through_fraction': .25, 'source_upper_arm_axis_zero_from_fraction': .5,
        'dominant_breast_axis_gate_bypass_mass': .5, 'breast_axis_gate_bypass_fade_from_mass': .25,
        'changed_vertices': int(changed.sum()), 'maximum_restoration_towards_source_m': float(np.linalg.norm(difference, axis=1).max()),
        'rms_restoration_changed_m': float(np.sqrt(np.mean(np.sum(difference[changed] ** 2, axis=1)))),
        'changed_source_vertex_ids': np.flatnonzero(changed).tolist(),
        'full_source_restored_vertices': int(full.sum()), 'full_source_positions_bit_equal': bool(np.array_equal(corrected[full], source[full])),
        'proximal_arm_majority_rows_restored': int((changed & (arm_mass >= .5)).sum()),
        'proximal_arm_majority_restoration_max_m': float(np.linalg.norm(difference[arm_mass >= .5], axis=1).max(initial=0)),
        'arm_majority_exception_scope': 'proximal axilla/upper-arm source support only; actual endpoint neighborhoods and all hand/foot rows remain exact v3',
        'dominant_breast_positions_bit_equal_to_source': True,
        'positive_breast_tail_rows_differing_from_source': int(((breast_mass > 0) & np.any(corrected != source, axis=1)).sum()),
        'actual_joint_neighborhoods': neighborhoods,
        'hands_feet_neck_and_joint_neighborhoods_bit_equal_to_v3': True,
        'outside_field_bit_equal_to_v3': True, 'source_triangle_topology_changed': False,
        'source_skin_weights_changed': False, 'sculpt_changes': 0,
        'collision_pair_ids_used_to_define_field': False,
        'surface_acceptance': 'requires fresh independent full pose/prepared/serialized source comparisons',
        'game_animation_validation': 'unverified; reviewed v3 limb endpoint offsets are unchanged'}
    return result, report
