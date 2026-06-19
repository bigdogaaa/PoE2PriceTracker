from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path


DEFAULT_REPO = "bigdogaaa/PoE2PriceTracker"
DEFAULT_GITEE_REPO = "BiGDoGaaa/poe2pricetracker_version_info"
DEFAULT_GITEE_BRANCH = "master"
DEFAULT_GITEE_PATH = "latest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_urls(urls: list[str]) -> list[str]:
    result: list[str] = []
    for url in urls:
        cleaned = str(url or "").strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def read_project_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError("Cannot read version from pyproject.toml")
    return match.group(1)


def read_notes(values: list[str], files: list[str]) -> list[str]:
    notes = [item.strip() for item in values if item.strip()]
    for file_name in files:
        path = Path(file_name)
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line:
                notes.append(line)
    return notes


def github_request(url: str, token: str, method: str = "GET", payload=None, headers: dict | None = None):
    request_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "poe2-price-tracker-release",
    }
    if headers:
        request_headers.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True).encode("ascii")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
        return json.loads(body.decode("utf-8")) if body else None


def github_release(repo: str, token: str, version: str, notes: list[str], asset: Path, manifest: Path) -> str:
    tag = f"v{version}"
    api_base = f"https://api.github.com/repos/{repo}"
    try:
        release = github_request(f"{api_base}/releases/tags/{tag}", token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        body = f"## {version}\n\n" + "".join(f"- {note}\n" for note in notes)
        release = github_request(
            f"{api_base}/releases",
            token,
            method="POST",
            payload={"tag_name": tag, "name": tag, "body": body, "draft": False, "prerelease": False},
        )

    release_id = release["id"]
    body = f"## {version}\n\n" + "".join(f"- {note}\n" for note in notes)
    release = github_request(
        f"{api_base}/releases/{release_id}",
        token,
        method="PATCH",
        payload={"name": tag, "body": body},
    )

    existing = {item["name"]: item for item in release.get("assets", [])}
    for path in (asset, manifest):
        if path.name in existing:
            github_request(existing[path.name]["url"], token, method="DELETE")
        upload_url = release["upload_url"].split("{", 1)[0]
        upload_url += "?" + urllib.parse.urlencode({"name": path.name})
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        request = urllib.request.Request(
            upload_url,
            data=data,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "poe2-price-tracker-release",
                "Content-Type": content_type,
                "Content-Length": str(len(data)),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            response.read()
        print(f"GitHub asset uploaded: {path.name}")
    return release.get("html_url", "")


def gitee_request(repo: str, token: str, path: str, method: str = "GET", payload: dict | None = None):
    encoded_path = urllib.parse.quote(path.strip("/"), safe="")
    url = f"https://gitee.com/api/v5/repos/{repo}/contents/{encoded_path}"
    data = None
    headers = {"User-Agent": "poe2-price-tracker-release"}
    if payload is None:
        url += "?" + urllib.parse.urlencode({"access_token": token})
    else:
        payload = dict(payload)
        payload["access_token"] = token
        data = urllib.parse.urlencode(payload).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
        return json.loads(body.decode("utf-8")) if body else None


def gitee_raw_url(repo: str, branch: str, path: str) -> str:
    return f"https://gitee.com/{repo}/raw/{branch}/{path.strip('/')}"


def gitee_publish_latest(repo: str, token: str, branch: str, path: str, manifest: Path, version: str) -> str:
    if not token:
        raise RuntimeError("GITEE_TOKEN is required unless --skip-gitee is used")
    content = base64.b64encode(manifest.read_bytes()).decode("ascii")
    payload = {
        "branch": branch,
        "content": content,
        "message": f"Update latest.json for v{version}",
    }
    try:
        current = gitee_request(repo, token, path)
        sha = str((current or {}).get("sha", "")).strip()
        if sha:
            payload["sha"] = sha
        gitee_request(repo, token, path, method="PUT", payload=payload)
        print(f"Gitee manifest updated: {path}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        gitee_request(repo, token, path, method="POST", payload=payload)
        print(f"Gitee manifest created: {path}")
    return gitee_raw_url(repo, branch, path)


def quark_url_from_command(command: str, asset: Path, version: str) -> str:
    env = os.environ.copy()
    env["POE2_RELEASE_ASSET"] = str(asset)
    env["POE2_RELEASE_VERSION"] = version
    completed = subprocess.run(command, shell=True, text=True, capture_output=True, env=env)
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise RuntimeError(f"Quark upload command failed with exit code {completed.returncode}")
    output = completed.stdout + "\n" + completed.stderr
    matches = re.findall(r"https?://\S+", output)
    if not matches:
        raise RuntimeError("Quark upload command did not print a URL")
    return matches[-1].strip()


def write_manifest(
    path: Path,
    version: str,
    asset: Path,
    download_url: str,
    manual_urls: list[str],
    notes: list[str],
    channel: str,
) -> None:
    urls = unique_urls([download_url])
    manifest = {
        "version": version,
        "channel": channel,
        "url": urls[0],
        "download_url": urls[0],
        "download_urls": urls,
        "manual_urls": unique_urls(manual_urls),
        "sha256": sha256(asset),
        "size": asset.stat().st_size,
        "release_date": date.today().isoformat(),
        "notes": notes,
        "mandatory": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Publish release assets to GitHub, Gitee manifest, and Quark.")
    parser.add_argument("--version", default="")
    parser.add_argument("--asset", default="")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO))
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--skip-github", action="store_true")
    parser.add_argument("--gitee-repo", default=os.environ.get("GITEE_REPOSITORY", DEFAULT_GITEE_REPO))
    parser.add_argument("--gitee-token", default=os.environ.get("GITEE_TOKEN", ""))
    parser.add_argument("--gitee-branch", default=os.environ.get("GITEE_BRANCH", DEFAULT_GITEE_BRANCH))
    parser.add_argument("--gitee-path", default=os.environ.get("GITEE_PATH", DEFAULT_GITEE_PATH))
    parser.add_argument("--skip-gitee", action="store_true")
    parser.add_argument("--quark-url", action="append", default=[])
    parser.add_argument("--quark-upload-command", default=os.environ.get("QUARK_UPLOAD_COMMAND", ""))
    parser.add_argument("--notes", action="append", default=[])
    parser.add_argument("--notes-file", action="append", default=[], help="UTF-8 text file, one release note per line.")
    parser.add_argument("--channel", default="stable")
    args = parser.parse_args()

    version = args.version.strip() or read_project_version(root)
    asset = Path(args.asset) if args.asset else root / "dist" / f"PoE2PriceTracker-{version}.exe"
    if not asset.exists():
        raise FileNotFoundError(asset)

    quark_urls = list(args.quark_url)
    if args.quark_upload_command.strip():
        quark_urls.insert(0, quark_url_from_command(args.quark_upload_command, asset, version))

    notes = read_notes(args.notes, args.notes_file)
    github_download_url = f"https://github.com/{args.repo}/releases/download/v{version}/{asset.name}"
    manifest = root / "release" / "latest.json"
    write_manifest(manifest, version, asset, github_download_url, quark_urls, notes, args.channel)
    print(f"Manifest created: {manifest}")

    if not args.skip_github:
        if not args.github_token:
            raise RuntimeError("GITHUB_TOKEN is required unless --skip-github is used")
        url = github_release(args.repo, args.github_token, version, notes, asset, manifest)
        print(f"GitHub release: {url}")

    if not args.skip_gitee:
        gitee_url = gitee_publish_latest(
            args.gitee_repo,
            args.gitee_token,
            args.gitee_branch,
            args.gitee_path,
            manifest,
            version,
        )
        print(f"Gitee latest: {gitee_url}")

    if quark_urls:
        print(f"Quark manual URL: {quark_urls[0]}")
    else:
        print("Quark manual URL: not configured")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"publish_release_channels failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
