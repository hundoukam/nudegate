"""Read the installed game's global and level character records in archive order."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from build import run


ACTOR_FILE = re.compile(r"Mods/[^/]+/(?:Globals|Levels)/[^/]+/Characters/[^/]+\.(?:lsf|lsx)", re.I)


def actor_sources(data, ordered, cache, divine):
    archives = sorted(data.glob("*.pak"), key=lambda p: p.name.casefold())
    stamps = [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in archives]
    key = hashlib.sha256(json.dumps(stamps).encode()).hexdigest()[:24]
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / key
    manifest = dest / "manifest.json"
    if not manifest.exists():
        # V16/V18 store the directory for every numbered part in the first PAK.
        split_parts = set()
        for archive in archives:
            with archive.open("rb") as stream:
                header = stream.read(40)
            if header[:4] == b"LSPK" and int.from_bytes(header[4:8], "little") in (16, 18):
                count = int.from_bytes(header[38:40], "little")
                for i in range(1, count):
                    part = archive.with_name(f"{archive.stem}_{i}.pak")
                    if not part.is_file():
                        raise ValueError(f"Missing numbered game archive part {part.name}")
                    split_parts.add(part)
        def inventory(pak):
            files = [line.split("\t", 1)[0].replace("\\", "/") for line in
                     run(divine, "-a", "list-package", "-s", pak).splitlines()]
            return pak.stem, sorted(name for name in files if ACTOR_FILE.fullmatch(name))

        with ThreadPoolExecutor(max_workers=3) as pool:
            listed = dict(pool.map(inventory, (p for p in archives if p not in split_parts)))
        extra = [name for name, files in listed.items() if files and name not in ordered]
        if extra:
            raise ValueError(f"Actor sources require package ordering for {extra}")
        with TemporaryDirectory(prefix="npc-actors-", dir=cache) as temporary:
            stage = Path(temporary) / "records"
            stage.mkdir()
            rows = []
            for package in ordered:
                origin = stage / package
                for name in listed[package]:
                    if ".." in Path(name).parts:
                        raise ValueError(f"Invalid actor path in {package}")
                    game_file = origin / name
                    run(divine, "-a", "extract-package", "-s", data / (package + ".pak"),
                        "-d", origin, "-x", name)
                    if not game_file.is_file():
                        raise ValueError(f"Missing listed actor file {name}")
                    xml = game_file
                    if game_file.suffix.lower() == ".lsf":
                        xml = game_file.with_suffix(".lsf.lsx")
                        run(divine, "-a", "convert-resource", "-s", game_file, "-d", xml)
                    rows.append({"path": xml.relative_to(stage).as_posix(),
                                 "sha256": hashlib.sha256(xml.read_bytes()).hexdigest()})
            if not rows:
                raise ValueError("No installed game actor records found")
            (stage / "manifest.json").write_text(json.dumps(
                {"archives": stamps, "actor_files_by_package": listed, "records": rows}, indent=2))
            try:
                stage.rename(dest)
            except FileExistsError:
                if not manifest.is_file():
                    raise
    proof = json.loads(manifest.read_text())
    if proof["archives"] != [list(stamp) for stamp in stamps]:
        raise ValueError("Actor source cache does not match the installed game")
    files = []
    for row in proof["records"]:
        path = (dest / row["path"]).resolve()
        if not path.is_relative_to(dest.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Cached actor file no longer matches its extraction")
        files.append(path)
    if not files or len(files) != sum(map(len, proof["actor_files_by_package"].values())):
        raise ValueError("Actor source cache is incomplete")
    return files, {"archives_listed": len(proof["actor_files_by_package"]), "game_pak_files": len(stamps), "character_banks": len(files),
                   "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}
