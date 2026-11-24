"""Package an AC:Unreal plugin folder for a GitHub release (Python 3.10+)."""
import argparse
import base64
import json
import re
from pathlib import Path

ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")
ASSET = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_. -]{0,90}\.(png|wav)", re.I)
RESERVED = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)", re.I)
LIMIT = 16 * 1024 * 1024
NATIVE = {"actiondeck", "autocraft", "huntledger", "looteditor", "supplyledger", "ucmmicro", "waypoint"}
OFFICIAL_DATA = {
    "autocraft": ("catalog.json", "LICENSE", "NOTICE.txt"),
    "ucm": ("monster-elements.json",),
    "thirdeye": ("sounds/README.txt",),
    "waypoint": ("locations.xml", "MapRegions.xml", "LICENSE_GOARROW.txt"),
}


def plugin_id_from_manifest(manifest):
    plugin_id = manifest["id"]
    if not ID.fullmatch(plugin_id) or RESERVED.match(plugin_id) or type(manifest.get("api")) is not int or manifest["api"] not in (1, 2):
        raise ValueError("Expected a portable lowercase plugin ID and API 1 or 2")
    if manifest.get("mode", "") not in ("", "automation", "companion") or not isinstance(manifest.get("permissions"), list):
        raise ValueError("Expected a Lua automation or companion manifest with a permissions list")
    if not isinstance(manifest.get("version"), str) or not 0 < len(manifest["version"].strip()) <= 96:
        raise ValueError("Set a plugin version of 1 to 96 characters in plugin.json")
    return plugin_id


def file_limit(key, official_id=None):
    if key in OFFICIAL_DATA.get(official_id, ()):
        return 8 * 1024 * 1024 if key == "catalog.json" else 2 * 1024 * 1024
    if key == "main.lua":
        return 256 * 1024
    if key in ("plugin.json", "default.json"):
        return 2 * 1024 * 1024
    directory, _, name = key.partition("/")
    if directory == "data" and re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_. -]{0,90}\.(json|xml|txt)", name, re.I) and not RESERVED.match(name):
        return 8 * 1024 * 1024
    extension = {"images": ".png", "sounds": ".wav"}.get(directory)
    if not extension or not ASSET.fullmatch(name) or RESERVED.match(name) or not name.lower().endswith(extension):
        raise ValueError(f"Unsupported package path: {key}")
    return 1024 * 1024 if directory == "sounds" else 2 * 1024 * 1024


def validate_bundle(data, expected_id, official=False):
    if not 0 < len(data) <= LIMIT:
        raise ValueError("Package exceeds 16 MiB or is empty")
    def unique_keys(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("Duplicate JSON key")
        return result
    bundle = json.loads(data, object_pairs_hook=unique_keys)
    files = bundle["files"]
    if type(bundle["format"]) is not int or bundle["format"] != 1 or not isinstance(files, dict) or not 1 <= len(files) <= 128:
        raise ValueError("Invalid plugin package format")
    required = {"plugin.json", *OFFICIAL_DATA.get(expected_id, ())} if official else {"plugin.json"}
    if not official or expected_id not in NATIVE:
        required.add("main.lua")
    if not required.issubset(files) or len({key.lower() for key in files}) != len(files):
        raise ValueError("Missing required files or duplicate filenames")
    for key, value in files.items():
        limit = file_limit(key, expected_id if official else None)
        if not isinstance(value, str) or len(value) > ((limit+2)//3)*4:
            raise ValueError(f"Invalid encoded file: {key}")
        decoded = base64.b64decode(value, validate=True)
        if not 0 < len(decoded) <= limit:
            raise ValueError(f"Unsupported file size: {key}")
        if key == "plugin.json":
            manifest = json.loads(decoded, object_pairs_hook=unique_keys)
            if plugin_id_from_manifest(manifest) != expected_id:
                raise ValueError("Release manifest ID differs from the registration")
            if manifest["api"] == 2 and "main.lua" not in files:
                raise ValueError("API 2 plugins require main.lua")
            version = manifest["version"].strip()
        if key.startswith("data/"):
            decoded.decode("utf-8")
        if key == "default.json" and not isinstance(json.loads(decoded, object_pairs_hook=unique_keys), dict):
            raise ValueError("Expected a JSON object in default.json")
    return version


def pack(folder, output, official=False):
    manifest = json.loads((folder / "plugin.json").read_text(encoding="utf-8-sig"))
    plugin_id = plugin_id_from_manifest(manifest)
    paths = [Path("plugin.json")]
    if not official or plugin_id not in NATIVE or (folder / "main.lua").exists():
        paths.append(Path("main.lua"))
    extras = OFFICIAL_DATA.get(plugin_id, ()) if official else ()
    paths.extend(map(Path, extras))
    if (folder / "default.json").is_file():
        paths.append(Path("default.json"))
    for directory, extension in (("images", ".png"), ("sounds", ".wav")):
        for path in sorted((folder / directory).glob("*")):
            if path.relative_to(folder).as_posix() in extras:
                continue
            if not ASSET.fullmatch(path.name) or RESERVED.match(path.name) or path.suffix.lower() != extension:
                raise ValueError(f"Unsupported asset: {path}")
            paths.append(path.relative_to(folder))
    paths.extend(path.relative_to(folder) for path in sorted((folder / "data").glob("*")))
    files = {}
    seen = set()
    size = 0
    for path in paths:
        source = folder / path
        key = path.as_posix()
        if source.is_symlink() or not source.resolve().is_relative_to(folder.resolve()) or key.lower() in seen:
            raise ValueError(f"Invalid or duplicate asset: {key}")
        seen.add(key.lower())
        limit = file_limit(key, plugin_id if official else None)
        if not 0 < source.stat().st_size <= limit:
            raise ValueError(f"Unsupported file size: {key}")
        files[key] = base64.b64encode(source.read_bytes()).decode("ascii")
        size += len(files[key])
        if size > LIMIT or len(files) > 128:
            raise ValueError("Package exceeds 16 MiB or 128 files")
    data = json.dumps({"format": 1, "files": files}, separators=(",", ":")).encode()
    validate_bundle(data, plugin_id, official)
    output.mkdir(parents=True, exist_ok=True)
    result = output / f"{plugin_id}.acplugin"
    result.write_bytes(data)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--official", action="store_true", help="Package AC:Unreal's native panels and official data")
    args = parser.parse_args()
    print(pack(args.folder, args.output, args.official))

