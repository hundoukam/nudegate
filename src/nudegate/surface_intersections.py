"""Compare a fixed triangle surface with its source using actual intersections.

Requires the project's NumPy authoring extra. Coordinates and tolerance are in
the caller's model units. UV splits are welded in the *source* for adjacency;
only contact on the corresponding shared feature is ignored. Faces sharing a
vertex are still tested for overlap elsewhere. Point-only contact is allowed.

The narrow phase intersects nonparallel triangle/plane intervals, and clips
coplanar triangles in 2D to distinguish positive-area overlap from contact.
This is a tolerance-based floating point checker, not an exact-arithmetic proof
or a collision/animation simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import itertools
import json
import math
from typing import Any, Sequence

import numpy as np


class SurfaceIntersectionError(ValueError):
    """An unsafe surface result, retaining its JSON-compatible report."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__(
            f"Surface has {report['introduced_intersection_count']} introduced "
            f"triangle intersections and {report['new_collapsed_faces']} new "
            "collapsed faces"
        )


def _positive(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite and positive")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def _positions(values: Sequence[Sequence[float]]) -> np.ndarray:
    try:
        result = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Positions must be finite XYZ coordinates") from exc
    if result.ndim != 2 or result.shape[1] != 3 or not len(result):
        raise ValueError("Positions must be a nonempty N by 3 array")
    if not np.isfinite(result).all():
        raise ValueError("Positions must be finite XYZ coordinates")
    return np.array(result, copy=True, order="C")


def _triangles(values: Sequence[Sequence[int]], vertex_count: int) -> np.ndarray:
    result = np.asarray(values)
    if result.ndim != 2 or result.shape[1] != 3 or not len(result):
        raise ValueError("Triangles must be a nonempty M by 3 array")
    if result.dtype.kind not in "iu" or result.dtype.kind == "b":
        raise ValueError("Triangle indices must be integers")
    if np.any(result < 0) or np.any(result >= vertex_count):
        raise ValueError("Triangle index outside position array")
    return np.array(result, dtype=np.int64, copy=True, order="C")


def _weld(positions: np.ndarray, tolerance: float) -> np.ndarray:
    """Deterministic distance-based components, including hash-cell boundaries."""
    parent = list(range(len(positions)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cells: dict[tuple[int, int, int], list[int]] = {}
    neighbors = tuple(itertools.product((-1, 0, 1), repeat=3))
    squared = tolerance * tolerance
    # Translation avoids unnecessarily huge cell indices for offset models.
    origin = positions.min(axis=0)
    for i, position in enumerate(positions):
        key = tuple(math.floor(float(v)) for v in (position - origin) / tolerance)
        for delta in neighbors:
            for j in cells.get(tuple(key[k] + delta[k] for k in range(3)), ()):
                difference = positions[j] - position
                if float(difference @ difference) <= squared:
                    a, b = find(i), find(j)
                    parent[max(a, b)] = min(a, b)
        cells.setdefault(key, []).append(i)
    return np.asarray([find(i) for i in range(len(positions))], dtype=np.int64)


@dataclass
class _Node:
    indices: np.ndarray | None
    left: int = -1
    right: int = -1


class _BVH:
    """A source partition reused and refitted for every candidate surface."""

    def __init__(self, triangles: np.ndarray, leaf_size: int = 8):
        self.nodes: list[_Node] = []
        centers = triangles.mean(axis=1)

        def build(indices: np.ndarray) -> int:
            if len(indices) <= leaf_size:
                node = _Node(indices)
            else:
                extent = np.ptp(centers[indices], axis=0)
                axis = int(np.argmax(extent))
                order = np.argsort(centers[indices, axis], kind="stable")
                middle = len(indices) // 2
                left = build(indices[order[:middle]])
                right = build(indices[order[middle:]])
                node = _Node(None, left, right)
            self.nodes.append(node)
            return len(self.nodes) - 1

        self.root = build(np.arange(len(triangles), dtype=np.int64))

    def pairs(self, triangles: np.ndarray, active: np.ndarray, epsilon: float) -> np.ndarray:
        mins, maxs = triangles.min(axis=1), triangles.max(axis=1)
        low = np.empty((len(self.nodes), 3))
        high = np.empty_like(low)
        enabled = np.empty(len(self.nodes), dtype=bool)
        for i, node in enumerate(self.nodes):
            if node.indices is not None:
                low[i] = mins[node.indices].min(axis=0)
                high[i] = maxs[node.indices].max(axis=0)
                enabled[i] = active[node.indices].any()
            else:
                low[i] = np.minimum(low[node.left], low[node.right])
                high[i] = np.maximum(high[node.left], high[node.right])
                enabled[i] = enabled[node.left] or enabled[node.right]
        stack = [(self.root, self.root)]
        batches = []
        while stack:
            a, b = stack.pop()
            if not (enabled[a] or enabled[b]):
                continue
            if np.any(low[a] > high[b] + epsilon) or np.any(low[b] > high[a] + epsilon):
                continue
            na, nb = self.nodes[a], self.nodes[b]
            if a == b and na.indices is None:
                stack.extend(((na.left, na.left), (na.left, na.right), (na.right, na.right)))
            elif na.indices is not None and nb.indices is not None:
                ia, ib = np.meshgrid(na.indices, nb.indices, indexing="ij")
                ia, ib = ia.ravel(), ib.ravel()
                keep = ia < ib if a == b else ia != ib
                keep &= active[ia] | active[ib]
                keep &= np.all(mins[ia] <= maxs[ib] + epsilon, axis=1)
                keep &= np.all(mins[ib] <= maxs[ia] + epsilon, axis=1)
                if keep.any():
                    batches.append(np.sort(np.stack((ia[keep], ib[keep]), axis=1), axis=1))
            elif nb.indices is not None or (na.indices is None and
                    float(np.max(high[a] - low[a])) >= float(np.max(high[b] - low[b]))):
                stack.extend(((na.left, b), (na.right, b)))
            else:
                stack.extend(((a, nb.left), (a, nb.right)))
        return np.concatenate(batches) if batches else np.empty((0, 2), dtype=np.int64)


def _plane_segment(triangle: np.ndarray, distances: np.ndarray, epsilon: float) -> list[np.ndarray]:
    points = [triangle[i] for i in range(3) if abs(float(distances[i])) <= epsilon]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        if (distances[i] < -epsilon and distances[j] > epsilon or
                distances[j] < -epsilon and distances[i] > epsilon):
            fraction = distances[i] / (distances[i] - distances[j])
            points.append(triangle[i] + fraction * (triangle[j] - triangle[i]))
    return points


def _cross2(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _coplanar_overlap(a: np.ndarray, b: np.ndarray, normal: np.ndarray, epsilon: float) -> bool:
    """Positive-area convex clipping; shared points/edges have zero area."""
    drop = int(np.argmax(np.abs(normal)))
    aa, bb = np.delete(a, drop, axis=1), np.delete(b, drop, axis=1)
    # Work near the origin to avoid cancellation in the polygon area sum.
    origin = aa[0].copy()
    aa, bb = aa - origin, bb - origin
    orientation = 1.0 if _cross2(bb[1] - bb[0], bb[2] - bb[0]) > 0 else -1.0
    polygon = list(aa)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        edge = bb[j] - bb[i]
        previous = polygon[-1] if polygon else None
        if previous is None:
            return False
        dp = orientation * _cross2(edge, previous - bb[i])
        clipped = []
        for current in polygon:
            dc = orientation * _cross2(edge, current - bb[i])
            # The exact half-space boundary avoids manufacturing area from a
            # tolerance-expanded shared edge. The final area has a tolerance.
            if (dc >= 0) != (dp >= 0):
                clipped.append(previous + (dp / (dp - dc)) * (current - previous))
            if dc >= 0:
                clipped.append(current)
            previous, dp = current, dc
        polygon = clipped
    if len(polygon) < 3:
        return False
    area = abs(sum(_cross2(polygon[i], polygon[(i + 1) % len(polygon)])
                   for i in range(len(polygon)))) * 0.5
    edge_scale = max(float(np.linalg.norm(t[j] - t[i]))
                     for t in (aa, bb) for i, j in ((0, 1), (1, 2), (2, 0)))
    # Projected area is <= true area, by at most sqrt(3) for this projection.
    return area > epsilon * max(edge_scale, epsilon)


def _on_segment(point: np.ndarray, a: np.ndarray, b: np.ndarray, epsilon: float) -> bool:
    direction = b - a
    squared = float(direction @ direction)
    if squared <= epsilon * epsilon:
        return float(np.linalg.norm(point - a)) <= epsilon
    fraction = float((point - a) @ direction) / squared
    if fraction < -epsilon / math.sqrt(squared) or fraction > 1 + epsilon / math.sqrt(squared):
        return False
    return float(np.linalg.norm(point - (a + fraction * direction))) <= epsilon


def _expected_shared_contact(a: np.ndarray, b: np.ndarray, wa: np.ndarray,
                             wb: np.ndarray, endpoints: tuple[np.ndarray, np.ndarray],
                             epsilon: float) -> bool:
    shared = []
    for i in range(3):
        for j in range(3):
            if wa[i] == wb[j] and float(np.linalg.norm(a[i] - b[j])) <= epsilon:
                p = (a[i] + b[j]) * 0.5
                if not any(float(np.linalg.norm(p - q)) <= epsilon for q in shared):
                    shared.append(p)
    if len(shared) < 2:
        return False
    return any(all(_on_segment(p, x, y, epsilon) for p in endpoints)
               for x, y in itertools.combinations(shared, 2))


def _exact_pair_intersects(a: np.ndarray, b: np.ndarray, wa: np.ndarray,
                           wb: np.ndarray, epsilon: float) -> bool:
    """Resolve rare ambiguous predicates using the exact input binary floats.

    In particular, a vertex within epsilon of a plane is not necessarily on
    it. Treating it as on-plane can both miss a shallow crossing and manufacture
    a shifted intersection segment for near-coplanar adjacent triangles.
    """
    aa = [[Fraction.from_float(float(v)) for v in point] for point in a]
    bb = [[Fraction.from_float(float(v)) for v in point] for point in b]

    def sub(x, y):
        return [i-j for i,j in zip(x,y)]

    def cross(x, y):
        return [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]

    def dot(x, y):
        return sum(i*j for i,j in zip(x,y))

    na = cross(sub(aa[1],aa[0]),sub(aa[2],aa[0]))
    nb = cross(sub(bb[1],bb[0]),sub(bb[2],bb[0]))
    da = [dot(nb,sub(point,bb[0])) for point in aa]
    db = [dot(na,sub(point,aa[0])) for point in bb]
    if (all(value>0 for value in da) or all(value<0 for value in da)
            or all(value>0 for value in db) or all(value<0 for value in db)):
        return False
    line = cross(na,nb)
    if not any(line):
        if any(da) or any(db):
            return False  # Parallel distinct planes, even at sub-epsilon gaps.
        # Exact coplanar convex clipping. Only positive area is an overlap;
        # point/edge contacts must not acquire area from expanded half-spaces.
        drop = max(range(3),key=lambda k:abs(na[k]))
        axes = [k for k in range(3) if k!=drop]
        pa = [[point[k] for k in axes] for point in aa]
        pb = [[point[k] for k in axes] for point in bb]

        def cross2(x,y):
            return x[0]*y[1]-x[1]*y[0]

        orientation = 1 if cross2(sub(pb[1],pb[0]),sub(pb[2],pb[0]))>0 else -1
        polygon = pa
        for i,j in ((0,1),(1,2),(2,0)):
            if not polygon:
                return False
            edge = sub(pb[j],pb[i])
            previous = polygon[-1]
            dp = orientation*cross2(edge,sub(previous,pb[i]))
            clipped = []
            for current in polygon:
                dc = orientation*cross2(edge,sub(current,pb[i]))
                if (dc>=0)!=(dp>=0):
                    fraction = dp/(dp-dc)
                    clipped.append([p+fraction*(q-p) for p,q in zip(previous,current)])
                if dc>=0:
                    clipped.append(current)
                previous,dp = current,dc
            polygon = clipped
        if len(polygon)<3:
            return False
        area = abs(sum(cross2(polygon[i],polygon[(i+1)%len(polygon)])
                       for i in range(len(polygon))))/2
        edge_scale = max(math.dist([float(v) for v in points[i]],
                                   [float(v) for v in points[j]])
                         for points in (pa,pb) for i,j in ((0,1),(1,2),(2,0)))
        return area > Fraction.from_float(epsilon)*Fraction.from_float(max(edge_scale,epsilon))

    def cut(triangle,distances):
        points = [point for point,distance in zip(triangle,distances) if distance==0]
        for i,j in ((0,1),(1,2),(2,0)):
            if distances[i]*distances[j]<0:
                fraction = distances[i]/(distances[i]-distances[j])
                points.append([p+fraction*(q-p) for p,q in zip(triangle[i],triangle[j])])
        return points

    pa,pb = cut(aa,da),cut(bb,db)
    if len(pa)<2 or len(pb)<2:
        return False
    axis = max(range(3),key=lambda k:abs(line[k]))
    low = max(min(p[axis] for p in pa),min(p[axis] for p in pb))
    high = min(max(p[axis] for p in pa),max(p[axis] for p in pb))
    if high<=low:
        return False
    p0,p1 = min(pa,key=lambda p:p[axis]),max(pa,key=lambda p:p[axis])
    endpoints = [[p+(value-p0[axis])/(p1[axis]-p0[axis])*(q-p)
                  for p,q in zip(p0,p1)] for value in (low,high)]
    delta = sub(endpoints[1],endpoints[0])
    if dot(delta,delta)<=Fraction.from_float(epsilon)**2:
        return False
    float_endpoints = tuple(np.asarray([float(v) for v in point]) for point in endpoints)
    return not _expected_shared_contact(a,b,wa,wb,float_endpoints,epsilon)


def _pair_hash(pairs: set[tuple[int, int]]) -> str:
    payload = json.dumps(sorted(pairs), separators=(",", ":")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _geometry_fingerprint(positions: np.ndarray, triangles: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(positions.astype("<f8", copy=False).tobytes(order="C"))
    digest.update(triangles.astype("<i8", copy=False).tobytes(order="C"))
    return digest.hexdigest()


def geometry_fingerprint(positions: Sequence[Sequence[float]],
                         triangles: Sequence[Sequence[int]]) -> str:
    """SHA-256 of ordered XYZ float64 LE bytes followed by int64 LE faces.

    Bind proof to coordinates parsed back from the authored DAE when the
    serializer may round numbers. Vertex/face order and winding are significant.
    This has the same byte format as checker source/candidate geometry hashes.
    """
    xyz = _positions(positions)
    faces = _triangles(triangles, len(xyz))
    return _geometry_fingerprint(xyz, faces)


class SurfaceIntersectionChecker:
    """Cache a fixed source surface and compare many same-topology candidates.

    ``check`` returns JSON data and marks unsafe results with ``safe=False``.
    ``validate`` additionally raises :class:`SurfaceIntersectionError` on new
    intersections or newly collapsed faces. Existing source intersections are
    disclosed and excluded by exact triangle-index pair, never by region.

    Default tolerances suit meter-scale BG3 models: linear contact tolerance
    1e-9, source UV-split weld distance 1e-7, area collapse threshold 1e-12.
    Features below these tolerances cannot be distinguished reliably. The
    collapse threshold measures triangle area, not twice-area normal length.
    """

    def __init__(self, source_positions: Sequence[Sequence[float]],
                 triangles: Sequence[Sequence[int]], *, topology_id: str | None = None,
                 tolerance: float = 1e-9, weld_tolerance: float = 1e-7,
                 area_tolerance: float = 1e-12):
        self.tolerance = _positive(tolerance, "tolerance")
        self.weld_tolerance = _positive(weld_tolerance, "weld_tolerance")
        self.area_tolerance = _positive(area_tolerance, "area_tolerance")
        self.topology_id = topology_id
        self.source = _positions(source_positions)
        self.triangles = _triangles(triangles, len(self.source))
        self.welded_vertices = _weld(self.source, self.weld_tolerance)
        self.welded_triangles = self.welded_vertices[self.triangles]
        self.source_triangles = self.source[self.triangles]
        self.source_cross = np.cross(self.source_triangles[:, 1] - self.source_triangles[:, 0],
                                     self.source_triangles[:, 2] - self.source_triangles[:, 0])
        self.source_area = np.linalg.norm(self.source_cross, axis=1) * 0.5
        self._bvh = _BVH(self.source_triangles)
        self.source_pairs, self.source_stats = self._find(
            self.source_triangles, np.ones(len(self.triangles), dtype=bool))
        self.source_pair_hash = _pair_hash(self.source_pairs)
        self.source_geometry_sha256 = _geometry_fingerprint(self.source, self.triangles)
        for values in (self.source, self.triangles, self.welded_vertices,
                       self.welded_triangles, self.source_triangles,
                       self.source_cross, self.source_area):
            values.flags.writeable = False

    def _find(self, triangles: np.ndarray, active: np.ndarray) -> tuple[set[tuple[int, int]], dict]:
        pairs = self._bvh.pairs(triangles, active, self.tolerance)
        broad_count = len(pairs)
        if not len(pairs):
            return set(), {"aabb_pairs": 0, "narrow_phase_pairs": 0, "exact_fallback_pairs": 0}
        crosses = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        lengths = np.linalg.norm(crosses, axis=1)
        valid = lengths > self.area_tolerance * 2
        pairs = pairs[valid[pairs].all(axis=1)]
        normals = np.divide(crosses, lengths[:, None], out=np.zeros_like(crosses), where=lengths[:, None] > 0)
        # Batch signed-plane rejection removes most neighbor contacts before
        # the scalar narrow phase. A plane cut must be at least a segment;
        # a sole vertex touching the other plane cannot be a crossing.
        a, b = triangles[pairs[:, 0]], triangles[pairs[:, 1]]
        na, nb = normals[pairs[:, 0]], normals[pairs[:, 1]]
        da = np.einsum("nki,ni->nk", a - b[:, :1], nb)
        db = np.einsum("nki,ni->nk", b - a[:, :1], na)
        # An exactly coordinate-equal candidate vertex is a known plane zero.
        # Source weld IDs alone cannot establish this after deformation.
        equal = np.all(a[:,:,None,:]==b[:,None,:,:],axis=3)
        known_a,known_b = equal.any(axis=2),equal.any(axis=1)
        da[known_a],db[known_b] = 0,0
        ambiguous = (((np.abs(da)<=self.tolerance) & ~known_a).any(axis=1)
                     | ((np.abs(db)<=self.tolerance) & ~known_b).any(axis=1)
                     | (np.linalg.norm(np.cross(na,nb),axis=1)<=1e-6))
        # This must precede cuts_segment: a small *nonzero* signed distance can
        # belong to a genuine crossing, not a sole touching vertex.
        exact_pairs = pairs[ambiguous]
        intersections: set[tuple[int, int]] = set()
        for ia,ib in exact_pairs:
            if _exact_pair_intersects(triangles[ia],triangles[ib],self.welded_triangles[ia],
                                      self.welded_triangles[ib],self.tolerance):
                intersections.add((int(ia),int(ib)))

        def cuts_segment(d: np.ndarray) -> np.ndarray:
            return (((d.min(axis=1) < -self.tolerance) & (d.max(axis=1) > self.tolerance)) |
                    ((np.abs(d) <= self.tolerance).sum(axis=1) >= 2))

        keep = ~ambiguous & cuts_segment(da) & cuts_segment(db)
        pairs, da, db = pairs[keep], da[keep], db[keep]
        for (ia, ib), distances_a, distances_b in zip(pairs, da, db):
            ta, tb = triangles[ia], triangles[ib]
            line = np.cross(normals[ia], normals[ib])
            line_length = float(np.linalg.norm(line))
            if line_length <= 1e-10:
                if (np.max(np.abs(distances_a)) <= self.tolerance and
                        np.max(np.abs(distances_b)) <= self.tolerance and
                        _coplanar_overlap(ta, tb, normals[ia], self.tolerance)):
                    intersections.add((int(ia), int(ib)))
                continue
            pa = _plane_segment(ta, distances_a, self.tolerance)
            pb = _plane_segment(tb, distances_b, self.tolerance)
            if len(pa) < 2 or len(pb) < 2:
                continue
            line /= line_length
            # Relative projection avoids loss from large absolute coordinates.
            origin = pa[0]
            aa = [float((p - origin) @ line) for p in pa]
            bb = [float((p - origin) @ line) for p in pb]
            low, high = max(min(aa), min(bb)), min(max(aa), max(bb))
            if high - low <= self.tolerance:
                continue
            endpoints = (origin + low * line, origin + high * line)
            if _expected_shared_contact(ta, tb, self.welded_triangles[ia],
                                        self.welded_triangles[ib], endpoints, self.tolerance):
                continue
            intersections.add((int(ia), int(ib)))
        return intersections, {"aabb_pairs": int(broad_count),
                               "narrow_phase_pairs": int(len(pairs)+len(exact_pairs)),
                               "exact_fallback_pairs": int(len(exact_pairs))}

    def check(self, candidate_positions: Sequence[Sequence[float]], *,
              triangles: Sequence[Sequence[int]] | None = None,
              topology_id: str | None = None) -> dict[str, Any]:
        """Compare final coordinates; supplied topology must be identical."""
        candidate = _positions(candidate_positions)
        if candidate.shape != self.source.shape:
            raise ValueError("Candidate must preserve source position count and triangle topology")
        if triangles is not None and not np.array_equal(_triangles(triangles, len(candidate)), self.triangles):
            raise ValueError("Candidate triangle topology differs from the source")
        if topology_id is not None and topology_id != self.topology_id:
            raise ValueError("Candidate topology_id differs from the source")
        moved = np.any(candidate != self.source, axis=1)
        active = moved[self.triangles].any(axis=1)
        candidate_triangles = candidate[self.triangles]
        cross = np.cross(candidate_triangles[:, 1] - candidate_triangles[:, 0],
                         candidate_triangles[:, 2] - candidate_triangles[:, 0])
        area = np.linalg.norm(cross, axis=1) * 0.5
        original_valid = self.source_area > self.area_tolerance
        collapsed = np.flatnonzero(original_valid & (area <= self.area_tolerance)).tolist()
        turns = np.flatnonzero(original_valid & (area > self.area_tolerance) &
                               (np.einsum("ij,ij->i", self.source_cross, cross) < 0)).tolist()
        if active.any():
            checked, stats = self._find(candidate_triangles, active)
            unchanged = {pair for pair in self.source_pairs if not (active[pair[0]] or active[pair[1]])}
            candidate_pairs = checked | unchanged
        else:
            candidate_pairs = set(self.source_pairs)
            stats = {"aabb_pairs": 0, "narrow_phase_pairs": 0, "exact_fallback_pairs": 0}
        introduced = candidate_pairs - self.source_pairs
        resolved = self.source_pairs - candidate_pairs
        return {
            "schema_version": 1,
            "algorithm": "bvh-plane-interval-coplanar-clip-v1",
            "predicate_version": "adaptive-exact-nearplane-v2",
            "safe": not introduced and not collapsed,
            "topology_id": self.topology_id,
            "source_geometry_sha256": self.source_geometry_sha256,
            "candidate_geometry_sha256": _geometry_fingerprint(candidate, self.triangles),
            "position_count": int(len(self.source)),
            "triangle_count": int(len(self.triangles)),
            "welded_position_count": int(len(np.unique(self.welded_vertices))),
            "tolerances": {"linear": self.tolerance, "source_weld_distance": self.weld_tolerance,
                           "triangle_area": self.area_tolerance, "parallel_sine": 1e-10},
            "contact_policy": "point-only contact and contact confined to a shared welded edge are ignored",
            "exact_fallback": {
                "arithmetic":"Fraction.from_float exact binary-rational plane signs and intervals",
                "trigger":"nonshared vertex within linear plane tolerance, or near-parallel normals",
                "near_parallel_sine":1e-6,
                "source_pairs_tested":self.source_stats["exact_fallback_pairs"],
                "candidate_pairs_tested":stats["exact_fallback_pairs"],
            },
            "source_intersection_count": len(self.source_pairs),
            "source_intersection_pairs": [list(pair) for pair in sorted(self.source_pairs)],
            "source_intersection_pair_sha256": self.source_pair_hash,
            "candidate_intersection_count": len(candidate_pairs),
            "candidate_intersection_pairs": [list(pair) for pair in sorted(candidate_pairs)],
            "introduced_intersection_count": len(introduced),
            "introduced_intersection_pairs": [list(pair) for pair in sorted(introduced)],
            "resolved_intersection_count": len(resolved),
            "resolved_intersection_pairs": [list(pair) for pair in sorted(resolved)],
            "source_collapsed_faces": int(np.count_nonzero(~original_valid)),
            "new_collapsed_faces": len(collapsed),
            "new_collapsed_face_indices": collapsed,
            "reference_normal_turns": len(turns),
            "reference_normal_turn_face_indices": turns,
            "moved_vertices": int(moved.sum()),
            "active_triangles": int(active.sum()),
            "candidate_search": stats,
        }

    def validate(self, candidate_positions: Sequence[Sequence[float]], **kwargs) -> dict[str, Any]:
        report = self.check(candidate_positions, **kwargs)
        if not report["safe"]:
            raise SurfaceIntersectionError(report)
        return report


def compare_surfaces(source_positions: Sequence[Sequence[float]],
                     candidate_positions: Sequence[Sequence[float]],
                     triangles: Sequence[Sequence[int]], **kwargs) -> dict[str, Any]:
    """One-off convenience; reuse a checker for batches of the same source."""
    return SurfaceIntersectionChecker(source_positions, triangles, **kwargs).check(candidate_positions)
