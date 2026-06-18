from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from . import __version__


@dataclass(frozen=True)
class UpdateInfo:
    available: bool
    current_version: str
    latest_version: str
    download_url: str
    sha256: str
    message: str
    manifest_location: str = ""
    size: int = 0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DownloadedUpdate:
    package_path: Path
    extract_dir: Path
    executable_path: Path | None
    message: str


def _read_manifest(location: str) -> dict:
    if location.startswith(("http://", "https://")):
        with urllib.request.urlopen(location, timeout=12) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    path = Path(location)
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _manifest_locations(value: str) -> list[str]:
    locations: list[str] = []
    for line in value.replace(",", "\n").replace(";", "\n").splitlines():
        location = line.strip()
        if location:
            locations.append(location)
    return locations


def _manifest_payload(manifest: dict) -> dict:
    payload = manifest.get("payload", manifest)
    return payload if isinstance(payload, dict) else manifest


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _resolve_download_url(manifest_location: str, download_url: str) -> str:
    if download_url.startswith(("http://", "https://")):
        return download_url
    if manifest_location.startswith(("http://", "https://")):
        return urljoin(manifest_location, download_url)
    return str((Path(manifest_location).parent / download_url).resolve())


def _download_name(url: str) -> str:
    parsed = urlparse(url)
    return Path(parsed.path).name or "update.zip"


def _download_file(url: str, target: Path, progress=None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith(("http://", "https://")):
        def report(block_count: int, block_size: int, total_size: int) -> None:
            if progress and total_size > 0:
                progress(min(100, int(block_count * block_size * 100 / total_size)), url)

        urllib.request.urlretrieve(url, target, reporthook=report)
        return
    shutil.copyfile(url, target)
    if progress:
        progress(100, url)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_executable(root: Path) -> Path | None:
    candidates = sorted(root.rglob("PoE2PriceTracker*.exe"))
    if candidates:
        return candidates[0]
    all_exe = sorted(root.rglob("*.exe"))
    return all_exe[0] if all_exe else None


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(1, 1000):
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Cannot find an available filename for {path}")


def _stage_executable_near_current(executable: Path, app_dir: Path) -> Path:
    target = app_dir / executable.name
    if executable.resolve() == target.resolve():
        return executable
    target = _next_available_path(target)
    shutil.copy2(executable, target)
    return target


def check_update(manifest_location: str) -> UpdateInfo:
    locations = _manifest_locations(manifest_location)
    if not locations:
        return UpdateInfo(False, __version__, __version__, "", "", "未配置更新地址。")
    errors: list[str] = []
    for location in locations:
        try:
            manifest = _manifest_payload(_read_manifest(location))
        except Exception as exc:
            errors.append(f"{location}: {exc}")
            continue

        latest = str(manifest.get("version", "0.0.0"))
        download_url = str(manifest.get("download_url") or manifest.get("url") or "")
        sha256 = str(manifest.get("sha256", ""))
        try:
            size = max(0, int(manifest.get("size", 0) or 0))
        except (TypeError, ValueError):
            size = 0
        raw_notes = manifest.get("notes", ())
        if isinstance(raw_notes, str):
            notes = (raw_notes,)
        elif isinstance(raw_notes, list):
            notes = tuple(str(item) for item in raw_notes if str(item).strip())
        else:
            notes = ()
        available = _version_tuple(latest) > _version_tuple(__version__)
        message = "发现新版本。" if available else "当前已是最新版本。"
        return UpdateInfo(available, __version__, latest, download_url, sha256, message, location, size, notes)
    return UpdateInfo(False, __version__, __version__, "", "", f"检查更新失败：{'; '.join(errors[:3])}")


def download_update(
    manifest_location: str,
    info: UpdateInfo,
    updates_dir: Path,
    progress=None,
    app_dir: Path | None = None,
) -> DownloadedUpdate:
    locations = _manifest_locations(manifest_location)
    location = info.manifest_location.strip() or (locations[0] if locations else "")
    url = _resolve_download_url(location, info.download_url.strip())
    version_dir = updates_dir / info.latest_version
    package_path = version_dir / _download_name(url)
    if version_dir.exists():
        shutil.rmtree(version_dir)
    version_dir.mkdir(parents=True, exist_ok=True)
    _download_file(url, package_path, progress)
    if info.size and package_path.stat().st_size != info.size:
        raise ValueError(f"更新包大小校验失败：期望 {info.size}，实际 {package_path.stat().st_size}")

    if info.sha256:
        actual = _sha256(package_path)
        if actual.lower() != info.sha256.lower():
            raise ValueError(f"更新包校验失败：期望 {info.sha256}，实际 {actual}")

    extract_dir = version_dir / "extracted"
    if package_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(package_path) as archive:
            archive.extractall(extract_dir)
    else:
        extract_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package_path, extract_dir / package_path.name)

    executable = _find_executable(extract_dir)
    if executable is not None and app_dir is not None:
        executable = _stage_executable_near_current(executable, app_dir)
    message = "更新已下载并校验完成。"
    if not executable:
        message = "更新已下载，但未在包内找到可执行文件。"
    return DownloadedUpdate(package_path, extract_dir, executable, message)
