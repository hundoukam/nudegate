"""Additive body studies; approved original profiles remain separate inputs."""
import copy
import math

from .body_shapes import smooth, band, author_masks


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + ' must be a finite number')
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(label + ' must be a finite number')
    return value


def _points(values, label):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError(label + ' must be a nonempty position list')
    for point in values:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            raise ValueError(label + ' must contain three-dimensional vectors')
        for value in point:
            _finite_number(value, label)
    return values


def _mesh_inputs(mesh, positions, *, triangles_required=False):
    if not isinstance(mesh, dict):
        raise ValueError('Expected a mesh object')
    source = _points(mesh.get('positions'), 'Source positions')
    _points(positions, 'Target positions')
    if len(source) != len(positions):
        raise ValueError('Target positions must match source vertex count')
    indices = mesh.get('locked_vertices', [])
    if not isinstance(indices, (list, tuple, set)) or any(type(i) is not int or not 0 <= i < len(source) for i in indices):
        raise ValueError('Invalid protected vertex indices')
    locked = set(indices)
    if any(list(positions[i]) != list(source[i]) for i in locked):
        raise ValueError('Protected input positions differ from the source')
    groups = {}
    for i, point in enumerate(source):
        key = tuple(point)
        if key in groups and list(positions[i]) != list(positions[groups[key]]):
            raise ValueError('Coincident source vertices require matching target positions')
        groups.setdefault(key, i)
    triangles = mesh.get('triangles', [])
    if triangles_required and not triangles:
        raise ValueError('Expected source triangles')
    if not isinstance(triangles, (list, tuple)) or any(
        not isinstance(tri, (list, tuple)) or len(tri) != 3
        or any(type(i) is not int or not 0 <= i < len(source) for i in tri) for tri in triangles
    ):
        raise ValueError('Invalid source triangle indices')
    return source, locked


def author_expansion_masks(mesh, frame=None, *, preserve_back_ridges=False):
    """Broader silhouette fields with opt-in reviewed tiefling ridge protection.

    The caller enables this only for the reviewed tiefling families. It removes
    smoothing/padding from the upper central back ridge, with a smooth spatial
    feather. Body proportion masks and all legacy/default behavior stay intact.
    """
    if type(preserve_back_ridges) is not bool:
        raise ValueError('preserve_back_ridges must be a boolean')
    masks, report = author_masks(mesh.positions,mesh.triangles,mesh.topology_id,
                                 frame=frame,pelvis_front_top=1.03,seam_distance=.012)
    frame = frame or [1,1,1]
    coordinates = [[p[k]/frame[k] for k in range(3)] for p in mesh.positions]
    raw = {}
    for name,envelope in (('waist',(.98,1.08,1.19,1.265)),
                          ('hips',(.72,.86,1.04,1.20)),
                          ('thighs',(.35,.54,.78,.96))):
        raw[name] = [band(y,*envelope)*(1-smooth(.18,.28,abs(x))) for x,y,z in coordinates]
    chest = ('chest_left','chest_right')
    for i in range(len(coordinates)):
        feather = masks['attachment_weights'][i]
        chest_weight = sum(masks['regions'][n]['weights'][i] for n in chest)
        total = sum(raw[n][i] for n in raw)
        for name in raw:
            masks['regions'][name]['weights'][i] = raw[name][i]/(max(1,total)+1e-12)*feather*max(0,1-chest_weight)
    if preserve_back_ridges:
        protection = [band(y,1.28,1.31,1.41,1.45)
                      * (1-smooth(.095,.145,abs(x))) * smooth(.025,.065,z)
                      for x,y,z in coordinates]
        # Use the same source-coordinate weld precision as soften_surface.
        # Max protection keeps every member of a UV split equally protected,
        # including values straddling a mask feather within one welded group.
        keys = [tuple(round(v,6) for v in point) for point in mesh.positions]
        welded_protection = {}
        for key,value in zip(keys,protection):
            welded_protection[key] = max(welded_protection.get(key,0),value)
        protection = [welded_protection[key] for key in keys]
        masks['soft_weights'] = [weight*(1-preserve)
                                 for weight,preserve in zip(masks['soft_weights'],protection)]
        report['back_ridge_protection'] = {
            'enabled':True, 'version':'tiefling-upper-back-v1',
            'scope':'soft_weights only; source-space canonical coordinates',
            'height_envelope':[1.28,1.31,1.41,1.45],
            'absolute_x_feather':[.095,.145], 'rear_z_feather':[.025,.065],
            'fully_protected_vertices':sum(value==1 for value in protection),
            'feathered_vertices':sum(0<value<1 for value in protection),
            'uv_split_protection_welded':True,
        }
    return masks,report


def effective_profile(profile, *, strong=False):
    if not isinstance(profile, dict) or type(strong) is not bool:
        raise ValueError('Expected a profile object and boolean strong frame')
    result = copy.deepcopy(profile)
    settings = result.pop('strong_adjustments', {})
    allowed = {'hip_width', 'thigh_width', 'bust_width', 'bust_projection'}
    if not isinstance(settings, dict) or set(settings)-allowed:
        raise ValueError('Invalid strong-frame adjustment settings')
    for key in allowed:
        multiplier = _finite_number(settings.get(key, 1.0), 'Strong-frame '+key)
        if not .85 <= multiplier <= 1.35:
            raise ValueError('Strong-frame curve multiplier is outside its reviewed range')
    if strong:
        for name in ('hips_scale', 'thigh_scale', 'chest_scale'):
            vector = result.get(name)
            if not isinstance(vector, (list, tuple)) or len(vector) != 3:
                raise ValueError('Strong-frame scale must have three components: '+name)
            if any(not .5 <= _finite_number(value, name) <= 2 for value in vector):
                raise ValueError('Strong-frame base scale exceeds its reviewed range')
            result[name] = list(vector)
        for name, key in (('hips_scale','hip_width'), ('thigh_scale','thigh_width'), ('chest_scale','bust_width')):
            multiplier = settings.get(key, 1.0)
            result[name][0] *= multiplier
        result['chest_scale'][2] *= settings.get('bust_projection', 1.0)
        if any(not .5 <= value <= 2 for name in ('hips_scale', 'thigh_scale', 'chest_scale') for value in result[name]):
            raise ValueError('Effective strong-frame scale exceeds its reviewed range')
    result['max_shape_displacement'] = .30
    return result


def apply_body_details(mesh, positions, profile):
    """Sculpt broad belly mass or subtle abdominal definition in body space."""
    source, locked = _mesh_inputs(mesh, positions)
    if not isinstance(profile, dict):
        raise ValueError('Expected a body-detail profile object')
    settings = profile.get('body_details', {})
    if not isinstance(settings, dict) or set(settings)-{'belly', 'abs'}:
        raise ValueError('Invalid body-detail settings')
    belly = _finite_number(settings.get('belly', 0), 'Belly amplitude')
    abs_strength = _finite_number(settings.get('abs', 0), 'Abdominal amplitude')
    if not 0 <= belly <= .075 or not 0 <= abs_strength <= .008:
        raise ValueError('Body detail amplitude is outside its reviewed range')
    frame = mesh.get('frame', [1,1,1])
    if not isinstance(frame, (list, tuple)) or len(frame) != 3 or any(not .8 <= _finite_number(v, 'Body frame') <= 1.4 for v in frame):
        raise ValueError('Invalid reviewed body frame')
    feather = mesh.get('attachment_weights', [1]*len(source))
    if not isinstance(feather, (list, tuple)) or len(feather) != len(source) or any(not 0 <= _finite_number(w, 'Attachment weight') <= 1 for w in feather):
        raise ValueError('Attachment weights must match vertices and lie in [0, 1]')
    weld_weights = {}
    for point, weight in zip(source, feather):
        key = tuple(point)
        if key in weld_weights and weight != weld_weights[key]:
            raise ValueError('Coincident source vertices require matching attachment weights')
        weld_weights[key] = weight
    result = [list(p) for p in positions]
    for i, point in enumerate(source):
        if i in locked:
            continue
        x,y,z = [point[k]/frame[k] for k in range(3)]
        front = 1-smooth(-.085,-.025,z)
        if front == 0:
            continue
        belly_weight = math.exp(-.5*((x/.13)**2+((y-1.135)/.095)**2)) * band(y,.98,1.045,1.22,1.30)
        abdominal = 0.0
        for row in (1.255,1.205,1.155):
            for column in (-.040,.040):
                abdominal += math.exp(-.5*(((x-column)/.022)**2+((y-row)/.017)**2))
        abdominal *= band(y,1.115,1.145,1.270,1.295) * (1-smooth(.10,.15,abs(x)))
        result[i][2] -= (belly*belly_weight + abs_strength*abdominal) * front * feather[i] * frame[2]
    if any(result[i] != positions[i] for i in locked):
        raise ValueError('Body detail moved a protected attachment')
    return result, {'belly_amplitude_metres':belly,'abs_amplitude_metres':abs_strength,
                    'moved_vertices':sum(a!=b for a,b in zip(positions,result)),
                    'protected_vertices_unchanged':True}
