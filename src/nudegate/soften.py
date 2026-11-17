"""Masked surface relaxation and padding for reviewed offline body meshes."""
import math


def soften_surface(positions, triangles, weights, locked_vertices, *, passes=4,
                   strength=.45, reverse_strength=-.47, padding=0.0,
                   max_displacement=.018):
    """Taubin-style smoothing with welded UV splits and fixed attachments.

    The caller supplies the reviewed body-region mask. Only positions change;
    topology, UVs, rig, identity and material decisions stay outside this helper.
    Padding follows the relaxed geometric normal and is bounded with smoothing.
    """
    if not isinstance(passes, int) or isinstance(passes, bool) or not 1 <= passes <= 16:
        raise ValueError('Surface passes must be between 1 and 16')
    for value in (strength, reverse_strength, padding, max_displacement):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Surface parameters must be finite numbers')
    if not .1 <= strength <= .65 or not -.70 <= reverse_strength <= -.1:
        raise ValueError('Surface relaxation strength exceeds the authoring range')
    if not 0 <= padding <= .02 or not 0 < max_displacement <= .03:
        raise ValueError('Surface padding/displacement exceeds the authoring range')
    if not positions or len(weights) != len(positions):
        raise ValueError('Surface weights must match a nonempty mesh')
    points = []
    for point in positions:
        if len(point) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
            raise ValueError('Source positions must be finite three-dimensional vectors')
        points.append(list(point))
    if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or not 0 <= w <= 1 for w in weights):
        raise ValueError('Surface weights must be finite and within [0, 1]')
    locked = set()
    for i in locked_vertices:
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(points):
            raise ValueError('Invalid protected vertex index')
        locked.add(i)
    groups, group_for, members = {}, [], []
    for i, point in enumerate(points):
        key = tuple(round(v, 6) for v in point)
        if key not in groups:
            groups[key] = len(members)
            members.append([])
        g = groups[key]
        members[g].append(i)
        group_for.append(g)
    neighbors = [set() for _ in members]
    faces = []
    for triangle in triangles:
        if len(triangle) != 3 or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(points) for i in triangle):
            raise ValueError('Invalid surface triangle indices')
        face = [group_for[i] for i in triangle]
        faces.append(face)
        for a, b in zip(face, face[1:] + face[:1]):
            if a != b:
                neighbors[a].add(b)
                neighbors[b].add(a)
    if not faces:
        raise ValueError('Surface mesh has no triangles')
    effective_weights = []
    for indices in members:
        values = [weights[i] for i in indices]
        if max(values) - min(values) > 1e-6:
            raise ValueError('Coincident UV-split vertices require matching masks')
        effective_weights.append(0.0 if any(i in locked for i in indices) else min(values))
    original = [points[indices[0]][:] for indices in members]
    current = [point[:] for point in original]
    for _ in range(passes):
        for factor in (strength, reverse_strength):
            next_points = [point[:] for point in current]
            for g, adjacent in enumerate(neighbors):
                w = effective_weights[g]
                if not adjacent or w == 0:
                    continue
                for axis in range(3):
                    mean = math.fsum(current[n][axis] for n in sorted(adjacent)) / len(adjacent)
                    next_points[g][axis] += factor * w * (mean - current[g][axis])
            current = next_points
    normals = [[0.0, 0.0, 0.0] for _ in members]
    for a, b, c in faces:
        u = [current[b][k] - current[a][k] for k in range(3)]
        v = [current[c][k] - current[a][k] for k in range(3)]
        normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        for g in (a, b, c):
            for axis in range(3):
                normals[g][axis] += normal[axis]
    clamped = 0
    for g, point in enumerate(current):
        w = effective_weights[g]
        if w == 0:
            current[g] = original[g][:]
            continue
        magnitude = math.hypot(*normals[g])
        if magnitude > 0:
            point = [point[k] + normals[g][k] / magnitude * padding * w for k in range(3)]
        delta = [point[k] - original[g][k] for k in range(3)]
        distance = math.hypot(*delta)
        if not math.isfinite(distance):
            raise ValueError('Surface arithmetic is nonfinite')
        if distance > max_displacement:
            delta = [v * max_displacement / distance for v in delta]
            clamped += 1
        current[g] = [original[g][k] + delta[k] for k in range(3)]
    result = [point[:] for point in points]
    for g, indices in enumerate(members):
        # Preserve each original coordinate exactly where no change is allowed.
        if effective_weights[g] == 0:
            continue
        delta = [current[g][k] - original[g][k] for k in range(3)]
        for i in indices:
            result[i] = [points[i][k] + delta[k] for k in range(3)]
    def face_normal(vertices, triangle):
        a, b, c = (vertices[i] for i in triangle)
        u = [b[k] - a[k] for k in range(3)]
        v = [c[k] - a[k] for k in range(3)]
        return [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
    source_normals = [face_normal(points, triangle) for triangle in triangles]
    def unsafe_faces(candidate):
        bad = []
        for index, (triangle, before) in enumerate(zip(triangles, source_normals)):
            area = sum(v*v for v in before)
            if area < 1e-20:
                continue
            after = face_normal(candidate, triangle)
            if sum(a*b for a,b in zip(before,after)) <= 0 or sum(v*v for v in after) < area * .01:
                bad.append(index)
        return bad
    # Fine racial ridges and dense surface patches can tolerate much less
    # relaxation than the broad torso. Backtrack rather than accepting a fold.
    full = result
    blends = [1.0 for _ in members]
    for _ in range(20):
        bad = unsafe_faces(result)
        if not bad:
            break
        limited = {group_for[i] for face in bad for i in triangles[face]}
        for g in limited:
            blends[g] *= .5
        # A short feather avoids introducing an abrupt correction boundary.
        next_blends = blends[:]
        for g in limited:
            for other in neighbors[g]:
                next_blends[other] = min(next_blends[other], (1 + blends[g]) / 2)
        blends = next_blends
        result = [[p[k] + (q[k]-p[k])*blends[group_for[i]] for k in range(3)]
                  for i,(p,q) in enumerate(zip(points,full))]
    else:
        result, blends = [p[:] for p in points], [0.0 for _ in members]
    displacement = [math.dist(a, b) for a, b in zip(points, result)]
    return result, {'passes': passes, 'padding_metres': padding,
                    'moved_vertices': sum(d > 1e-12 for d in displacement),
                    'max_displacement_metres': max(displacement),
                    'minimum_surface_safety_blend': min(blends),
                    'locally_limited_groups': sum(b < 1 for b in blends),
                    'clamped_groups': clamped, 'protected_vertices_unchanged': all(result[i] == points[i] for i in locked)}
