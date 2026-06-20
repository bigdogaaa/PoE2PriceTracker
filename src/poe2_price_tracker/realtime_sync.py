# Copyright (c) 2026 大狗狗
# This file is part of this project and is licensed under the GNU GPL-3.0-only.
# See the LICENSE file for details.

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .db import RealtimePriceRecord, canonical_currency
from .secure_config import RedisCredentials, load_redis_credentials


RECORDS_HASH = "poe2:realtime:v1:records"
UPVOTES_HASH = "poe2:realtime:v1:upvotes"
LONG_TO_COMPACT = {
    "remote_key": "k",
    "item_name": "n",
    "item_match": "m",
    "item_known": "ik",
    "side": "s",
    "amount": "a",
    "currency": "c",
    "want_item": "w",
    "have_item": "h",
    "market_want_amount": "mwa",
    "market_have_amount": "mha",
    "user_want_amount": "uwa",
    "user_have_amount": "uha",
    "source": "src",
    "captured_at": "t",
    "confidence": "cf",
    "note": "no",
    "upvotes": "u",
}
COMPACT_TO_LONG = {value: key for key, value in LONG_TO_COMPACT.items()}


@dataclass(frozen=True)
class RemoteRealtimePrice:
    remote_key: str
    item_name: str
    item_match: str
    item_known: bool
    side: str
    amount: float
    currency: str
    want_item: str
    have_item: str
    market_want_amount: float
    market_have_amount: float
    user_want_amount: float
    user_have_amount: float
    source: str
    captured_at: str
    confidence: float
    raw_text: str
    screenshot_path: str
    note: str
    upvotes: int = 0


@dataclass(frozen=True)
class RealtimeSyncPage:
    records: list[RemoteRealtimePrice]
    cursor: str
    complete: bool
    scanned: int = 0


class RealtimeSyncClient:
    def __init__(self, credentials: RedisCredentials, service_url: str = ""):
        self.credentials = credentials
        self.service_url = service_url.strip().rstrip("/")

    @classmethod
    def from_config(cls, data_dir: Path, service_url: str = "") -> "RealtimeSyncClient":
        return cls(load_redis_credentials(data_dir), service_url=service_url)

    def can_read(self) -> bool:
        return bool(self.service_url) or self.credentials.has_read()

    def can_write(self) -> bool:
        return bool(self.service_url) or self.credentials.has_write()

    def _service_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.service_url:
            raise RuntimeError("价格共享服务未配置")
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.service_url + path,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "PoE2PriceTracker/1",
            },
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=12) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"价格共享服务请求失败：HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"价格共享服务请求失败：{exc}") from exc
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not parsed.get("ok", False):
            error = parsed.get("error", "返回格式异常") if isinstance(parsed, dict) else "返回格式异常"
            raise RuntimeError(f"价格共享服务返回错误：{error}")
        return parsed

    def _token(self, read_only: bool = False) -> str:
        if read_only and self.credentials.read_token:
            return self.credentials.read_token
        return self.credentials.write_token or self.credentials.read_token

    def _pipeline(self, commands: list[list[Any]], read_only: bool = False) -> list[Any]:
        url = self.credentials.url.rstrip("/") + "/pipeline"
        token = self._token(read_only=read_only)
        if not url or not token:
            raise RuntimeError("实时价格同步服务未配置")
        body = json.dumps(commands, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"实时价格同步请求失败：HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"实时价格同步请求失败：{exc}") from exc
        parsed = json.loads(payload)
        if not isinstance(parsed, list):
            raise RuntimeError("实时价格同步返回格式异常")
        results: list[Any] = []
        for item in parsed:
            if isinstance(item, dict) and item.get("error"):
                raise RuntimeError(f"实时价格同步返回错误：{item.get('error')}")
            results.append(item.get("result") if isinstance(item, dict) else item)
        return results

    @staticmethod
    def _payload_from_record(record: RealtimePriceRecord) -> str:
        payload = {
            "remote_key": record.remote_key,
            "item_name": record.item_name,
            "item_match": record.item_match,
            "item_known": record.item_known,
            "side": record.side,
            "amount": record.amount,
            "currency": canonical_currency(record.currency),
            "want_item": record.want_item,
            "have_item": record.have_item,
            "market_want_amount": record.market_want_amount,
            "market_have_amount": record.market_have_amount,
            "user_want_amount": record.user_want_amount,
            "user_have_amount": record.user_have_amount,
            "source": record.source,
            "captured_at": record.captured_at,
            "confidence": record.confidence,
            "note": record.note[:200],
            "upvotes": max(0, int(record.upvotes or 0)),
        }
        compact = {LONG_TO_COMPACT[key]: value for key, value in payload.items() if value not in {"", None}}
        return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    def submit_record(self, record: RealtimePriceRecord) -> None:
        if not record.remote_key:
            raise RuntimeError("实时价格记录缺少远端标识")
        if self.service_url:
            payload = json.loads(self._payload_from_record(record))
            self._service_request("POST", "/v1/realtime/submit", payload)
            return
        payload = self._payload_from_record(record)
        self._pipeline(
            [
                ["HSET", RECORDS_HASH, record.remote_key, payload],
                ["HSETNX", UPVOTES_HASH, record.remote_key, str(max(0, int(record.upvotes or 0)))],
            ]
        )

    def increment_upvote(self, remote_key: str) -> None:
        if not remote_key:
            return
        if self.service_url:
            self._service_request("POST", "/v1/realtime/upvote", {"remote_key": remote_key})
            return
        self._pipeline([["HINCRBY", UPVOTES_HASH, remote_key, "1"]])

    @staticmethod
    def _hash_items(value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items()}
        if not isinstance(value, list):
            return {}
        result: dict[str, str] = {}
        iterator = iter(value)
        for key in iterator:
            try:
                item = next(iterator)
            except StopIteration:
                break
            result[str(key)] = str(item)
        return result

    @staticmethod
    def _scan_items(value: Any) -> tuple[str, dict[str, str]]:
        if not isinstance(value, list) or len(value) < 2:
            return "0", {}
        cursor = str(value[0] or "0")
        return cursor, RealtimeSyncClient._hash_items(value[1])

    @staticmethod
    def _remote_from_payload(remote_key: str, payload: str, upvotes: int) -> RemoteRealtimePrice | None:
        try:
            raw = json.loads(payload)
            if isinstance(raw, dict) and any(key in raw for key in COMPACT_TO_LONG):
                raw = {COMPACT_TO_LONG.get(str(key), str(key)): value for key, value in raw.items()}
            amount = float(raw.get("amount", 0) or 0)
        except Exception:
            return None
        if not str(raw.get("item_name", "")).strip() or amount <= 0:
            return None
        return RemoteRealtimePrice(
            remote_key=str(raw.get("remote_key") or remote_key),
            item_name=str(raw.get("item_name", "")).strip(),
            item_match=str(raw.get("item_match", "")).strip(),
            item_known=bool(raw.get("item_known", False)),
            side=str(raw.get("side", "")).strip() or "未知",
            amount=amount,
            currency=canonical_currency(str(raw.get("currency", ""))),
            want_item=str(raw.get("want_item", "")),
            have_item=str(raw.get("have_item", "")),
            market_want_amount=float(raw.get("market_want_amount", 0) or 0),
            market_have_amount=float(raw.get("market_have_amount", 0) or 0),
            user_want_amount=float(raw.get("user_want_amount", 0) or 0),
            user_have_amount=float(raw.get("user_have_amount", 0) or 0),
            source=str(raw.get("source", "")).strip() or "实时价格导入",
            captured_at=str(raw.get("captured_at", "")).strip(),
            confidence=float(raw.get("confidence", 0) or 0),
            raw_text=str(raw.get("raw_text", "")),
            screenshot_path="",
            note=str(raw.get("note", "")),
            upvotes=max(0, int(raw.get("upvotes", upvotes) or 0)),
        )

    def fetch_all(self) -> list[RemoteRealtimePrice]:
        records: list[RemoteRealtimePrice] = []
        for page in self.fetch_pages():
            records.extend(page.records)
        records.sort(key=lambda item: (item.captured_at, item.remote_key), reverse=True)
        return records

    def fetch_pages(self, page_size: int = 500) -> Iterator[RealtimeSyncPage]:
        page_size = max(50, min(1000, int(page_size or 500)))
        if self.service_url:
            cursor = "0"
            first = True
            while True:
                query = urllib.parse.urlencode({"cursor": cursor, "limit": str(page_size)})
                try:
                    response = self._service_request("GET", f"/v1/realtime/records?{query}")
                except RuntimeError:
                    if not first:
                        raise
                    yield RealtimeSyncPage(self._fetch_all_from_service(), "0", True)
                    return
                first = False
                parsed = self._records_from_service_response(response)
                next_cursor = str(response.get("next_cursor", "0") or "0")
                complete = bool(response.get("complete", next_cursor == "0"))
                yield RealtimeSyncPage(parsed, next_cursor, complete, int(response.get("scanned", 0) or 0))
                if complete or next_cursor == "0":
                    return
                cursor = next_cursor
        else:
            cursor = "0"
            while True:
                results = self._pipeline([["HSCAN", RECORDS_HASH, cursor, "COUNT", str(page_size)]], read_only=True)
                next_cursor, records = self._scan_items(results[0] if results else [])
                keys = list(records.keys())
                upvotes_raw: dict[str, str] = {}
                if keys:
                    upvote_results = self._pipeline([["HMGET", UPVOTES_HASH, *keys]], read_only=True)
                    raw_values = upvote_results[0] if upvote_results else []
                    if isinstance(raw_values, list):
                        upvotes_raw = {
                            key: "0" if value is None else str(value)
                            for key, value in zip(keys, raw_values)
                        }
                parsed = self._records_from_hashes(records, upvotes_raw)
                yield RealtimeSyncPage(parsed, next_cursor, next_cursor == "0", len(records))
                if next_cursor == "0":
                    return
                cursor = next_cursor

    def _fetch_all_from_service(self) -> list[RemoteRealtimePrice]:
        response = self._service_request("GET", "/v1/realtime/records")
        return self._records_from_service_response(response)

    def _records_from_service_response(self, response: dict[str, Any]) -> list[RemoteRealtimePrice]:
        raw_records = response.get("records", [])
        parsed: list[RemoteRealtimePrice] = []
        if isinstance(raw_records, list):
            for item in raw_records:
                if not isinstance(item, dict):
                    continue
                remote_key = str(item.get("remote_key") or item.get("k") or "").strip()
                if not remote_key:
                    continue
                record = self._remote_from_payload(
                    remote_key,
                    json.dumps(item, ensure_ascii=False),
                    int(item.get("upvotes", item.get("u", 0)) or 0),
                )
                if record is not None:
                    parsed.append(record)
        parsed.sort(key=lambda item: (item.captured_at, item.remote_key), reverse=True)
        return parsed

    def _records_from_hashes(self, records: dict[str, str], upvotes_raw: dict[str, str]) -> list[RemoteRealtimePrice]:
        parsed: list[RemoteRealtimePrice] = []
        for remote_key, payload in records.items():
            try:
                upvotes = int(upvotes_raw.get(remote_key, "0") or 0)
            except ValueError:
                upvotes = 0
            record = self._remote_from_payload(remote_key, payload, upvotes)
            if record is not None:
                parsed.append(record)
        parsed.sort(key=lambda item: (item.captured_at, item.remote_key), reverse=True)
        return parsed
