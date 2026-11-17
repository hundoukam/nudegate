"""Conservative COLLADA position editing for reviewed, externally authored meshes.

Supports indexed triangle meshes, including LSLib's direct-source VERTEX input.
Skin controllers, UVs, material bindings, and every unedited XML element stay in
the document. Rebuilt normals retain existing corner-normal indices, sharing
area sums across originally smooth coincident UV splits while retaining hard
edges. Tangent/binormal arrays are preserved; rebuild tangent frames
in the final asset exporter when required by its normal-map workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


NS = "http://www.collada.org/2005/11/COLLADASchema"
ET.register_namespace("", NS)


def _tag(name: str) -> str:
    return f"{{{NS}}}{name}"


def _canonical(element: ET.Element) -> Any:
    """Semantic XML representation, independent of prefixes and indentation."""
    return [str(element.tag), sorted(element.attrib.items()),
            " ".join((element.text or "").split()),
            [_canonical(child) for child in element]]


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _integer(value: str | None, label: str, minimum: int = 0) -> int:
    try:
        result = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if str(value).strip() != str(result) or result < minimum:
        raise ValueError(f"Invalid {label}: {value!r}")
    return result


def _indices(element: ET.Element | None, label: str) -> list[int]:
    if element is None:
        raise ValueError(f"Missing {label}")
    return [_integer(token, label) for token in (element.text or "").split()]


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _reference(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("#") or len(value) == 1:
        raise ValueError(f"{label} must reference a local XML ID")
    return value[1:]


@dataclass
class _Source:
    element: ET.Element
    array: ET.Element
    values: list[float] | list[str]
    count: int
    stride: int
    offset: int
    components: tuple[int, int, int] | None
    numeric: bool

    @classmethod
    def read(cls, element: ET.Element) -> "_Source":
        arrays = [child for child in element if child.tag in
                  {_tag("float_array"), _tag("Name_array"), _tag("IDREF_array")}]
        if len(arrays) != 1:
            raise ValueError(f"Source {element.get('id')} requires exactly one supported array")
        array = arrays[0]
        tokens = (array.text or "").split()
        declared = _integer(array.get("count"), "array count")
        if declared != len(tokens):
            raise ValueError(f"Array count mismatch in source {element.get('id')}")
        numeric = array.tag == _tag("float_array")
        if numeric:
            try:
                values = [float(token) for token in tokens]
            except ValueError as exc:
                raise ValueError(f"Nonnumeric float array in source {element.get('id')}") from exc
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"Nonfinite float array in source {element.get('id')}")
        else:
            values = tokens
        accessors = element.findall(f"{_tag('technique_common')}/{_tag('accessor')}")
        if len(accessors) != 1:
            raise ValueError(f"Source {element.get('id')} requires exactly one accessor")
        accessor = accessors[0]
        if _reference(accessor.get("source"), "accessor source") != array.get("id"):
            raise ValueError(f"Accessor references a different array in source {element.get('id')}")
        count = _integer(accessor.get("count"), "accessor count")
        stride = _integer(accessor.get("stride", "1"), "accessor stride", 1)
        offset = _integer(accessor.get("offset", "0"), "accessor offset")
        params = accessor.findall(_tag("param"))
        component_offsets = []
        width = 0
        for param in params:
            component_offsets.append(width)
            parameter_type = param.get("type", "float")
            match = re.fullmatch(r"(?:float|double|int|bool)([1-4])?(?:x([1-4]))?", parameter_type)
            width += (int(match.group(1) or "1") * int(match.group(2) or "1")) if match else 1
        if width > stride:
            raise ValueError(f"Accessor parameters exceed stride in source {element.get('id')}")
        width = width if params else stride
        if offset > len(values) or (count and offset + (count - 1) * stride + width > len(values)):
            raise ValueError(f"Accessor exceeds array bounds in source {element.get('id')}")
        names = [param.get("name") for param in params]
        components = None
        if all(names.count(name) == 1 for name in ("X", "Y", "Z")):
            components = tuple(component_offsets[names.index(name)] for name in ("X", "Y", "Z"))
        elif stride == 3 and (not params or not any(names)):
            components = (0, 1, 2)
        return cls(element, array, values, count, stride, offset, components, numeric)

    def vector3(self, index: int) -> list[float]:
        if not self.numeric or self.components is None:
            raise ValueError(f"Source {self.element.get('id')} is not an explicit XYZ vector array")
        if index < 0 or index >= self.count:
            raise ValueError(f"Vector index out of bounds in source {self.element.get('id')}: {index}")
        start = self.offset + index * self.stride
        return [self.values[start + component] for component in self.components]

    def replacing_vectors(self, vectors: dict[int, list[float]]) -> list[float]:
        values = list(self.values)
        for index, vector in vectors.items():
            self.vector3(index)  # Validates this source's layout and bounds.
            start = self.offset + index * self.stride
            for axis, component in enumerate(self.components):
                values[start + component] = vector[axis]
        return values

    def commit(self, values: list[float]) -> None:
        self.values = values
        self.array.text = " ".join(format(value, ".17g") for value in values)


@dataclass(frozen=True)
class _Corner:
    position: int
    normal: tuple[str, int] | None


class ColladaMesh:
    """One explicitly selected mesh inside a preserved COLLADA XML document."""

    @classmethod
    def load(cls, path: str | Path, geometry_id: str | None = None) -> "ColladaMesh":
        path = Path(path)
        try:
            parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
            tree = ET.parse(path, parser=parser)
        except (OSError, ET.ParseError) as exc:
            raise ValueError(f"Cannot read COLLADA document {path}: {exc}") from exc
        root = tree.getroot()
        if root.tag != _tag("COLLADA"):
            raise ValueError("Expected COLLADA document in the standard COLLADA namespace")
        geometries = root.findall(f"{_tag('library_geometries')}/{_tag('geometry')}")
        meshes = [geometry for geometry in geometries if geometry.find(_tag("mesh")) is not None]
        if geometry_id is None:
            if len(meshes) != 1:
                raise ValueError(f"Explicit geometry_id required: document contains {len(meshes)} mesh geometries")
            geometry = meshes[0]
        else:
            selected = [geometry for geometry in meshes if geometry.get("id") == geometry_id]
            if len(selected) != 1:
                raise ValueError(f"Expected exactly one mesh with geometry_id {geometry_id!r}")
            geometry = selected[0]
        if not geometry.get("id"):
            raise ValueError("Selected geometry has no XML ID")
        instance = cls()
        instance._tree = tree
        instance._root = root
        instance._geometry = geometry
        instance.geometry_id = geometry.get("id")
        instance._mesh = geometry.find(_tag("mesh"))
        instance._ids: dict[str, ET.Element] = {}
        for element in root.iter():
            identifier = element.get("id")
            if identifier:
                if identifier in instance._ids:
                    raise ValueError(f"Duplicate XML ID: {identifier}")
                instance._ids[identifier] = element
        instance._sources = {source.get("id"): _Source.read(source)
                             for source in instance._mesh.findall(_tag("source"))}
        if None in instance._sources:
            raise ValueError("Mesh source has no XML ID")
        instance._position_source_id = None
        instance._normal_sources: set[str] = set()
        instance._uv_sources: set[str] = set()
        instance._tangent_sources: set[str] = set()
        instance._source_semantics: dict[str, set[str]] = {}
        instance._corners: list[tuple[_Corner, _Corner, _Corner]] = []
        instance._primitives = []
        instance._read_primitives()
        for source_id in {instance._position_source_id} | instance._normal_sources:
            expected = "POSITION" if source_id == instance._position_source_id else "NORMAL"
            if instance._source_semantics[source_id] != {expected}:
                raise ValueError(f"Editable {expected} source {source_id} is shared with another attribute semantic")
        instance._position_source = instance._sources[instance._position_source_id]
        if instance._position_source.count == 0:
            raise ValueError("Selected mesh has no positions")
        for index in range(instance._position_source.count):
            instance._position_source.vector3(index)
        instance._original_positions = instance.positions
        instance._original_normals = {
            corner.normal: instance._sources[corner.normal[0]].vector3(corner.normal[1])
            for triangle in instance._corners for corner in triangle if corner.normal is not None
        }
        instance._normal_groups = None
        instance._controllers, instance._weighted_vertices = instance._read_skin()
        return instance

    def _source(self, reference: str | None, label: str) -> tuple[str, _Source]:
        identifier = _reference(reference, label)
        if identifier not in self._sources:
            raise ValueError(f"{label} references an unknown mesh source: {identifier}")
        return identifier, self._sources[identifier]

    def _read_primitives(self) -> None:
        supported_children = {_tag("source"), _tag("vertices"), _tag("triangles"), _tag("extra")}
        for element in self._mesh:
            if isinstance(element.tag, str) and element.tag not in supported_children:
                raise ValueError(f"Unsupported mesh primitive or element: {element.tag.rsplit('}', 1)[-1]}")
        for primitive in self._mesh.findall(_tag("triangles")):
            self._primitives.append(primitive)
            count = _integer(primitive.get("count"), "triangle count")
            inputs = primitive.findall(_tag("input"))
            if not inputs:
                raise ValueError("Triangle primitive has no inputs")
            stride = max(_integer(item.get("offset", "0"), "input offset") for item in inputs) + 1
            bindings: list[tuple[str, str, _Source, int]] = []
            for item in inputs:
                semantic = item.get("semantic")
                offset = _integer(item.get("offset", "0"), "input offset")
                reference = _reference(item.get("source"), "triangle input")
                target = self._ids.get(reference)
                if target is None:
                    raise ValueError(f"Triangle input references unknown XML ID: {reference}")
                if semantic == "VERTEX" and target.tag == _tag("vertices"):
                    children = target.findall(_tag("input"))
                    if not children:
                        raise ValueError("VERTEX input references an empty vertices element")
                    for child in children:
                        source_id, source = self._source(child.get("source"), "vertices input")
                        bindings.append((child.get("semantic"), source_id, source, offset))
                else:
                    source_id, source = self._source(item.get("source"), "triangle input")
                    bindings.append(("POSITION" if semantic == "VERTEX" else semantic, source_id, source, offset))
            position_bindings = [binding for binding in bindings if binding[0] == "POSITION"]
            normal_bindings = [binding for binding in bindings if binding[0] == "NORMAL"]
            if len(position_bindings) != 1 or len(normal_bindings) > 1:
                raise ValueError("Triangle primitive requires one unambiguous POSITION and at most one NORMAL binding")
            position_id = position_bindings[0][1]
            position_bindings[0][2].vector3(0)
            if self._position_source_id is not None and self._position_source_id != position_id:
                raise ValueError("Selected geometry uses multiple position sources; explicit mesh consolidation required")
            self._position_source_id = position_id
            for semantic, source_id, source, _ in bindings:
                self._source_semantics.setdefault(source_id, set()).add(semantic)
                if semantic == "NORMAL":
                    source.vector3(0)
                    self._normal_sources.add(source_id)
                elif semantic == "TEXCOORD":
                    self._uv_sources.add(source_id)
                elif semantic in {"TEXTANGENT", "TEXBINORMAL", "TANGENT", "BINORMAL"}:
                    self._tangent_sources.add(source_id)
            p_elements = primitive.findall(_tag("p"))
            if len(p_elements) != 1:
                raise ValueError("Triangle primitive requires exactly one index array")
            values = _indices(p_elements[0], "triangle indices")
            if len(values) != count * 3 * stride:
                raise ValueError("Triangle index count does not match count and input stride")
            corners = []
            for start in range(0, len(values), stride):
                position_index = None
                normal = None
                for semantic, source_id, source, offset in bindings:
                    index = values[start + offset]
                    if index >= source.count:
                        raise ValueError(f"{semantic} index out of bounds for source {source_id}: {index}")
                    if semantic == "POSITION":
                        position_index = index
                    elif semantic == "NORMAL":
                        normal = (source_id, index)
                corners.append(_Corner(position_index, normal))
            self._corners.extend(tuple(corners[index:index + 3]) for index in range(0, len(corners), 3))
        if not self._corners or self._position_source_id is None:
            raise ValueError("Selected mesh must contain indexed triangles")

    def _read_skin(self) -> tuple[list[ET.Element], set[int]]:
        controllers = []
        weighted: set[int] = set()
        for controller in self._root.findall(f"{_tag('library_controllers')}/{_tag('controller')}"):
            skin = controller.find(_tag("skin"))
            if skin is None or _reference(skin.get("source"), "skin source") != self.geometry_id:
                continue
            controllers.append(controller)
            sources = {source.get("id"): _Source.read(source) for source in skin.findall(_tag("source"))}
            weights = skin.find(_tag("vertex_weights"))
            if weights is None:
                raise ValueError("Skin controller has no vertex_weights")
            count = _integer(weights.get("count"), "skin vertex count")
            if count != self._position_source.count:
                raise ValueError("Skin vertex count does not match position count")
            inputs = weights.findall(_tag("input"))
            if not inputs:
                raise ValueError("Skin vertex_weights has no inputs")
            stride = max(_integer(item.get("offset", "0"), "skin input offset") for item in inputs) + 1
            bindings = []
            for item in inputs:
                identifier = _reference(item.get("source"), "skin input")
                if identifier not in sources:
                    raise ValueError(f"Skin input references unknown source: {identifier}")
                bindings.append((item.get("semantic"), sources[identifier],
                                 _integer(item.get("offset", "0"), "skin input offset")))
            if sum(semantic == "WEIGHT" for semantic, _, _ in bindings) != 1 or sum(semantic == "JOINT" for semantic, _, _ in bindings) != 1:
                raise ValueError("Skin requires one JOINT and one WEIGHT input")
            counts = _indices(weights.find(_tag("vcount")), "skin influence counts")
            values = _indices(weights.find(_tag("v")), "skin influence indices")
            if len(counts) != count or len(values) != sum(counts) * stride:
                raise ValueError("Skin influence counts do not match indices")
            cursor = 0
            for vertex, influences in enumerate(counts):
                for _ in range(influences):
                    for semantic, source, offset in bindings:
                        index = values[cursor + offset]
                        if index >= source.count:
                            raise ValueError(f"Skin {semantic} index out of bounds: {index}")
                        if semantic == "WEIGHT":
                            if not source.numeric or source.stride != 1:
                                raise ValueError("Skin WEIGHT source must be a numeric scalar array")
                            value = source.values[source.offset + index]
                            if value < 0:
                                raise ValueError("Skin weights must not be negative")
                            if value > 0:
                                weighted.add(vertex)
                    cursor += stride
        return controllers, weighted

    @property
    def positions(self) -> list[list[float]]:
        return [self._position_source.vector3(index) for index in range(self._position_source.count)]

    @property
    def triangles(self) -> list[tuple[int, int, int]]:
        return [tuple(corner.position for corner in triangle) for triangle in self._corners]

    @property
    def topology_id(self) -> str:
        source_layout = []
        for identifier in sorted(self._sources):
            source = self._sources[identifier]
            accessor = source.element.find(f"{_tag('technique_common')}/{_tag('accessor')}")
            source_layout.append([identifier, _canonical(accessor)])
        payload = {
            "version": 1, "geometry": self.geometry_id,
            "vertex_count": self._position_source.count,
            "source_layout": source_layout,
            "vertices": [_canonical(node) for node in self._mesh.findall(_tag("vertices"))],
            "primitives": [_canonical(node) for node in self._primitives],
            "uv": [_canonical(self._sources[key].element) for key in sorted(self._uv_sources)],
            "skin": [_canonical(node) for node in self._controllers],
        }
        return "collada-topology-v1:" + _hash(payload)

    def snapshot(self) -> dict[str, Any]:
        """Return semantic preservation hashes and counts for review reports."""
        return {
            "geometry_id": self.geometry_id,
            "topology_id": self.topology_id,
            "vertex_count": self._position_source.count,
            "triangle_count": len(self._corners),
            "skin_controller_count": len(self._controllers),
            "skin_weighted_vertices": len(self._weighted_vertices),
            "normal_source_count": len(self._normal_sources),
            "controller_sha256": _hash([_canonical(node) for node in self._root.findall(_tag("library_controllers"))]),
            "uv_sha256": _hash([_canonical(self._sources[key].element) for key in sorted(self._uv_sources)]),
            "tangent_sha256": _hash([_canonical(self._sources[key].element) for key in sorted(self._tangent_sources)]),
            "material_sha256": _hash([_canonical(node) for node in self._root if node.tag in
                                     {_tag("library_materials"), _tag("library_effects")}]),
            "position_sha256": _hash(self.positions),
            "normal_sha256": _hash([_canonical(self._sources[key].element) for key in sorted(self._normal_sources)]),
        }

    def _smoothing_groups(self) -> list[tuple[set[tuple[str, int]], set[int]]]:
        """Use the source's own normals to distinguish UV splits from hard edges.

        Coincident original positions can share a sum only if all original unit
        normals in the merged group differ by at most .01 in vector length
        (about .57 degrees). A complete-group check prevents tolerance chaining
        from gradually joining distinct hard-edge directions.
        """
        if self._normal_groups is not None:
            return self._normal_groups
        parents = {binding: binding for binding in self._original_normals}
        members = {binding: {binding} for binding in self._original_normals}
        units = {}
        for binding, vector in self._original_normals.items():
            length = math.hypot(*vector)
            if not math.isfinite(length) or length == 0:
                raise ValueError(f"Cannot infer smoothing from zero or nonfinite source normal: {binding}")
            units[binding] = [value / length for value in vector]

        def find(binding):
            while parents[binding] != binding:
                parents[binding] = parents[parents[binding]]
                binding = parents[binding]
            return binding

        by_position: dict[tuple[float, float, float], set[tuple[str, int]]] = {}
        incident: dict[tuple[str, int], set[int]] = {}
        for face, triangle in enumerate(self._corners):
            for corner in triangle:
                position = tuple(self._original_positions[corner.position])
                by_position.setdefault(position, set()).add(corner.normal)
                incident.setdefault(corner.normal, set()).add(face)
        for bindings in by_position.values():
            ordered = sorted(bindings)
            for index, a in enumerate(ordered):
                for b in ordered[index + 1:]:
                    root_a, root_b = find(a), find(b)
                    if root_a == root_b:
                        continue
                    if all(math.dist(units[x], units[y]) <= .01
                           for x in members[root_a] for y in members[root_b]):
                        keep, remove = sorted((root_a, root_b))
                        parents[remove] = keep
                        members[keep].update(members.pop(remove))
        groups = []
        for _, bindings in sorted(members.items()):
            faces = set().union(*(incident[binding] for binding in bindings))
            groups.append((bindings, faces))
        self._normal_groups = groups
        return groups

    def _normal_values(self, positions: list[list[float]]) -> tuple[dict[str, list[float]], int, int]:
        crosses = []
        changed_faces = set()
        for face, triangle in enumerate(self._corners):
            if any(corner.normal is None for corner in triangle):
                raise ValueError("Normal recalculation requires an explicit NORMAL binding on every triangle")
            if any(positions[corner.position] != self._original_positions[corner.position] for corner in triangle):
                changed_faces.add(face)
            a, b, c = (positions[corner.position] for corner in triangle)
            u = [b[axis] - a[axis] for axis in range(3)]
            v = [c[axis] - a[axis] for axis in range(3)]
            cross = [u[1] * v[2] - u[2] * v[1],
                     u[2] * v[0] - u[0] * v[2],
                     u[0] * v[1] - u[1] * v[0]]
            if not all(math.isfinite(value) for value in cross):
                raise ValueError("Nonfinite face normal during recalculation")
            crosses.append(cross)
        replacements: dict[str, dict[int, list[float]]] = {}
        rebuilt = preserved = 0
        for bindings, faces in self._smoothing_groups():
            if not faces & changed_faces:
                # Preserve authored shading on every completely untouched
                # neighborhood, and restore it when a deformation is undone.
                for source_id, index in bindings:
                    replacements.setdefault(source_id, {})[index] = self._original_normals[(source_id, index)]
                preserved += len(bindings)
                continue
            try:
                vector = [math.fsum(crosses[face][axis] for face in sorted(faces)) for axis in range(3)]
            except OverflowError as exc:
                raise ValueError("Face normal accumulation overflow") from exc
            length = math.hypot(*vector)
            if not math.isfinite(length) or length == 0:
                raise ValueError(f"Cannot recalculate zero or nonfinite normal for source smoothing group {sorted(bindings)}")
            normal = [value / length for value in vector]
            for source_id, index in bindings:
                replacements.setdefault(source_id, {})[index] = normal
            rebuilt += len(bindings)
        return {source_id: self._sources[source_id].replacing_vectors(vectors)
                for source_id, vectors in replacements.items()}, rebuilt, preserved

    def set_positions(self, positions: list[list[float]], *, recalculate_normals: bool = True) -> dict[str, Any]:
        """Replace positions without changing indices or rigging; rebuild normals.

        All validation and normal calculations finish before XML is changed.
        Tangent/binormal arrays stay intact and need a final exporter rebuild
        when using tangent-space normal maps.
        """
        if not isinstance(recalculate_normals, bool):
            raise ValueError("recalculate_normals must be a boolean")
        if not isinstance(positions, (list, tuple)) or len(positions) != self._position_source.count:
            raise ValueError("New positions must preserve vertex count")
        validated = []
        for index, position in enumerate(positions):
            if not isinstance(position, (list, tuple)) or len(position) != 3:
                raise ValueError(f"Position {index} must contain exactly three coordinates")
            validated.append([_number(value, f"position {index} coordinate") for value in position])
        normals, normals_updated, normals_preserved = self._normal_values(validated) if recalculate_normals else ({}, 0, 0)
        values = self._position_source.replacing_vectors(dict(enumerate(validated)))
        # Commit only after every potential authoring-data failure has passed.
        self._position_source.commit(values)
        for source_id, normal_values in normals.items():
            self._sources[source_id].commit(normal_values)
        return {"vertex_count": len(validated), "normals_updated": normals_updated,
                "normals_preserved": normals_preserved,
                "normal_sources_updated": len(normals), "tangent_frames": "preserved; exporter rebuild required"}

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        self._tree.write(temporary, encoding="utf-8", xml_declaration=True)
        temporary.replace(path)


def validate_smooth_seams(reference: ColladaMesh, current: ColladaMesh,
                          tolerance_degrees: float = 1.0) -> dict[str, Any]:
    """Reject shading splits within smoothing groups established by the source.

    Matching triangle/corner order maps current normals even when an exporter
    renames or deduplicates normal arrays. Only the reference's original
    coincident positions and original agreeing normals establish merged groups;
    original hard edges retain separate acceptance groups.
    """
    tolerance = _number(tolerance_degrees, "normal seam tolerance")
    if tolerance <= 0 or tolerance > 180:
        raise ValueError("Normal seam tolerance must be within (0, 180] degrees")
    if len(reference.positions) != len(current.positions) or reference.triangles != current.triangles:
        raise ValueError("Smooth seam validation requires matching indexed triangle topology")
    if any(corner.normal is None for mesh in (reference, current)
           for triangle in mesh._corners for corner in triangle):
        raise ValueError("Smooth seam validation requires NORMAL bindings on every corner")
    groups = reference._smoothing_groups()
    lookup = {binding: index for index, (bindings, _) in enumerate(groups) for binding in bindings}
    actual: list[set[tuple[float, float, float]]] = [set() for _ in groups]
    for original_triangle, current_triangle in zip(reference._corners, current._corners):
        for original, changed in zip(original_triangle, current_triangle):
            source_id, normal_index = changed.normal
            vector = current._sources[source_id].vector3(normal_index)
            length = math.hypot(*vector)
            if not math.isfinite(length) or length == 0:
                raise ValueError("Smooth seam validation found a zero or nonfinite normal")
            actual[lookup[original.normal]].add(tuple(value / length for value in vector))
    maximum = seam_maximum = 0.0
    seam_count = 0
    for index, (bindings, _) in enumerate(groups):
        vectors = sorted(actual[index])
        group_maximum = 0.0
        for i, a in enumerate(vectors):
            for b in vectors[i + 1:]:
                dot = max(-1.0, min(1.0, math.fsum(x * y for x, y in zip(a, b))))
                group_maximum = max(group_maximum, math.degrees(math.acos(dot)))
        maximum = max(maximum, group_maximum)
        if len(bindings) > 1:
            seam_count += 1
            seam_maximum = max(seam_maximum, group_maximum)
        if group_maximum > tolerance:
            raise ValueError(f"New smooth-normal seam exceeds {tolerance} degrees: {group_maximum:.6f} degrees in source group {index}")
    return {"status": "passed", "source_smoothing_groups": len(groups),
            "source_smooth_seam_groups": seam_count,
            "checked_corner_normals": len(reference._corners) * 3,
            "max_smoothing_group_angle_degrees": maximum,
            "max_smooth_seam_angle_degrees": seam_maximum,
            "tolerance_degrees": tolerance}
