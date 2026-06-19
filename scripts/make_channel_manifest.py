from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_urls(urls: list[str]) -> list[str]:
    result: list[str] = []
    for url in urls:
        cleaned = url.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an update manifest with automatic downloads and manual download pages."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--asset", required=True, help="Local release package used for size and SHA256.")
    parser.add_argument("--primary-url", required=True, help="Automatic download URL, for example GitHub release asset.")
    parser.add_argument("--mirror-url", action="append", default=[], help="Fallback package URL.")
    parser.add_argument("--manual-url", action="append", default=[], help="Manual download page, for example Quark share.")
    parser.add_argument("--output", default="release/latest.json")
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--notes", action="append", default=[])
    parser.add_argument("--mandatory", action="store_true")
    args = parser.parse_args()

    asset = Path(args.asset)
    if not asset.exists():
        raise FileNotFoundError(asset)
    urls = unique_urls([args.primary_url, *args.mirror_url])
    if not urls:
        raise ValueError("at least one download URL is required")

    manifest = {
        "version": args.version,
        "channel": args.channel,
        "url": urls[0],
        "download_url": urls[0],
        "download_urls": urls,
        "manual_urls": unique_urls(args.manual_url),
        "sha256": sha256(asset),
        "size": asset.stat().st_size,
        "release_date": date.today().isoformat(),
        "notes": args.notes,
        "mandatory": bool(args.mandatory),
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {output}")
    print(f"Primary:  {urls[0]}")
    if len(urls) > 1:
        print(f"Mirrors:  {len(urls) - 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
