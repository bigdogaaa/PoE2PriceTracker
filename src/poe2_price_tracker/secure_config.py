# Copyright (c) 2026 大狗狗
# This file is part of this project and is licensed under the GNU GPL-3.0-only.
# See the LICENSE file for details.

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


CRYPTPROTECT_UI_FORBIDDEN = 0x01


@dataclass(frozen=True)
class RedisCredentials:
    url: str = ""
    write_token: str = ""
    read_token: str = ""

    def has_read(self) -> bool:
        return bool(self.url.strip() and (self.read_token.strip() or self.write_token.strip()))

    def has_write(self) -> bool:
        return bool(self.url.strip() and self.write_token.strip())


def _to_blob(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))


def _blob_to_bytes(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _entropy() -> DATA_BLOB:
    return _to_blob(b"PoE2PriceTracker.RedisSync.v1")


def protect_text(value: str) -> str:
    raw = value.encode("utf-8")
    input_blob = _to_blob(raw)
    entropy = _entropy()
    output_blob = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise OSError("Windows DPAPI 加密失败")
    return base64.b64encode(_blob_to_bytes(output_blob)).decode("ascii")


def unprotect_text(value: str) -> str:
    raw = base64.b64decode(value.encode("ascii"))
    input_blob = _to_blob(raw)
    entropy = _entropy()
    output_blob = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise OSError("Windows DPAPI 解密失败")
    return _blob_to_bytes(output_blob).decode("utf-8")


def redis_config_path(data_dir: Path) -> Path:
    return data_dir / "redis_sync.secure.json"


def save_redis_credentials(data_dir: Path, credentials: RedisCredentials) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": protect_text(credentials.url),
        "write_token": protect_text(credentials.write_token),
        "read_token": protect_text(credentials.read_token),
    }
    redis_config_path(data_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_redis_credentials(data_dir: Path) -> RedisCredentials:
    env = RedisCredentials(
        url=os.environ.get("POE2_UPSTASH_REDIS_REST_URL", "").strip()
        or os.environ.get("UPSTASH_REDIS_REST_URL", "").strip(),
        write_token=os.environ.get("POE2_UPSTASH_REDIS_REST_TOKEN", "").strip()
        or os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip(),
        read_token=os.environ.get("POE2_UPSTASH_REDIS_REST_READ_TOKEN", "").strip()
        or os.environ.get("UPSTASH_REDIS_REST_READ_TOKEN", "").strip(),
    )
    path = redis_config_path(data_dir)
    if not path.exists():
        return env
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        stored = RedisCredentials(
            url=unprotect_text(str(raw.get("url", ""))) if raw.get("url") else "",
            write_token=unprotect_text(str(raw.get("write_token", ""))) if raw.get("write_token") else "",
            read_token=unprotect_text(str(raw.get("read_token", ""))) if raw.get("read_token") else "",
        )
    except Exception:
        return env
    return RedisCredentials(
        url=stored.url or env.url,
        write_token=stored.write_token or env.write_token,
        read_token=stored.read_token or env.read_token,
    )
