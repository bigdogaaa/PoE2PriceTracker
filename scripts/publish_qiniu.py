from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def env_value(name: str, fallback: str = "") -> str:
    return os.environ.get(name, fallback).strip()


def public_url(domain: str, key: str) -> str:
    return f"{domain.rstrip('/')}/{key.lstrip('/')}"


def upload_file(bucket: str, key: str, path: Path, overwrite: bool) -> None:
    try:
        from qiniu import Auth, put_file_v2
    except Exception as exc:
        raise RuntimeError("Missing qiniu package. Install with: python -m pip install qiniu") from exc

    access_key = env_value("QINIU_ACCESS_KEY")
    secret_key = env_value("QINIU_SECRET_KEY")
    if not access_key or not secret_key:
        raise RuntimeError("QINIU_ACCESS_KEY and QINIU_SECRET_KEY are required")
    policy = {"insertOnly": 0 if overwrite else 1}
    token = Auth(access_key, secret_key).upload_token(bucket, key, 3600, policy)
    ret, info = put_file_v2(token, key, str(path), version="v2")
    if getattr(info, "status_code", 0) // 100 != 2:
        raise RuntimeError(f"Qiniu upload failed for {key}: {info}")
    if not isinstance(ret, dict) or ret.get("key") != key:
        raise RuntimeError(f"Qiniu upload returned unexpected result for {key}: {ret}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish PoE2PriceTracker release assets to Qiniu Kodo.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--exe", default="")
    parser.add_argument("--bucket", default=env_value("QINIU_BUCKET"))
    parser.add_argument("--domain", default=env_value("QINIU_DOMAIN"))
    parser.add_argument("--prefix", default=env_value("QINIU_PREFIX", "poe2-price-tracker"))
    parser.add_argument("--notes", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    exe = Path(args.exe) if args.exe else root / "dist" / f"PoE2PriceTracker-{args.version}.exe"
    if not exe.exists():
        raise FileNotFoundError(f"Build output not found: {exe}")
    if not args.bucket:
        raise RuntimeError("Qiniu bucket is required. Use --bucket or QINIU_BUCKET.")
    if not args.domain:
        raise RuntimeError("Qiniu public domain is required. Use --domain or QINIU_DOMAIN.")

    prefix = args.prefix.strip("/")
    version_key_prefix = f"{prefix}/releases/{args.version}" if prefix else f"releases/{args.version}"
    exe_key = f"{version_key_prefix}/{exe.name}"
    latest_key = f"{prefix}/latest.json" if prefix else "latest.json"
    version_latest_key = f"{version_key_prefix}/latest.json"

    manifest = {
        "version": args.version,
        "channel": "stable",
        "url": public_url(args.domain, exe_key),
        "download_url": public_url(args.domain, exe_key),
        "sha256": sha256(exe),
        "size": exe.stat().st_size,
        "release_date": date.today().isoformat(),
        "notes": args.notes,
        "mandatory": False,
    }

    release_dir = root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = release_dir / "latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    upload_file(args.bucket, exe_key, exe, overwrite=args.overwrite)
    upload_file(args.bucket, version_latest_key, manifest_path, overwrite=True)
    upload_file(args.bucket, latest_key, manifest_path, overwrite=True)

    print(f"Uploaded executable: {public_url(args.domain, exe_key)}")
    print(f"Uploaded manifest:   {public_url(args.domain, latest_key)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"publish_qiniu failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
