"""Build the public index from registrations and stable GitHub release assets."""
import argparse
import base64
import hashlib
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from functools import lru_cache
from urllib.request import Request, urlopen

from package import ID, LIMIT, RESERVED, validate_bundle

ROOT = Path(__file__).resolve().parents[1]
REPO = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}")
TAG = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,95}")


def listing(path):
    source = ET.parse(path).getroot()
    pid, repo = source.get("id", ""), source.get("repo", "")
    if source.tag != "plugin" or pid != path.stem or not ID.fullmatch(pid) or RESERVED.match(pid) or not REPO.fullmatch(repo):
        raise ValueError(f"Invalid ID or GitHub repository: {path}")
    result = ET.Element("plugin", id=pid, repository=f"https://github.com/{repo}")
    for key, limit in (("name", 80), ("developer", 80), ("description", 600)):
        value = (source.findtext(key) or "").strip()
        if not 0 < len(value) <= limit:
            raise ValueError(f"Invalid {key} for {pid}")
        ET.SubElement(result, key).text = value
    logo = source.findtext("logo")
    if logo:
        if logo != f"{pid}.png":
            raise ValueError(f"Name the logo {pid}.png")
        data = (path.parent / logo).read_bytes()
        if not 24 <= len(data) <= 65536 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or not all(0 < n <= 256 for n in struct.unpack(">II", data[16:24])):
            raise ValueError(f"Expected a PNG up to 256x256 and 64 KiB for {pid}")
        ET.SubElement(result, "logo").text = base64.b64encode(data).decode()
    return result, repo


@lru_cache(maxsize=None)
def release_info(repo):
    # Only send the Actions token to the fixed GitHub API origin.
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ACUnrealPlugins"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    base = f"https://api.github.com/repos/{repo}"
    if repo == "Thwargle/ACE":
        # Game releases and official plugin releases have independent lifecycles.
        # Select the latest published plugin tag, even if a newer source build is still running.
        page = 1
        latest = None
        while True:
            with urlopen(Request(f"{base}/releases?per_page=100&page={page}", headers=headers), timeout=20) as response:
                releases = json.load(response)
            for item in releases:
                if not item["draft"] and not item["prerelease"] and re.fullmatch(r"plugins-[a-f0-9]{40}", item["tag_name"]):
                    if latest is None or item["published_at"] > latest["published_at"]:
                        latest = item
            if len(releases) < 100:
                if latest is None:
                    raise ValueError("No published official plugin release")
                return latest
            page += 1
    with urlopen(Request(f"{base}/releases/latest", headers=headers), timeout=20) as response:
        return json.load(response)


def release(result, repo, previous):
    info = release_info(repo)
    tag = info["tag_name"]
    if info["prerelease"] or info["draft"] or not TAG.fullmatch(tag):
        raise ValueError("Expected a stable release with a portable tag")
    filename = result.get("id") + ".acplugin"
    asset = next((a for a in info["assets"] if a["name"] == filename and a["state"] == "uploaded"), None)
    link = f"https://github.com/{repo}/releases/download/{tag}/{filename}"
    if not asset or asset["browser_download_url"] != link or not 0 < asset["size"] <= LIMIT:
        raise ValueError(f"Missing or oversized {filename}")
    digest = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError(f"No GitHub SHA-256 digest for {filename}")
    version = previous.get("version") if previous is not None and previous.get("sha256") == digest[7:] else None
    if not version:
        with urlopen(Request(link, headers={"User-Agent": "ACUnrealPlugins"}), timeout=30) as response:
            data = response.read(asset["size"] + 1)
        if len(data) != asset["size"] or hashlib.sha256(data).hexdigest() != digest[7:]:
            raise ValueError(f"Release asset failed integrity verification: {filename}")
        version = validate_bundle(data, result.get("id"), official=repo == "Thwargle/ACE")
    ET.SubElement(result, "release", tag=tag, version=version, download=link, sha256=digest[7:], bytes=str(asset["size"]))


def build(strict=False):
    output = ROOT / "catalog.xml"
    old = {e.get("id"): e for e in ET.parse(output).getroot()} if output.exists() else {}
    catalog = ET.Element("catalog", schema="1")
    for path in sorted((ROOT / "registry").glob("*.xml")):
        entry, repo = listing(path)
        previous = old.get(entry.get("id"))
        try:
            known = previous.find("release") if previous is not None and previous.get("repository") == entry.get("repository") and not strict else None
            release(entry, repo, known)
        except Exception as error:
            if strict or previous is None or previous.get("repository") != entry.get("repository") or previous.find("release") is None:
                raise
            print(f"{repo}: keeping previous release ({error})", file=sys.stderr)
            entry.append(previous.find("release"))
        catalog.append(entry)
    ET.indent(catalog)
    data = ET.tostring(catalog, encoding="utf-8", xml_declaration=True) + b"\n"
    if len(data) > 4*1024*1024 or len(catalog) > 512:
        raise ValueError("Catalog exceeds client capacity")
    if not strict:
        output.write_bytes(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate registrations and live releases without writing")
    build(parser.parse_args().check)

