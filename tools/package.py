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


def plugin_id_from_manifest(manifest):
    plugin_id = manifest["id"]
    if not ID.fullmatch(plugin_id) or RESERVED.match(plugin_id) or type(manifest.get("api")) is not int or manifest["api"] not in (1, 2):
        raise ValueError("Expected a portable lowercase plugin ID and API 1 or 2")
    if manifest.get("mode", "") not in ("", "automation", "companion") or not isinstance(manifest.get("permissions"), list):
        raise ValueError("Expected a Lua automation or companion manifest with a permissions list")
    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        raise ValueError("Set the plugin version in plugin.json")
    return plugin_id


def file_limit(key):
    if key == "main.lua":
        return 256 * 1024
    if key in ("plugin.json", "default.json"):
        return 2 * 1024 * 1024
    directory, _, name = key.partition("/")
    extension = {"images": ".png", "sounds": ".wav"}.get(directory)
    if not extension or not ASSET.fullmatch(name) or RESERVED.match(name) or not name.lower().endswith(extension):
        raise ValueError(f"Unsupported package path: {key}")
    return 1024 * 1024 if directory == "sounds" else 2 * 1024 * 1024


def validate_bundle(data, expected_id):
    if not 0 < len(data) <= LIMIT:
        raise ValueError("Package exceeds 16 MiB or is empty")
    def unique_keys(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("Duplicate JSON key")
        return result
    bundle = json.loads(data, object_pairs_hook=unique_keys)
    files = bundle["files"]
    if type(bundle["format"]) is not int or bundle["format"] != 1 or not isinstance(files, dict) or not 2 <= len(files) <= 128:
        raise ValueError("Invalid plugin package format")
    if not {"main.lua", "plugin.json"}.issubset(files) or len({key.lower() for key in files}) != len(files):
        raise ValueError("Missing required files or duplicate filenames")
    for key, value in files.items():
        limit = file_limit(key)
        if not isinstance(value, str) or len(value) > ((limit+2)//3)*4:
            raise ValueError(f"Invalid encoded file: {key}")
        decoded = base64.b64decode(value, validate=True)
        if not 0 < len(decoded) <= limit:
            raise ValueError(f"Unsupported file size: {key}")
        if key == "plugin.json" and plugin_id_from_manifest(json.loads(decoded, object_pairs_hook=unique_keys)) != expected_id:
            raise ValueError("Release manifest ID differs from the registration")
        if key == "default.json" and not isinstance(json.loads(decoded, object_pairs_hook=unique_keys), dict):
            raise ValueError("Expected a JSON object in default.json")


def pack(folder, output):
    manifest = json.loads((folder / "plugin.json").read_text(encoding="utf-8-sig"))
    plugin_id = plugin_id_from_manifest(manifest)
    paths = [Path("plugin.json"), Path("main.lua")]
    if (folder / "default.json").is_file():
        paths.append(Path("default.json"))
    for directory, extension in (("images", ".png"), ("sounds", ".wav")):
        for path in sorted((folder / directory).glob("*")):
            if not ASSET.fullmatch(path.name) or RESERVED.match(path.name) or path.suffix.lower() != extension:
                raise ValueError(f"Unsupported asset: {path}")
            paths.append(path.relative_to(folder))
    files = {}
    seen = set()
    size = 0
    for path in paths:
        source = folder / path
        key = path.as_posix()
        if source.is_symlink() or not source.resolve().is_relative_to(folder.resolve()) or key.lower() in seen:
            raise ValueError(f"Invalid or duplicate asset: {key}")
        seen.add(key.lower())
        limit = file_limit(key)
        if not 0 < source.stat().st_size <= limit:
            raise ValueError(f"Unsupported file size: {key}")
        files[key] = base64.b64encode(source.read_bytes()).decode("ascii")
        size += len(files[key])
        if size > LIMIT or len(files) > 128:
            raise ValueError("Package exceeds 16 MiB or 128 files")
    data = json.dumps({"format": 1, "files": files}, separators=(",", ":")).encode()
    validate_bundle(data, plugin_id)
    output.mkdir(parents=True, exist_ok=True)
    result = output / f"{plugin_id}.acplugin"
    result.write_bytes(data)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    print(pack(args.folder, args.output))

