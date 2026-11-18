"""Reviewed seven-spine Cinderella profile; no Juno calibration or repairs.

Only a uniform placement and source-weighted limb pose operations change the
donor. Native surfaces are subsequently lookup data, never a replacement mesh.
"""
from __future__ import annotations

import numpy as np

from .donor_body import normalized_deform_weights, rotation_between, fractional_rotation, native_collar
from .surface_intersections import geometry_fingerprint

OPTIONAL_UNCOMPRESSED_KEYS = ('Boba marcas bikini parche', 'Boobpress', 'thihhs')


def validate_optional_uncompressed(metadata, selected):
    """An optional study may release only the three measured wardrobe fields."""
    import copy
    if (metadata.get('id') != 'cinderella_optional_uncompressed'
            or metadata.get('source_sha256') != selected.get('source_sha256')
            or metadata.get('key_overrides') != {key: 0 for key in OPTIONAL_UNCOMPRESSED_KEYS}):
        raise ValueError('Optional Cinderella study requires only the measured wardrobe switches')
    expected = copy.deepcopy(selected['applied_shape_keys'])
    for key in OPTIONAL_UNCOMPRESSED_KEYS:
        expected[key]['value'], expected[key]['mute'] = 0., False
    if metadata['applied_shape_keys'] != expected:
        raise ValueError('Optional Cinderella study changed another selected authored setting')
    return {'kind': 'optional authored-key uncompressed study, not selected A',
            'only_key_changes': {key: 0 for key in OPTIONAL_UNCOMPRESSED_KEYS},
            'all_other_selected_settings_exact': True, 'source_saved': False}


def apply_pose_coherence(posed, parameters, source_sha256):
    """Apply an explicit, fingerprinted submillimeter central pose correction.

    The inner patch follows a single translation of the original sculpt,
    replacing varying small limb-weight offsets. A compact C1 blend joins the
    existing pose outside it; no source weight, normal or topology is edited.
    """
    if (parameters.get('schema_version') != 1 or parameters.get('source_npz_sha256') != source_sha256
            or parameters.get('source_pose_geometry_sha256') != geometry_fingerprint(posed['positions'], posed['triangles'])):
        raise ValueError('Cinderella pose corrective does not match the exact source/pose fingerprints')
    lo = np.asarray(parameters['inner_min'], dtype=np.float64)
    hi = np.asarray(parameters['inner_max'], dtype=np.float64)
    target = np.asarray(parameters['target_displacement'], dtype=np.float64)
    fade = parameters['fade_m']
    maximum = parameters['maximum_allowed_corrective_m']
    if (lo.shape != (3,) or hi.shape != (3,) or target.shape != (3,)
            or not np.isfinite([lo, hi, target]).all() or np.any(lo >= hi)
            or type(fade) not in (float, int) or not np.isfinite(fade) or not 0 < fade <= .01
            or type(maximum) not in (float, int) or not np.isfinite(maximum) or not 0 < maximum <= .001):
        raise ValueError('Invalid bounded local Cinderella pose correction')
    source = posed['scaled_source_positions']
    displacement = posed['positions'] - source
    distance = np.maximum(np.maximum(lo - source, source - hi), 0)
    q = np.clip(distance / fade, 0, 1)
    weight = np.prod(1 - q*q*(3 - 2*q), axis=1)
    delta = (target - displacement) * weight[:, None]
    length = np.linalg.norm(delta, axis=1)
    if length.max(initial=0) > maximum:
        raise ValueError('Cinderella local pose corrective exceeds its explicit displacement bound')
    changed = np.flatnonzero(length > 0)
    if any(np.any(posed['source_breast_influence_' + side][changed] > 0) for side in ('left', 'right')):
        raise ValueError('Central pelvic pose corrective reached source breast influences')
    result = dict(posed)
    result['positions'] = posed['positions'].copy()
    result['positions'][changed] += delta[changed]
    result['pose_displacement'] = result['positions'] - source
    result['pelvic_pose_corrective'] = delta
    return result, {'operation': parameters['operation'], 'maximum_corrective_m': float(length.max(initial=0)),
        'changed_source_vertex_ids': changed.tolist(), 'changed_vertices': len(changed),
        'source_patch_min': source[changed].min(axis=0).tolist() if len(changed) else None,
        'source_patch_max': source[changed].max(axis=0).tolist() if len(changed) else None,
        'source_weights_and_topology_unchanged': True, 'source_breast_influences_unchanged': True,
        'all_positions_outside_corrective_bit_exact': result['positions'][length == 0].tobytes() == posed['positions'][length == 0].tobytes(),
        'independent_surface_acceptance': 'required; parameter validation does not establish intersection safety'}


def active_bones(metadata):
    active = set(metadata['vertex_group_validation']['active_vertex_group_rigs'])
    bones = {bone['name']: bone for rig in metadata['rigs'] if rig['name'] in active for bone in rig['bones']}
    expected = ['DEF-spine'] + ['DEF-spine.%03d' % index for index in range(1, 7)]
    if sorted(name for name in bones if name.startswith('DEF-spine')) != sorted(expected):
        raise ValueError('Cinderella profile requires the reviewed seven-spine rig')
    return bones


def calibrate(arrays, metadata, native):
    """Ground plus shoulder/neck landmarks determine one uniform scale.

    The saved Rigify source uses DEF-spine.005 as the neck segment and .006 as
    the head. These are separately reviewed, rather than Juno's eight-spine map.
    """
    bones = active_bones(metadata)
    positions = np.asarray(arrays['positions'], dtype=np.float64)
    if positions.ndim != 2 or positions.shape[1] != 3 or not np.isfinite(positions).all():
        raise ValueError('Invalid captured Cinderella positions')
    source_ground = float(positions[:, 2].min())
    target_ground = float(native['positions'][:, 1].min())
    source_shoulder = np.mean([bones['DEF-upper_arm.' + side]['posed_head_world'] for side in ('L', 'R')], axis=0)[[0, 2, 1]]
    source_neck = np.asarray(bones['DEF-spine.005']['posed_head_world'])[[0, 2, 1]]
    target_shoulder = np.mean([native['bone_world']['Shoulder_' + side][:3, 3] for side in ('L', 'R')], axis=0)
    target_neck = native['bone_world']['Neck_M'][:3, 3]
    a = np.array([source_shoulder[1], source_neck[1]]) - source_ground
    b = np.array([target_shoulder[1], target_neck[1]]) - target_ground
    if np.any(a <= 0):
        raise ValueError('Source calibration landmarks are not above ground')
    scale = float(a @ b / (a @ a))
    if not .5 <= scale <= 1.5:
        raise ValueError('Cinderella landmark scale outside the reviewed range')
    translation = np.array([target_shoulder[0] - scale * source_shoulder[0],
                            target_ground - scale * source_ground,
                            np.mean([target_shoulder[2] - scale * source_shoulder[2],
                                     target_neck[2] - scale * source_neck[2]])])
    collar = native['positions'][native_collar(native)]
    native_neck_length = abs(float(native['bone_world']['Head_M'][1, 3] - target_neck[1]))
    if not .05 < native_neck_length < .2:
        raise ValueError('Unexpected native neck/head landmark interval')
    cut = min(float(target_neck[1] - .35 * native_neck_length), float(collar[:, 1].min() - .018))
    report = {'profile': 'cinderella-rigify-seven-spine-v1', 'uniform_scale': scale,
        'translation_bg3': translation.tolist(), 'axis_order': [0, 2, 1], 'reverse_winding': True,
        'source_ground_z': source_ground, 'native_ground_y': target_ground,
        'scale_method': 'least-squares shoulder and neck heights above exact mesh ground; one uniform scale',
        'source_neck_anchor': 'DEF-spine.005', 'native_neck_anchor': 'Neck_M',
        'source_shoulder': source_shoulder.tolist(), 'native_shoulder': target_shoulder.tolist(),
        'source_neck': source_neck.tolist(), 'native_neck': target_neck.tolist(),
        'placed_shoulder_residual': (source_shoulder * scale + translation - target_shoulder).tolist(),
        'placed_neck_residual': (source_neck * scale + translation - target_neck).tolist(),
        'head_cut_base_height': cut, 'neck_transition_band': .3 * native_neck_length,
        'neck_cut_method': 'native Neck_M minus 35 percent native neck/head interval, capped 18mm below native collar'}
    return report


def _source_limb(name, bones):
    seen = set()
    while name and name not in seen:
        seen.add(name)
        for part in ('hand', 'forearm', 'upper_arm', 'toe', 'foot', 'shin', 'thigh'):
            for side in ('L', 'R'):
                if name in ('DEF-' + part + '.' + side, 'DEF-' + part + '.' + side + '.001'):
                    return part, side
        name = bones.get(name, {}).get('parent')
    return None


def pose(arrays, metadata, native, calibration, *, align_hip_x=False,
         arm_fraction=1., leg_fraction=1.):
    """Apply the donor's evaluated deform weights to rigid limb corrections."""
    weights, names, bones, report = normalized_deform_weights(arrays, metadata)
    active_bones(metadata)
    scale = calibration['uniform_scale']
    translation = np.asarray(calibration['translation_bg3'])
    points = np.asarray(arrays['positions'], dtype=np.float64)[:, [0, 2, 1]] * scale + translation
    transforms = {}
    fixtures = []
    for side in ('L', 'R'):
        for chain, target in [(('upper_arm', 'forearm', 'hand'), ('Shoulder', 'Elbow', 'Wrist')),
                              (('thigh', 'shin', 'foot'), ('Hip', 'Knee', 'Ankle'))]:
            a, b, c = [np.asarray(bones['DEF-' + part + '.' + side]['posed_head_world'])[[0, 2, 1]] * scale + translation for part in chain]
            ta, tb, tc = [native['bone_world'][part + '_' + side][:3, 3] for part in target]
            fraction = leg_fraction if chain[0] == 'thigh' else arm_fraction
            upper = fractional_rotation(rotation_between(b - a, tb - ta), fraction)
            lower = fractional_rotation(rotation_between(c - b, tc - tb), fraction)
            offset = np.zeros(3)
            if chain[0] == 'thigh' and align_hip_x:
                offset[0] = ta[0] - a[0]
            pivot = a + offset
            middle = pivot + upper @ (b - a)
            transforms[(chain[0], side)] = upper, pivot - upper @ a
            transforms[(chain[1], side)] = lower, middle - lower @ b
            transforms[(chain[2], side)] = transforms[(chain[1], side)]
            if chain[2] == 'foot':
                transforms[('toe', side)] = transforms[('foot', side)]
            fixtures.append({'source_chain': list(chain), 'native_chain': list(target), 'side': side,
                'source_pivot': a.tolist(), 'native_pivot': ta.tolist(), 'corrected_pivot': pivot.tolist(),
                'pivot_translation': offset.tolist(), 'fraction': fraction,
                'upper_rotation': upper.tolist(), 'lower_rotation': lower.tolist()})
    displacement = np.zeros_like(points)
    influence = np.zeros(len(points))
    for index, name in enumerate(names):
        limb = _source_limb(name, bones)
        if limb in transforms:
            rotation, offset = transforms[limb]
            displacement += (points @ rotation.T + offset - points) * weights[:, index, None]
            influence += weights[:, index]
    posed = points + displacement
    fixed = influence == 0
    if not np.array_equal(posed[fixed], points[fixed]):
        raise ValueError('Pose operation changed protected donor core vertices')
    result = {'positions': posed, 'scaled_source_positions': points,
        'triangles': np.asarray(arrays['triangles'])[:, [0, 2, 1]].copy(),
        'source_vertex_ids': np.arange(len(points)), 'pose_displacement': displacement, 'limb_influence': influence}
    for side, suffix in [('left', 'L'), ('right', 'R')]:
        groups = [name for name in names if name in ('DEF-breast.' + suffix, 'DEF-breast.' + suffix + '.002', 'DEF-breast.' + suffix + '.003')]
        result['source_breast_influence_' + side] = weights[:, [names.index(name) for name in groups]].sum(axis=1)
    report.update(calibration=calibration, uniform_scale=scale, translation_bg3=translation.tolist(),
        axis_conversion='[x,z,y]', native_hip_lateral_alignment=align_hip_x,
        arm_rotation_fraction=arm_fraction, leg_rotation_fraction=leg_fraction,
        limb_fixtures=fixtures, torso_uninfluenced_vertices=int(fixed.sum()), torso_uninfluenced_max_error=0.,
        pose_changed_vertices=int(np.count_nonzero(np.linalg.norm(displacement, axis=1) > 1e-12)),
        maximum_pose_displacement=float(np.linalg.norm(displacement, axis=1).max()))
    return result, weights, names, bones, report


def map_weights(weights, names, bones, native_names):
    """Map the independently reviewed seven-spine Rigify anatomy by name."""
    anchors = {'DEF-spine': 'Root_M', 'DEF-spine.001': 'Spine1_M', 'DEF-spine.002': 'Spine2_M',
               'DEF-spine.003': 'Chest_M', 'DEF-spine.004': 'Neck_M',
               'DEF-spine.005': 'Neck_M', 'DEF-spine.006': 'Head_M'}
    for side in ('L', 'R'):
        for source, target in [('shoulder', 'Scapula'), ('upper_arm', 'Shoulder'), ('forearm', 'Elbow'),
                               ('hand', 'Wrist'), ('thigh', 'Hip'), ('shin', 'Knee'), ('foot', 'Ankle'), ('toe', 'Toes')]:
            for suffix in ('', '.001'):
                anchors['DEF-' + source + '.' + side + suffix] = target + '_' + side
        for source in ('pelvis', 'Ass'):
            anchors['DEF-' + source + '.' + side] = 'Root_M'
        for suffix in ('', '.002', '.003'):
            anchors['DEF-breast.' + side + suffix] = 'Chest_M'
        for source, target in [('f_index', 'IndexFinger'), ('f_middle', 'MiddleFinger'),
                               ('f_ring', 'RingFinger'), ('f_pinky', 'PinkyFinger'), ('thumb', 'ThumbFinger')]:
            for number in range(1, 4):
                anchors['DEF-' + source + '.%02d.' % number + side] = target + str(number) + '_' + side
        for number in range(1, 5):
            anchors['DEF-palm.%02d.' % number + side] = ('RingFinger0_' if number == 3 else 'PinkyFinger0_' if number == 4 else 'Wrist_') + side
    mapped = np.zeros((len(weights), len(native_names)))
    resolved = {}
    for column, name in enumerate(names):
        if not np.any(weights[:, column] > 0):
            continue
        current = name
        seen = set()
        while current not in anchors:
            if not current or current in seen or current not in bones:
                raise ValueError('Unmapped positive Cinderella deform group: ' + name)
            seen.add(current)
            current = bones[current]['parent']
        target = anchors[current]
        if target not in native_names:
            raise ValueError('Missing native joint for Cinderella: ' + target)
        mapped[:, native_names.index(target)] += weights[:, column]
        resolved[name] = {'anchor': current, 'target': target, 'direct': current == name}
    if not np.allclose(mapped.sum(axis=1), 1, atol=1e-12):
        raise ValueError('Cinderella skin mapping lost normalized mass')
    return mapped, {'profile': 'cinderella-rigify-seven-spine-v1', 'semantic_anchors': anchors,
                    'resolved_positive_groups': resolved, 'unknown_positive_groups': []}
