from __future__ import annotations

import json
import os
import random
import socket
import struct
import threading
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
SECURITY_STATE_FILE = "/opt/poe2-price-share/security_state.json"
ALLOWED_PATHS = {
    "/health",
    "/v1/realtime/records",
    "/v1/realtime/submit",
    "/v1/realtime/upvote",
}
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


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name, "1" if default else "0").lower()
    return value in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


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


class IpGuard:
    def __init__(
        self,
        grace: int,
        ban_seconds: int,
        offense_window_seconds: int,
        unknown_path_threshold: int,
        unknown_path_window_seconds: int,
        permanent_offense_threshold: int,
        state_file: str,
    ) -> None:
        self.grace = max(0, grace)
        self.ban_seconds = max(60, ban_seconds)
        self.offense_window_seconds = max(60, offense_window_seconds)
        self.unknown_path_threshold = max(1, unknown_path_threshold)
        self.unknown_path_window_seconds = max(10, unknown_path_window_seconds)
        self.permanent_offense_threshold = max(self.grace + 2, permanent_offense_threshold)
        self.state_file = state_file
        self.offenses: dict[str, list[float]] = {}
        self.offense_totals: dict[str, int] = {}
        self.unknown_path_events: dict[str, list[float]] = {}
        self.banned_until: dict[str, float] = {}
        self.permanent_bans: dict[str, float] = {}
        self.lock = threading.Lock()
        self._load_state()

    def _load_state(self) -> None:
        try:
            with open(self.state_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return
        except Exception as exc:
            audit_log("access", {"event": "ip_guard_state_load_failed", "error": str(exc)[:300]})
            return
        if not isinstance(data, dict):
            return
        now = time.time()
        try:
            raw_offenses = data.get("offenses", {})
            if isinstance(raw_offenses, dict):
                self.offenses = {
                    str(ip): [float(item) for item in values if float(item) > 0][-100:]
                    for ip, values in raw_offenses.items()
                    if isinstance(values, list)
                }
            raw_totals = data.get("offense_totals", {})
            if isinstance(raw_totals, dict):
                self.offense_totals = {str(ip): max(0, int(value)) for ip, value in raw_totals.items()}
            raw_unknown = data.get("unknown_path_events", {})
            if isinstance(raw_unknown, dict):
                cutoff = now - self.unknown_path_window_seconds
                self.unknown_path_events = {
                    str(ip): [float(item) for item in values if float(item) >= cutoff]
                    for ip, values in raw_unknown.items()
                    if isinstance(values, list)
                }
            raw_banned = data.get("banned_until", {})
            if isinstance(raw_banned, dict):
                self.banned_until = {
                    str(ip): float(until)
                    for ip, until in raw_banned.items()
                    if float(until) > now
                }
            raw_permanent = data.get("permanent_bans", {})
            if isinstance(raw_permanent, dict):
                self.permanent_bans = {str(ip): float(ts or now) for ip, ts in raw_permanent.items()}
            elif isinstance(raw_permanent, list):
                self.permanent_bans = {str(ip): now for ip in raw_permanent}
        except Exception as exc:
            audit_log("access", {"event": "ip_guard_state_parse_failed", "error": str(exc)[:300]})

    def _save_state_locked(self) -> None:
        now = time.time()
        self.banned_until = {ip: until for ip, until in self.banned_until.items() if until > now}
        unknown_cutoff = now - self.unknown_path_window_seconds
        self.unknown_path_events = {
            ip: [item for item in values if item >= unknown_cutoff]
            for ip, values in self.unknown_path_events.items()
            if values
        }
        payload = {
            "version": 1,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "grace": self.grace,
            "ban_seconds": self.ban_seconds,
            "unknown_path_threshold": self.unknown_path_threshold,
            "unknown_path_window_seconds": self.unknown_path_window_seconds,
            "permanent_offense_threshold": self.permanent_offense_threshold,
            "offense_totals": self.offense_totals,
            "offenses": {ip: values[-100:] for ip, values in self.offenses.items()},
            "unknown_path_events": self.unknown_path_events,
            "banned_until": self.banned_until,
            "permanent_bans": self.permanent_bans,
        }
        try:
            directory = os.path.dirname(self.state_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temp_path = f"{self.state_file}.tmp"
            with open(temp_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(temp_path, self.state_file)
        except Exception as exc:
            audit_log("access", {"event": "ip_guard_state_save_failed", "error": str(exc)[:300]})

    def is_banned(self, ip: str) -> tuple[bool, int, bool]:
        if not ip or ip in {"127.0.0.1", "::1"}:
            return False, 0, False
        now = time.time()
        with self.lock:
            if ip in self.permanent_bans:
                return True, 0, True
            until = self.banned_until.get(ip, 0)
            if until > now:
                return True, max(1, int(until - now)), False
            if until:
                self.banned_until.pop(ip, None)
                self._save_state_locked()
            return False, 0, False

    def record_unknown_path(self, ip: str, path: str) -> tuple[bool, int, int, int, bool]:
        """Record a non-whitelisted path hit. More than N hits in the short window is one offense."""
        if not ip or ip in {"127.0.0.1", "::1"}:
            return False, 0, 0, 0, False
        now = time.time()
        unknown_cutoff = now - self.unknown_path_window_seconds
        with self.lock:
            if ip in self.permanent_bans:
                return True, 0, self.offense_totals.get(ip, self.permanent_offense_threshold), 0, True
            events = [item for item in self.unknown_path_events.get(ip, []) if item >= unknown_cutoff]
            events.append(now)
            count_in_window = len(events)
            if count_in_window <= self.unknown_path_threshold:
                self.unknown_path_events[ip] = events
                self._save_state_locked()
                audit_log(
                    "access",
                    {
                        "ip": ip,
                        "event": "unknown_path_seen",
                        "path": path[:200],
                        "count": count_in_window,
                        "threshold": self.unknown_path_threshold,
                        "window_seconds": self.unknown_path_window_seconds,
                    },
                )
                return False, 0, self.offense_totals.get(ip, 0), count_in_window, False

            self.unknown_path_events[ip] = []
            cutoff = now - self.offense_window_seconds
            values = [item for item in self.offenses.get(ip, []) if item >= cutoff]
            values.append(now)
            self.offenses[ip] = values
            offense_total = self.offense_totals.get(ip, 0) + 1
            self.offense_totals[ip] = offense_total
            if offense_total >= self.permanent_offense_threshold:
                self.permanent_bans[ip] = now
                self.banned_until.pop(ip, None)
                self._save_state_locked()
                audit_log(
                    "access",
                    {
                        "ip": ip,
                        "event": "ip_permanent_ban",
                        "reason": "unknown_path_burst",
                        "detail": path[:200],
                        "unknown_path_count": count_in_window,
                        "offenses": offense_total,
                    },
                )
                return True, 0, offense_total, count_in_window, True
            if offense_total > self.grace:
                until = now + self.ban_seconds
                self.banned_until[ip] = until
                self._save_state_locked()
                audit_log(
                    "access",
                    {
                        "ip": ip,
                        "event": "ip_ban",
                        "reason": "unknown_path_burst",
                        "detail": path[:200],
                        "unknown_path_count": count_in_window,
                        "offenses": offense_total,
                        "ban_seconds": self.ban_seconds,
                    },
                )
                return True, self.ban_seconds, offense_total, count_in_window, False
            self._save_state_locked()
            audit_log(
                "access",
                {
                    "ip": ip,
                    "event": "ip_offense",
                    "reason": "unknown_path_burst",
                    "detail": path[:200],
                    "unknown_path_count": count_in_window,
                    "offenses": offense_total,
                    "grace": self.grace,
                },
            )
            return False, 0, offense_total, count_in_window, False


SUBMIT_LIMITER = RateLimiter(120, 3600)
VOTE_LIMITER = RateLimiter(600, 3600)
SYNC_LIMITER = RateLimiter(60, 3600)
IP_GUARD = IpGuard(
    env_int("POE2_PRICE_SHARE_IP_OFFENSE_GRACE", 1),
    env_int("POE2_PRICE_SHARE_IP_BAN_SECONDS", 3600),
    env_int("POE2_PRICE_SHARE_IP_OFFENSE_WINDOW_SECONDS", 3600),
    env_int("POE2_PRICE_SHARE_UNKNOWN_PATH_THRESHOLD", 3),
    env_int("POE2_PRICE_SHARE_UNKNOWN_PATH_WINDOW_SECONDS", 60),
    env_int("POE2_PRICE_SHARE_PERMANENT_OFFENSE_THRESHOLD", 3),
    env("POE2_PRICE_SHARE_SECURITY_STATE", SECURITY_STATE_FILE),
)


class Handler(BaseHTTPRequestHandler):
    server_version = "PoE2PriceShare/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        message = fmt % args
        print(f"{self.client_address[0]} - {message}")
        audit_log("access", {"ip": self.client_address[0], "event": "http_log", "message": message})

    def _client_key(self) -> str:
        if env_bool("POE2_PRICE_SHARE_TRUST_X_FORWARDED_FOR", False):
            return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        return self.client_address[0]

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_if_banned(self, client_ip: str, method: str, path: str) -> bool:
        banned, seconds, permanent = IP_GUARD.is_banned(client_ip)
        if not banned:
            return False
        payload = {"ok": False, "error": "ip blocked", "retry_after": seconds, "permanent": permanent}
        self._send_json(HTTPStatus.FORBIDDEN, payload)
        audit_log(
            "access",
            {"ip": client_ip, "method": method, "path": path, "status": 403, "retry_after": seconds, "permanent": permanent},
        )
        return True

    def _record_unknown_path(self, client_ip: str, method: str, path: str) -> None:
        banned, seconds, offenses, count_in_window, permanent = IP_GUARD.record_unknown_path(client_ip, path)
        audit_log(
            "access",
            {
                "ip": client_ip,
                "method": method,
                "path": path,
                "status": HTTPStatus.NOT_FOUND,
                "unknown_path_count": count_in_window,
                "offenses": offenses,
                "banned": banned,
                "retry_after": seconds,
                "permanent": permanent,
            },
        )

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
            if self._reject_if_banned(client_ip, "GET", path):
                return
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
            self._record_unknown_path(client_ip, "GET", path)
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
            parsed_url = urllib.parse.urlparse(self.path)
            path = parsed_url.path
            if self._reject_if_banned(client_ip, "POST", path):
                return
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
            self._record_unknown_path(client_ip, "POST", self.path)
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
