from __future__ import annotations

import json
import os
import random
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager, nullcontext
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


RECORDS_HASH = "poe2:realtime:v1:records"
UPVOTES_HASH = "poe2:realtime:v1:upvotes"
MAX_BODY_BYTES = 24 * 1024
MAX_ITEM_NAME = 120
MAX_NOTE = 200
ACCESS_LOG = "/home/tcd/poe2-price-share/access.log"
SUBMISSION_LOG = "/home/tcd/poe2-price-share/submissions.log"
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
}
COMPACT_TO_LONG = {value: key for key, value in LONG_TO_COMPACT.items()}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def access_log(message: str) -> None:
    try:
        with open(env("POE2_PRICE_SHARE_ACCESS_LOG", ACCESS_LOG), "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def audit_log(name: str, payload: dict[str, Any]) -> None:
    paths = {
        "access": env("POE2_PRICE_SHARE_ACCESS_LOG", ACCESS_LOG),
        "submission": env("POE2_PRICE_SHARE_SUBMISSION_LOG", SUBMISSION_LOG),
    }
    path = paths.get(name, paths["access"])
    item = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **payload}
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


def record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "remote_key": record.get("remote_key", ""),
        "item_name": record.get("item_name", ""),
        "side": record.get("side", ""),
        "amount": record.get("amount", 0),
        "currency": record.get("currency", ""),
        "source": record.get("source", ""),
        "captured_at": record.get("captured_at", ""),
        "confidence": record.get("confidence", 0),
    }


def _read_dns_name(packet: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    original_offset = offset
    seen = 0
    while offset < len(packet):
        seen += 1
        if seen > 64:
            break
        length = packet[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                break
            pointer = ((length & 0x3F) << 8) | packet[offset + 1]
            if not jumped:
                original_offset = offset + 2
            offset = pointer
            jumped = True
            continue
        offset += 1
        labels.append(packet[offset : offset + length].decode("ascii", errors="ignore"))
        offset += length
    return ".".join(labels), original_offset if jumped else offset


def resolve_ipv4(hostname: str, dns_server: str = "223.5.5.5") -> str:
    query_id = random.randint(0, 65535)
    labels = hostname.strip(".").split(".")
    qname = b"".join(bytes([len(label)]) + label.encode("ascii") for label in labels) + b"\x00"
    packet = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.sendto(packet, (dns_server, 53))
        data, _addr = sock.recvfrom(512)
    if len(data) < 12:
        raise RuntimeError("DNS response too short")
    response_id, _flags, qdcount, ancount, _nscount, _arcount = struct.unpack("!HHHHHH", data[:12])
    if response_id != query_id or ancount <= 0:
        raise RuntimeError("DNS response has no answer")
    offset = 12
    for _ in range(qdcount):
        _name, offset = _read_dns_name(data, offset)
        offset += 4
    for _ in range(ancount):
        _name, offset = _read_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, rclass, _ttl, rdlength = struct.unpack("!HHIH", data[offset : offset + 10])
        offset += 10
        rdata = data[offset : offset + rdlength]
        offset += rdlength
        if rtype == 1 and rclass == 1 and rdlength == 4:
            return socket.inet_ntoa(rdata)
    raise RuntimeError("DNS response has no A record")


@contextmanager
def patched_getaddrinfo(hostname: str, ip: str):
    original = socket.getaddrinfo

    def replacement(host, port, family=0, type=0, proto=0, flags=0):
        if host == hostname:
            return original(ip, port, socket.AF_INET, type, proto, flags)
        return original(host, port, family, type, proto, flags)

    socket.getaddrinfo = replacement
    try:
        yield
    finally:
        socket.getaddrinfo = original


class UpstashClient:
    def __init__(self) -> None:
        self.url = env("UPSTASH_REDIS_REST_URL").rstrip("/")
        self.host = urllib.parse.urlparse(self.url).hostname or ""
        self.dns_server = env("POE2_UPSTASH_DNS_SERVER", "223.5.5.5")
        self.write_token = env("UPSTASH_REDIS_REST_TOKEN")
        self.read_token = env("UPSTASH_REDIS_REST_READ_TOKEN") or self.write_token
        if not self.url or not self.write_token:
            raise RuntimeError("UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are required")

    def pipeline(self, commands: list[list[Any]], read_only: bool = False) -> list[Any]:
        token = self.read_token if read_only else self.write_token
        request = urllib.request.Request(
            self.url + "/pipeline",
            data=json.dumps(commands, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            ip = resolve_ipv4(self.host, self.dns_server) if self.host else ""
            context = patched_getaddrinfo(self.host, ip) if ip else nullcontext()
            with context:
                response = urllib.request.urlopen(request, timeout=10)
            with response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Upstash HTTP {exc.code}: {detail}") from exc
        except Exception:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = response.read().decode("utf-8")
        parsed = json.loads(payload)
        if not isinstance(parsed, list):
            raise RuntimeError("Unexpected Upstash response")
        results: list[Any] = []
        for item in parsed:
            if isinstance(item, dict) and item.get("error"):
                raise RuntimeError(str(item["error"]))
            results.append(item.get("result") if isinstance(item, dict) else item)
        return results


UPSTASH = UpstashClient()


def hash_items(value: Any) -> dict[str, str]:
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


def scan_items(value: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(value, list) or len(value) < 2:
        return "0", {}
    return str(value[0] or "0"), hash_items(value[1])


def clean_text(value: Any, max_len: int) -> str:
    return " ".join(str(value or "").strip().split())[:max_len]


def clean_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def field(raw: dict[str, Any], name: str, default: Any = "") -> Any:
    return raw.get(name, raw.get(LONG_TO_COMPACT.get(name, ""), default))


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {LONG_TO_COMPACT[key]: value for key, value in record.items() if value not in {"", None}}


def normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    item_name = clean_text(field(raw, "item_name"), MAX_ITEM_NAME)
    amount = clean_float(field(raw, "amount"))
    currency = clean_text(field(raw, "currency"), 32)
    remote_key = clean_text(field(raw, "remote_key"), 96)
    if not remote_key or not item_name or amount <= 0 or not currency:
        raise ValueError("record requires remote_key, item_name, amount and currency")
    source = clean_text(field(raw, "source") or "实时价格导入", 32)
    if not source.startswith("实时价格导入"):
        source = "实时价格导入"
    return {
        "remote_key": remote_key,
        "item_name": item_name,
        "item_match": clean_text(field(raw, "item_match"), MAX_ITEM_NAME),
        "item_known": bool(field(raw, "item_known", False)),
        "side": clean_text(field(raw, "side") or "未知", 16),
        "amount": amount,
        "currency": currency,
        "want_item": clean_text(field(raw, "want_item"), MAX_ITEM_NAME),
        "have_item": clean_text(field(raw, "have_item"), MAX_ITEM_NAME),
        "market_want_amount": clean_float(field(raw, "market_want_amount")),
        "market_have_amount": clean_float(field(raw, "market_have_amount")),
        "user_want_amount": clean_float(field(raw, "user_want_amount")),
        "user_have_amount": clean_float(field(raw, "user_have_amount")),
        "source": source,
        "captured_at": clean_text(field(raw, "captured_at"), 40),
        "confidence": max(0.0, min(1.0, clean_float(field(raw, "confidence")))),
        "note": clean_text(field(raw, "note"), MAX_NOTE),
    }


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.events: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        values = [item for item in self.events.get(key, []) if item >= cutoff]
        if len(values) >= self.limit:
            self.events[key] = values
            return False
        values.append(now)
        self.events[key] = values
        return True


SUBMIT_LIMITER = RateLimiter(120, 3600)
VOTE_LIMITER = RateLimiter(600, 3600)
SYNC_LIMITER = RateLimiter(60, 3600)


class Handler(BaseHTTPRequestHandler):
    server_version = "PoE2PriceShare/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        message = fmt % args
        print(f"{self.client_address[0]} - {message}")
        audit_log("access", {"ip": self.client_address[0], "event": "http_log", "message": message})

    def _client_key(self) -> str:
        return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("invalid request body")
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("json object required")
        return data

    def do_GET(self) -> None:
        client_ip = self._client_key()
        try:
            access_log(f"GET {self.path} from {client_ip}")
            parsed_url = urllib.parse.urlparse(self.path)
            path = parsed_url.path
            if path == "/health":
                self._send_json(HTTPStatus.OK, {"ok": True})
                audit_log("access", {"ip": client_ip, "method": "GET", "path": path, "status": 200})
                return
            if path == "/v1/realtime/records":
                if not SYNC_LIMITER.allow(client_ip):
                    self._send_json(HTTPStatus.TOO_MANY_REQUESTS, {"ok": False, "error": "too many sync requests"})
                    audit_log("access", {"ip": client_ip, "method": "GET", "path": path, "status": 429})
                    return
                query = urllib.parse.parse_qs(parsed_url.query)
                if query:
                    cursor = clean_text(query.get("cursor", ["0"])[0], 32) or "0"
                    try:
                        limit = int(query.get("limit", ["500"])[0])
                    except (TypeError, ValueError):
                        limit = 500
                    limit = max(50, min(1000, limit))
                    scan_results = UPSTASH.pipeline(
                        [["HSCAN", RECORDS_HASH, cursor, "COUNT", str(limit)]],
                        read_only=True,
                    )
                    next_cursor, records = scan_items(scan_results[0] if scan_results else [])
                    keys = list(records.keys())
                    upvote_values: list[Any] = []
                    if keys:
                        upvote_results = UPSTASH.pipeline([["HMGET", UPVOTES_HASH, *keys]], read_only=True)
                        raw_upvotes = upvote_results[0] if upvote_results else []
                        if isinstance(raw_upvotes, list):
                            upvote_values = raw_upvotes
                    upvotes = {
                        key: "0" if value is None else str(value)
                        for key, value in zip(keys, upvote_values)
                    }
                    payload: list[dict[str, Any]] = []
                    for remote_key, item in records.items():
                        try:
                            record = json.loads(item)
                            if not isinstance(record, dict):
                                continue
                            record.setdefault("k", remote_key)
                            record["u"] = max(0, int(upvotes.get(remote_key, "0") or 0))
                            payload.append(record)
                        except Exception:
                            continue
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "records": payload,
                            "next_cursor": next_cursor,
                            "complete": next_cursor == "0",
                            "scanned": len(records),
                        },
                    )
                    audit_log(
                        "access",
                        {
                            "ip": client_ip,
                            "method": "GET",
                            "path": path,
                            "status": 200,
                            "records": len(payload),
                            "cursor": cursor,
                            "next_cursor": next_cursor,
                        },
                    )
                    return
                results = UPSTASH.pipeline([["HGETALL", RECORDS_HASH], ["HGETALL", UPVOTES_HASH]], read_only=True)
                records = hash_items(results[0] if results else {})
                upvotes = hash_items(results[1] if len(results) > 1 else {})
                payload: list[dict[str, Any]] = []
                for remote_key, item in records.items():
                    try:
                        record = json.loads(item)
                        if not isinstance(record, dict):
                            continue
                        record.setdefault("k", remote_key)
                        record["u"] = max(0, int(upvotes.get(remote_key, "0") or 0))
                        payload.append(record)
                    except Exception:
                        continue
                self._send_json(HTTPStatus.OK, {"ok": True, "records": payload})
                audit_log(
                    "access",
                    {"ip": client_ip, "method": "GET", "path": path, "status": 200, "records": len(payload)},
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            audit_log("access", {"ip": client_ip, "method": "GET", "path": path, "status": 404})
        except Exception as exc:
            audit_log(
                "access",
                {"ip": client_ip, "method": "GET", "path": self.path, "status": 500, "error": str(exc)[:300]},
            )
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal service error"})

    def do_POST(self) -> None:
        client_ip = self._client_key()
        try:
            access_log(f"POST {self.path} from {client_ip}")
            if self.path == "/v1/realtime/submit":
                if not SUBMIT_LIMITER.allow(client_ip):
                    self._send_json(HTTPStatus.TOO_MANY_REQUESTS, {"ok": False, "error": "too many submit requests"})
                    audit_log("access", {"ip": client_ip, "method": "POST", "path": self.path, "status": 429})
                    return
                record = normalize_record(self._read_json())
                compact = compact_record(record)
                payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
                UPSTASH.pipeline(
                    [
                        ["HSET", RECORDS_HASH, record["remote_key"], payload],
                        ["HSETNX", UPVOTES_HASH, record["remote_key"], "0"],
                    ]
                )
                self._send_json(HTTPStatus.OK, {"ok": True})
                audit_log("access", {"ip": client_ip, "method": "POST", "path": self.path, "status": 200})
                audit_log("submission", {"ip": client_ip, "event": "submit", "record": record_summary(record)})
                return
            if self.path == "/v1/realtime/upvote":
                if not VOTE_LIMITER.allow(client_ip):
                    self._send_json(HTTPStatus.TOO_MANY_REQUESTS, {"ok": False, "error": "too many vote requests"})
                    audit_log("access", {"ip": client_ip, "method": "POST", "path": self.path, "status": 429})
                    return
                remote_key = clean_text(self._read_json().get("remote_key"), 96)
                if not remote_key:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "remote_key required"})
                    audit_log("access", {"ip": client_ip, "method": "POST", "path": self.path, "status": 400})
                    return
                UPSTASH.pipeline([["HINCRBY", UPVOTES_HASH, remote_key, "1"]])
                self._send_json(HTTPStatus.OK, {"ok": True})
                audit_log("access", {"ip": client_ip, "method": "POST", "path": self.path, "status": 200})
                audit_log("submission", {"ip": client_ip, "event": "upvote", "remote_key": remote_key})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            audit_log("access", {"ip": client_ip, "method": "POST", "path": self.path, "status": 404})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            audit_log(
                "access",
                {"ip": client_ip, "method": "POST", "path": self.path, "status": 400, "error": str(exc)[:300]},
            )
        except Exception as exc:
            audit_log(
                "access",
                {"ip": client_ip, "method": "POST", "path": self.path, "status": 500, "error": str(exc)[:300]},
            )
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal service error"})


def main() -> None:
    host = env("POE2_PRICE_SHARE_HOST", "0.0.0.0")
    port = int(env("POE2_PRICE_SHARE_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"PoE2 price share service listening on {host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
