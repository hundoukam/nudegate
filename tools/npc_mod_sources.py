"""Apply the current profile's root, character visual and placed actor records."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from nudegate.core import _uuid, attrs


ROOT_BANK = re.compile(r"Public/[^/]+/RootTemplates/.+\.(?:lsx|lsf)$", re.I)
VISUAL_BANK = re.compile(r"Public/[^/]+/Content/(?:[^/]+/)*\[PAK\]_CharacterVisuals/.+\.(?:lsx|lsf)$", re.I)
ACTOR_BANK = re.compile(r"Mods/[^/]+/(?:Globals|Levels)/[^/]+/Characters/.+\.(?:lsx|lsf)$", re.I)
META = re.compile(r"Mods/[^/]+/meta\.lsx$", re.I)


def _command(divine, *args):
    result = subprocess.run([str(divine), "-g", "bg3", *map(str, args)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode or re.search(r"(?im)^\s*\[(?:ERROR|FATAL)\]", result.stdout + "\n" + result.stderr):
        raise ValueError(f"Divine failed ({' '.join(map(str, args))}): {result.stdout} {result.stderr}")
    return result.stdout


def _safe_member(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name:
        raise ValueError(f"Invalid PAK member path: {name}")
    return path


def _extract(divine, pak, member, dest):
    path = dest / _safe_member(member)
    path.parent.mkdir(parents=True, exist_ok=True)
    _command(divine, "-a", "extract-single-file", "-s", pak, "-f", member, "-d", path)
    if path.suffix.lower() == ".lsf":
        converted = path.with_suffix(".lsf.lsx")
        _command(divine, "-a", "convert-resource", "-s", path, "-d", converted)
        return converted
    return path


def _enabled(settings):
    root = ET.fromstring(settings)
    children = root.find("./region[@id='ModuleSettings']/node[@id='root']/children")
    if children is None:
        raise ValueError("Expected ModuleSettings in the BG3 profile")
    modules = {}
    for item in children.findall("node[@id='Mods']/children/node[@id='ModuleShortDesc']"):
        metadata = attrs(item)
        identifier = _uuid(metadata.get("UUID"), "profile module")
        if identifier in modules:
            raise ValueError(f"Duplicate active module UUID: {identifier}")
        modules[identifier] = metadata["Folder"].casefold()
    if not modules:
        raise ValueError("No modules found in the active BG3 profile")
    order = [_uuid(attrs(n).get("UUID"), "load order module") for n in
             children.findall("node[@id='ModOrder']/children/node[@id='Module']")]
    if len(order) != len(set(order)) or set(order) - modules.keys():
        raise ValueError("Explicit mod load order has duplicate or unknown entries")
    # Built-ins such as GustavX can appear only under Mods. Modern profiles list
    # every module there in order and omit ModOrder altogether.
    return {key: modules[key] for key in [*(key for key in modules if key not in order), *order]}


def _mod_data(pak, enabled, run_dir, divine):
    listing = _command(divine, "-a", "list-package", "-s", pak)
    paths = [line.split("\t")[0] for line in listing.splitlines() if "\t" in line]
    banks = sorted(p for p in paths if any(rule.fullmatch(p) for rule in (ROOT_BANK,VISUAL_BANK,ACTOR_BANK)))
    if not banks:
        return []
    destination = run_dir / pak.stem
    modules = {}
    for member in paths:
        if not META.fullmatch(member):
            continue
        meta = _extract(divine, pak, member, destination)
        info = ET.parse(meta).findall(".//node[@id='ModuleInfo']")
        if len(info) != 1:
            raise ValueError(f"Ambiguous module metadata in {pak.name}/{member}")
        metadata = attrs(info[0])
        identifier = _uuid(metadata.get("UUID"), "installed module")
        folder = metadata["Folder"].casefold()
        if folder != PurePosixPath(member).parts[1].casefold():
            raise ValueError(f"Module folder mismatch in {pak.name}/{member}")
        if identifier in enabled and enabled[identifier] != folder:
            raise ValueError(f"Active module folder differs from the installed metadata in {pak.name}")
        if folder in modules:
            raise ValueError(f"Duplicate module folder in {pak.name}")
        modules[folder] = identifier
    if len(modules) == 0:
        raise ValueError(f"Appearance banks have no module metadata in {pak.name}; their load order is unknown")
    matches = []
    for member in banks:
        folder = PurePosixPath(member).parts[1].casefold()
        identifier = modules.get(folder)
        if identifier is None:
            # A PAK with one module may also override a vanilla member.
            if len(modules) != 1:
                raise ValueError(f"Cannot assign {member} to a module within {pak.name}")
            identifier = next(iter(modules.values()))
        if identifier in enabled and enabled[identifier] != "nudegate":
            matches.append((identifier, member, _extract(divine, pak, member, destination), pak))
    return matches


def overlay_active_mods(db, mods_dir, settings_path, cache_dir, divine):
    """Return active mod actor paths and a report after updating the effective database."""
    settings = Path(settings_path).read_bytes()
    enabled = _enabled(settings)
    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="active-mods-", dir=cache_dir))
    mods_dir = Path(mods_dir).resolve()
    if not mods_dir.is_dir():
        raise ValueError(f"Missing BG3 Mods folder: {mods_dir}")
    packages = sorted(mods_dir.glob("*.pak"))
    with ThreadPoolExecutor(max_workers=6) as workers:
        groups = list(workers.map(lambda pak: _mod_data(pak, enabled, run_dir, divine), packages))
    priority = {identifier: n for n,identifier in enumerate(enabled)}
    rows = sorted((row for group in groups for row in group), key=lambda row: (priority[row[0]],row[1]))
    module_packages = {}
    actor_files = []
    changes = []
    counts = {"roots":0, "visuals":0, "actor_files":0, "unkeyed_items_skipped":0}
    templates, visuals = dict(db.templates), dict(db.visuals)
    template_sources, visual_sources = dict(db.template_sources), dict(db.visual_sources)
    for identifier, member, path, pak in rows:
        if module_packages.setdefault(identifier, pak.name) != pak.name:
            raise ValueError(f"Two installed PAKs supply active module {identifier}")
        if ACTOR_BANK.fullmatch(member):
            actor_files.append(path)
            counts["actor_files"] += 1
            continue
        visual = bool(VISUAL_BANK.fullmatch(member))
        section = "CharacterVisualBank" if visual else "Templates"
        tag = "Resource" if visual else "GameObjects"
        target = visuals if visual else templates
        provenance = visual_sources if visual else template_sources
        document = ET.parse(path)
        container = document.find(f"./region[@id='{section}']/node[@id='{section}']/children")
        if container is None:
            # Some mods store mesh resources alongside their character visuals
            # (e.g. a custom head). The active mod supplies that referenced mesh.
            if visual and document.find("./region[@id='VisualBank']/node[@id='VisualBank']") is not None:
                continue
            raise ValueError(f"Missing {section} in installed bank {path}")
        for node in container.findall(f"node[@id='{tag}']"):
            values = attrs(node)
            try:
                key = _uuid(values.get("ID" if visual else "MapKey"), "mod resource")
            except ValueError:
                # BCB ships several item drafts with malformed IDs. They cannot
                # be parents of a UUID-linked actor or supply a character visual.
                if not visual and values.get("Type") == "item" and not values.get("CharacterVisualResourceID"):
                    counts["unkeyed_items_skipped"] += 1
                    continue
                raise
            if visual and key in target:
                changes.append({"visual_id":key, "package":pak.name, "name":values.get("Name"),
                                "previous_body":attrs(target[key]).get("BodySetVisual"),
                                "active_body":values.get("BodySetVisual")})
            target[key] = node
            provenance[key] = {"package":pak.name,"module":enabled[identifier],"path":member}
            counts["visuals" if visual else "roots"] += 1
    if Path(settings_path).read_bytes() != settings:
        raise ValueError("BG3 profile changed during the active mod scan")
    db.templates, db.visuals = templates, visuals
    db.template_sources, db.visual_sources = template_sources, visual_sources
    db._children = None
    db._children_count = -1
    return actor_files, {"settings_sha256":hashlib.sha256(settings).hexdigest(),
                         "installed_packages_scanned":len(packages),"profile_modules":len(enabled),
                         "active_packages_with_banks":list(dict.fromkeys(module_packages.values())),
                         "records":counts,"overridden_character_visuals":changes}
