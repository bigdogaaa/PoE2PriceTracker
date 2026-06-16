from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__


@dataclass(frozen=True)
class UpdateInfo:
    available: bool
    current_version: str
    latest_version: str
    download_url: str
    message: str


def _read_manifest(location: str) -> dict:
    if location.startswith(("http://", "https://")):
        with urllib.request.urlopen(location, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    path = Path(location)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_update(manifest_location: str) -> UpdateInfo:
    if not manifest_location.strip():
        return UpdateInfo(
            False,
            __version__,
            __version__,
            "",
            "未配置 update_manifest。可以在配置文件中填本地 latest.json 或 HTTP(S) 地址。",
        )
    try:
        manifest = _read_manifest(manifest_location.strip())
    except Exception as exc:
        return UpdateInfo(False, __version__, __version__, "", f"检查更新失败：{exc}")

    latest = str(manifest.get("version", "0.0.0"))
    download_url = str(manifest.get("download_url", ""))
    available = _version_tuple(latest) > _version_tuple(__version__)
    message = "发现新版本。" if available else "当前已是最新版本。"
    return UpdateInfo(available, __version__, latest, download_url, message)
