"""Install a pinned official Windows EnergyPlus portable release locally."""
import hashlib
import json
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "26.2.0"
ASSET = "EnergyPlus-26.2.0-4bd7a1f26f-Windows-x86_64.zip"


def main():
    root = ROOT / ".runtime" / "energyplus"
    root.mkdir(parents=True, exist_ok=True)
    url = f"https://api.github.com/repos/NatLabRockies/EnergyPlus/releases/tags/v{VERSION}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "smart-home-energyplus"}), timeout=30) as r:
        release = json.load(r)
    asset = next(a for a in release["assets"] if a["name"] == ASSET)
    archive = root / ASSET
    chunk_size = 8 * 1024 * 1024
    if not archive.exists() or archive.stat().st_size != asset["size"]:
        with archive.open("wb") as stream:
            stream.truncate(asset["size"])

        def fetch(index):
            start = index * chunk_size
            end = min(start + chunk_size, asset["size"]) - 1
            req = urllib.request.Request(asset["browser_download_url"] + f"?download=1&range={start}-{end}",
                                         headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=45) as response:
                if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{asset['size']}":
                    raise ValueError("Release download range mismatch")
                data = response.read()
            if len(data) != end - start + 1:
                raise ValueError("Truncated release range")
            with archive.open("r+b") as stream:
                stream.seek(start)
                stream.write(data)
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(fetch, range((asset["size"] + chunk_size - 1) // chunk_size)))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if asset.get("digest") and asset["digest"] != "sha256:" + digest:
        raise ValueError("Official release digest mismatch")
    destination = (root / VERSION).resolve()
    destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not (destination / name).resolve().is_relative_to(destination):
                raise ValueError("Archive path escapes runtime root")
        bundle.extractall(destination)
    manifest = {"version": VERSION, "release": "v" + VERSION, "asset": ASSET,
                "url": asset["browser_download_url"], "sha256": digest,
                "official_asset_digest": asset.get("digest"), "directory": str(destination)}
    (root / "installation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
