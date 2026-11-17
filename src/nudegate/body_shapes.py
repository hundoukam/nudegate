"""Offline shape studies for explicitly selected normal-female BG3 sources.

Coordinates and masks are authored for the reviewed BCB family sources, not an
age classifier or a generic replacement for arbitrary bodies.
"""
from collections import Counter, defaultdict
import math

from .morphs import apply_morph


def smooth(a: float, b: float, x: float) -> float:
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def band(x: float, a: float, b: float, c: float, d: float) -> float:
    return smooth(a, b, x) * (1.0 - smooth(c, d, x))


def seam_locks(positions: list, triangles: list, rings: int = 2) -> set[int]:
    """Lock open geometric boundaries, welding coincident UV-split positions."""
    canonical = [tuple(round(float(v), 6) for v in p) for p in positions]
    edges = Counter()
    neighbors = defaultdict(set)
    for triangle in triangles:
        if len(triangle) != 3 or any(i < 0 or i >= len(positions) for i in triangle):
            raise ValueError("Invalid source triangle")
        for a, b in zip(triangle, triangle[1:] + triangle[:1]):
            ca, cb = canonical[a], canonical[b]
            if ca == cb:
                continue
            edges[tuple(sorted((ca, cb)))] += 1
            neighbors[ca].add(cb)
            neighbors[cb].add(ca)
    protected = {p for edge, count in edges.items() if count == 1 for p in edge}
    for _ in range(rings):
        protected.update({n for p in list(protected) for n in neighbors[p]})
    return {i for i, p in enumerate(canonical) if p in protected}


def surface_quality(original: list, modified: list, triangles: list) -> dict:
    """Reject collapsed or locally reversed faces introduced by a study."""
    if len(original) != len(modified):
        raise ValueError("Shape changed the position count")
    def normal(points, triangle):
        a, b, c = (points[i] for i in triangle)
        u = [b[k] - a[k] for k in range(3)]
        v = [c[k] - a[k] for k in range(3)]
        return [u[1]*v[2] - u[2]*v[1], u[2]*v[0] - u[0]*v[2], u[0]*v[1] - u[1]*v[0]]
    flipped = collapsed = 0
    for triangle in triangles:
        before, after = normal(original, triangle), normal(modified, triangle)
        old_area = sum(v*v for v in before)
        new_area = sum(v*v for v in after)
        collapsed += old_area > 1e-20 and new_area < 1e-20
        flipped += sum(a*b for a, b in zip(before, after)) < -1e-14
    if flipped or collapsed:
        raise ValueError(f"Shape introduced {flipped} reversed and {collapsed} collapsed faces")
    return {"reversed_faces": flipped, "new_collapsed_faces": collapsed}


def author_masks(positions: list, triangles: list, topology_id: str) -> tuple[dict, dict]:
    if not positions or any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in positions):
        raise ValueError("Expected finite three-dimensional source positions")
    height = max(p[1] for p in positions)
    if not 1.5 < height < 1.65:
        raise ValueError("Source dimensions do not match reviewed normal-female masks")
    locked = seam_locks(positions, triangles)
    # Preserve attachment zones and the central pelvic region independently of
    # the spatial envelopes, including meshes whose seams happen to be closed.
    locked.update(i for i, (x, y, z) in enumerate(positions)
                  if y > 1.48 or y < .20 or abs(x) > .28
                  or (.79 < y < 1.02 and abs(x) < .045 and z < .015))
    regions = {}
    tips = {}
    for side, sign in (("left", -1), ("right", 1)):
        candidates = [p for p in positions if .04 < sign * p[0] < .17 and 1.30 < p[1] < 1.41]
        if not candidates:
            raise ValueError("Source has no reviewed chest landmark candidates")
        # A geometric landmark, not an anatomical/texture classification. Its
        # local surface still needs visual review on each new source topology.
        tip = min(candidates, key=lambda p: p[2])
        tips[side] = list(tip)
        nipple_center = [tip[0], tip[1], tip[2] + .009]
        nipple_weights = []
        chest_weights = []
        for x, y, z in positions:
            radius = math.hypot(x - tip[0], y - tip[1])
            nipple_weights.append((1 - smooth(.004, .019, radius)) * (1 - smooth(tip[2] + .012, tip[2] + .024, z)))
            chest_weights.append(band(sign * x, .012, .040, .165, .220)
                                 * band(y, 1.225, 1.285, 1.405, 1.475)
                                 * (1 - smooth(-.105, -.040, z)))
        regions[f"nipple_{side}"] = {"center": nipple_center, "weights": nipple_weights}
        regions[f"chest_{side}"] = {"center": [sign * .085, 1.35, -.055], "weights": chest_weights}
    central = lambda x: 1 - smooth(.18, .28, abs(x))
    for name, envelope, center in (
        ("waist", (1.04, 1.10, 1.19, 1.265), [0, 1.15, 0]),
        ("hips", (.78, .88, 1.02, 1.105), [0, .95, 0]),
        ("thighs", (.40, .57, .83, .95), [0, .70, 0]),
    ):
        regions[name] = {"center": center,
                         "weights": [band(y, *envelope) * central(x) for x, y, z in positions]}
    body_names = [n for n in regions if not n.startswith("nipple_")]
    # Explicitly partition overlapping body envelopes before applying them.
    for i in range(len(positions)):
        total = sum(regions[n]["weights"][i] for n in body_names)
        if total > 1:
            for name in body_names:
                regions[name]["weights"][i] /= total + 1e-12
    mesh = {"positions": positions, "regions": regions,
            "locked_vertices": sorted(locked), "topology_id": topology_id}
    return mesh, {"surface_landmarks": tips, "locked_vertices": len(locked),
                  "mask_version": "bcb-normal-female-study-v1"}


def bake_shape(mesh: dict, profile: dict) -> tuple[list, dict]:
    """Bake local surface proportions first, then the compatible body study."""
    shape_id = profile["id"]
    nipple = profile["surface_scale"]
    first = apply_morph(mesh, {"id": shape_id + "-surface", "topology_id": mesh["topology_id"],
                              "region_scales": {f"nipple_{s}": nipple for s in ("left", "right")}})
    body_mesh = {**mesh, "positions": first["positions"]}
    scales = {"chest_left": profile["chest_scale"], "chest_right": profile["chest_scale"],
              "waist": profile["waist_scale"], "hips": profile["hips_scale"], "thighs": profile["thigh_scale"]}
    second = apply_morph(body_mesh, {"id": shape_id, "topology_id": mesh["topology_id"], "region_scales": scales})
    result = second["positions"]
    drop = float(profile.get("chest_drop", 0))
    if not math.isfinite(drop) or abs(drop) > .03:
        raise ValueError("Chest offset exceeds the authored study range")
    locked = set(mesh["locked_vertices"])
    for i, p in enumerate(result):
        if i not in locked:
            weight = mesh["regions"]["chest_left"]["weights"][i] + mesh["regions"]["chest_right"]["weights"][i]
            p[1] += drop * weight
    displaced = [math.dist(a, b) for a, b in zip(mesh["positions"], result)]
    if any(result[i] != mesh["positions"][i] for i in locked):
        raise ValueError("Protected source vertices moved")
    if max(displaced) > .15:
        raise ValueError("Shape exceeded the authored displacement limit")
    return result, {"moved_vertices": sum(d > 1e-10 for d in displaced),
                    "max_displacement_metres": max(displaced),
                    "protected_vertices_unchanged": True,
                    "surface_stage": first["report"], "body_stage": second["report"]}
