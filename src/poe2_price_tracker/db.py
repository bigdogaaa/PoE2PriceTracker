from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def compact_name(name: str) -> str:
    return "".join(ch for ch in normalize_name(name) if ch.isalnum())


def edit_distance_at_most_one(left: str, right: str) -> bool:
    left = compact_name(left)
    right = compact_name(right)
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    if len(left) > len(right):
        left, right = right, left
    i = j = edits = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        j += 1
    return True


def search_terms(query: str) -> list[str]:
    return [term for term in normalize_name(query).split(" ") if term]


@dataclass(frozen=True)
class PriceRecord:
    id: int
    item_name: str
    amount: float
    currency: str
    source: str
    captured_at: str
    confidence: float
    raw_text: str
    screenshot_path: str
    realtime_record_id: int = 0


@dataclass(frozen=True)
class PriceStats:
    item_name: str
    count: int
    latest_amount: float
    latest_currency: str
    latest_at: str
    min_amount: float
    max_amount: float
    avg_amount: float
    latest_source: str = ""
    latest_record_id: int = 0
    realtime_record_id: int = 0
    realtime_upvotes: int = 0
    realtime_downvotes: int = 0


@dataclass(frozen=True)
class MarketRow:
    item_id: int
    item_name: str
    item_icon_path: str
    latest_amount: float
    latest_currency: str
    latest_at: str
    source: str
    count: int
    min_amount: float
    max_amount: float
    avg_amount: float
    sparkline: str
    trend_percent: str
    favorite: bool
    pinned: bool
    latest_record_id: int = 0
    realtime_record_id: int = 0
    realtime_upvotes: int = 0
    realtime_downvotes: int = 0


@dataclass(frozen=True)
class IconAsset:
    name: str
    kind: str
    page_url: str
    icon_url: str
    local_path: str
    phash: str


@dataclass(frozen=True)
class MarketExchangeRecord:
    id: int
    want_item: str
    have_item: str
    want_item_match: str
    have_item_match: str
    want_item_known: bool
    have_item_known: bool
    want_item_is_currency: bool
    have_item_is_currency: bool
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


@dataclass(frozen=True)
class RealtimePriceRecord:
    id: int
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
    downvotes: int = 0
    mirrored_price_record_id: int = 0
    remote_key: str = ""


class PriceDatabase:
    def __init__(self, path: Path):
        self.path = path
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES items(id),
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                source TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                raw_text TEXT NOT NULL DEFAULT '',
                screenshot_path TEXT NOT NULL DEFAULT '',
                realtime_record_id INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_items_normalized_name
                ON items(normalized_name);
            CREATE INDEX IF NOT EXISTS idx_price_records_item_time
                ON price_records(item_id, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_price_records_item_realtime_time
                ON price_records(item_id, realtime_record_id, captured_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_price_records_source_item
                ON price_records(source, item_id);

            CREATE TABLE IF NOT EXISTS favorites (
                item_id INTEGER PRIMARY KEY REFERENCES items(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pinned_items (
                item_id INTEGER PRIMARY KEY REFERENCES items(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS icon_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                page_url TEXT NOT NULL DEFAULT '',
                icon_url TEXT NOT NULL DEFAULT '',
                local_path TEXT NOT NULL DEFAULT '',
                phash TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(normalized_name, kind)
            );

            CREATE INDEX IF NOT EXISTS idx_icon_assets_lookup
                ON icon_assets(kind, normalized_name);

            CREATE TABLE IF NOT EXISTS market_exchange_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                want_item TEXT NOT NULL,
                have_item TEXT NOT NULL,
                want_item_match TEXT NOT NULL DEFAULT '',
                have_item_match TEXT NOT NULL DEFAULT '',
                want_item_known INTEGER NOT NULL DEFAULT 0,
                have_item_known INTEGER NOT NULL DEFAULT 0,
                want_item_is_currency INTEGER NOT NULL DEFAULT 0,
                have_item_is_currency INTEGER NOT NULL DEFAULT 0,
                market_want_amount REAL NOT NULL,
                market_have_amount REAL NOT NULL,
                user_want_amount REAL NOT NULL,
                user_have_amount REAL NOT NULL,
                source TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                raw_text TEXT NOT NULL DEFAULT '',
                screenshot_path TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                upvotes INTEGER NOT NULL DEFAULT 0,
                downvotes INTEGER NOT NULL DEFAULT 0,
                mirrored_price_record_id INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_market_exchange_records_time
                ON market_exchange_records(captured_at DESC);

            CREATE TABLE IF NOT EXISTS realtime_price_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                item_match TEXT NOT NULL DEFAULT '',
                item_known INTEGER NOT NULL DEFAULT 0,
                side TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                want_item TEXT NOT NULL DEFAULT '',
                have_item TEXT NOT NULL DEFAULT '',
                market_want_amount REAL NOT NULL DEFAULT 0,
                market_have_amount REAL NOT NULL DEFAULT 0,
                user_want_amount REAL NOT NULL DEFAULT 0,
                user_have_amount REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                raw_text TEXT NOT NULL DEFAULT '',
                screenshot_path TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                remote_key TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_realtime_price_records_item_time
                ON realtime_price_records(item_name, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_realtime_price_records_side_time
                ON realtime_price_records(side, captured_at DESC);
            """
        )
        self._ensure_market_exchange_columns()
        self._ensure_price_record_columns()
        self._ensure_realtime_price_columns()
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_price_records_realtime_record ON price_records(realtime_record_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_realtime_price_records_vote ON realtime_price_records(id, upvotes)"
        )
        self.conn.commit()
        self._repair_realtime_price_mirrors()

    def _ensure_market_exchange_columns(self) -> None:
        existing = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(market_exchange_records)").fetchall()
        }
        columns = {
            "want_item_match": "TEXT NOT NULL DEFAULT ''",
            "have_item_match": "TEXT NOT NULL DEFAULT ''",
            "want_item_known": "INTEGER NOT NULL DEFAULT 0",
            "have_item_known": "INTEGER NOT NULL DEFAULT 0",
            "want_item_is_currency": "INTEGER NOT NULL DEFAULT 0",
            "have_item_is_currency": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE market_exchange_records ADD COLUMN {name} {definition}")

    def _ensure_price_record_columns(self) -> None:
        existing = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(price_records)").fetchall()
        }
        if "realtime_record_id" not in existing:
            self.conn.execute("ALTER TABLE price_records ADD COLUMN realtime_record_id INTEGER NOT NULL DEFAULT 0")

    def _ensure_realtime_price_columns(self) -> None:
        existing = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(realtime_price_records)").fetchall()
        }
        columns = {
            "upvotes": "INTEGER NOT NULL DEFAULT 0",
            "downvotes": "INTEGER NOT NULL DEFAULT 0",
            "mirrored_price_record_id": "INTEGER NOT NULL DEFAULT 0",
            "remote_key": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE realtime_price_records ADD COLUMN {name} {definition}")
        self.conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_realtime_price_records_remote_key
                ON realtime_price_records(remote_key)
                WHERE remote_key <> ''
            """
        )

    def _repair_realtime_price_mirrors(self) -> None:
        rows = self.conn.execute(
            """
            SELECT
                rp.id, rp.item_name, rp.side, rp.amount, rp.currency, rp.source,
                rp.captured_at, rp.confidence, rp.raw_text, rp.screenshot_path
            FROM realtime_price_records rp
            WHERE rp.amount > 0
              AND rp.item_name <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM price_records pr
                  WHERE pr.realtime_record_id = rp.id
              )
            ORDER BY rp.captured_at ASC, rp.id ASC
            """
        ).fetchall()
        for row in rows:
            item_name = str(row["item_name"]).strip()
            if not item_name:
                continue
            item_id = self.upsert_item(item_name)
            source = f"{str(row['source']).strip() or '实时价格导入'}-{str(row['side']).strip() or '未知'}"
            cur = self.conn.execute(
                """
                INSERT INTO price_records(
                    item_id, amount, currency, source, captured_at,
                    confidence, raw_text, screenshot_path, realtime_record_id
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    float(row["amount"]),
                    canonical_currency(str(row["currency"])),
                    source,
                    str(row["captured_at"]),
                    float(row["confidence"] or 0),
                    str(row["raw_text"] or ""),
                    str(row["screenshot_path"] or ""),
                    int(row["id"]),
                ),
            )
            self.conn.execute(
                "UPDATE realtime_price_records SET mirrored_price_record_id = ? WHERE id = ?",
                (int(cur.lastrowid), int(row["id"])),
            )
        if rows:
            self.conn.commit()

    def upsert_item(self, item_name: str) -> int:
        normalized = normalize_name(item_name)
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO items(name, normalized_name, created_at, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(normalized_name) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (item_name.strip(), normalized, now, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM items WHERE normalized_name = ?", (normalized,)
        ).fetchone()
        return int(row["id"])

    def add_price_record(
        self,
        item_name: str,
        amount: float,
        currency: str,
        source: str,
        confidence: float = 0,
        raw_text: str = "",
        screenshot_path: str = "",
        realtime_record_id: int = 0,
        captured_at: str | None = None,
    ) -> int:
        item_id = self.upsert_item(item_name)
        cur = self.conn.execute(
            """
            INSERT INTO price_records(
                item_id, amount, currency, source, captured_at,
                confidence, raw_text, screenshot_path, realtime_record_id
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                float(amount),
                currency.strip(),
                source,
                captured_at or utc_now(),
                float(confidence),
                raw_text,
                screenshot_path,
                int(realtime_record_id or 0),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def upsert_latest_price_record(
        self,
        item_name: str,
        amount: float,
        currency: str,
        source: str,
        confidence: float = 0,
        raw_text: str = "",
        screenshot_path: str = "",
        realtime_record_id: int = 0,
    ) -> int:
        item_id = self.upsert_item(item_name)
        row = self.conn.execute(
            """
            SELECT id FROM price_records
            WHERE item_id = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            return self.add_price_record(
                item_name,
                amount,
                currency,
                source,
                confidence=confidence,
                raw_text=raw_text,
                screenshot_path=screenshot_path,
                realtime_record_id=realtime_record_id,
            )
        record_id = int(row["id"])
        self.conn.execute(
            """
            UPDATE price_records
            SET amount = ?,
                currency = ?,
                source = ?,
                captured_at = ?,
                confidence = ?,
                raw_text = ?,
                screenshot_path = ?,
                realtime_record_id = ?
            WHERE id = ?
            """,
            (
                float(amount),
                currency.strip(),
                source,
                utc_now(),
                float(confidence),
                raw_text,
                screenshot_path,
                int(realtime_record_id or 0),
                record_id,
            ),
        )
        self.conn.commit()
        return record_id

    def search_items(self, query: str, limit: int = 12) -> list[str]:
        terms = search_terms(query)
        if not terms:
            return []
        where = " AND ".join("normalized_name LIKE ?" for _term in terms)
        params = [f"%{term}%" for term in terms]
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT name, normalized_name
            FROM items
            WHERE {where}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        direct = [str(row["name"]) for row in rows]
        if len(direct) >= limit:
            return direct

        all_rows = self.conn.execute(
            "SELECT name, normalized_name FROM items ORDER BY updated_at DESC LIMIT 500"
        ).fetchall()
        scored = []
        existing = {normalize_name(name) for name in direct}
        for row in all_rows:
            name = str(row["name"])
            norm = str(row["normalized_name"])
            if norm in existing:
                continue
            score = min(SequenceMatcher(None, term, norm).ratio() for term in terms)
            if score >= 0.45:
                scored.append((score, name))
        scored.sort(reverse=True)
        return direct + [name for _, name in scored[: max(0, limit - len(direct))]]

    def match_item_name(self, query: str, min_score: float = 0.72) -> tuple[str, float]:
        normalized = normalize_name(query)
        if not normalized:
            return "", 0.0
        rows = self.conn.execute(
            """
            SELECT name, normalized_name FROM items
            UNION
            SELECT name, normalized_name FROM icon_assets WHERE kind IN ('item', 'currency')
            """
        ).fetchall()
        best_name = ""
        best_score = 0.0
        try:
            from rapidfuzz import fuzz

            for row in rows:
                score = fuzz.WRatio(normalized, str(row["normalized_name"])) / 100.0
                if score > best_score:
                    best_score = score
                    best_name = str(row["name"])
        except Exception:
            for row in rows:
                score = SequenceMatcher(None, normalized, str(row["normalized_name"])).ratio()
                if score > best_score:
                    best_score = score
                    best_name = str(row["name"])
        if best_score < min_score:
            return query.strip(), best_score
        return best_name, best_score

    def match_item_name_strict(self, query: str, max_edits: int = 1) -> tuple[str, float]:
        normalized = normalize_name(query)
        if not normalized:
            return "", 0.0
        rows = self.conn.execute(
            """
            SELECT name, normalized_name FROM items
            UNION
            SELECT name, normalized_name FROM icon_assets WHERE kind IN ('item', 'currency')
            """
        ).fetchall()
        for row in rows:
            if normalized == str(row["normalized_name"]):
                return str(row["name"]), 1.0
        best_name = ""
        best_score = 0.0
        for row in rows:
            candidate = str(row["normalized_name"])
            if max_edits <= 1 and not edit_distance_at_most_one(normalized, candidate):
                continue
            score = SequenceMatcher(None, compact_name(normalized), compact_name(candidate)).ratio()
            if max_edits <= 1:
                score = max(score, 0.94)
            if score > best_score:
                best_score = score
                best_name = str(row["name"])
        if not best_name:
            return query.strip(), 0.0
        return best_name, best_score

    def get_stats(self, item_name: str, min_realtime_upvotes: int = 0) -> PriceStats | None:
        normalized = normalize_name(item_name)
        min_upvotes = max(0, int(min_realtime_upvotes or 0))
        item = self.conn.execute(
            "SELECT id, name FROM items WHERE normalized_name = ?",
            (normalized,),
        ).fetchone()
        if item is None:
            matches = self.search_items(item_name, limit=1)
            if not matches or normalize_name(matches[0]) == normalized:
                return None
            return self.get_stats(matches[0], min_realtime_upvotes=min_upvotes)

        rows = self.conn.execute(
            """
            SELECT
                r.id, r.amount, r.currency, r.source, r.captured_at, r.realtime_record_id,
                COALESCE(rp.upvotes, 0) AS realtime_upvotes,
                COALESCE(rp.downvotes, 0) AS realtime_downvotes
            FROM price_records r
            LEFT JOIN realtime_price_records rp ON rp.id = r.realtime_record_id
            WHERE r.item_id = ?
              AND (r.realtime_record_id = 0 OR COALESCE(rp.upvotes, 0) >= ?)
            ORDER BY r.captured_at DESC, r.id DESC
            """,
            (int(item["id"]), min_upvotes),
        ).fetchall()
        if not rows:
            return None
        realtime_rows = [row for row in rows if int(row["realtime_record_id"] or 0) > 0]
        preferred = realtime_rows or list(rows)
        latest = preferred[0]
        amounts = [float(row["amount"]) for row in preferred]
        return PriceStats(
            item_name=str(item["name"]),
            count=len(preferred),
            latest_amount=float(latest["amount"]),
            latest_currency=str(latest["currency"]),
            latest_at=str(latest["captured_at"]),
            min_amount=min(amounts),
            max_amount=max(amounts),
            avg_amount=sum(amounts) / len(amounts),
            latest_source=str(latest["source"]),
            latest_record_id=int(latest["id"] or 0),
            realtime_record_id=int(latest["realtime_record_id"] or 0),
            realtime_upvotes=int(latest["realtime_upvotes"] or 0),
            realtime_downvotes=int(latest["realtime_downvotes"] or 0),
        )

    def get_recent_records(
        self,
        item_name: str = "",
        limit: int = 30,
        min_realtime_upvotes: int = 0,
        prefer_realtime_if_available: bool = False,
    ) -> list[PriceRecord]:
        params: tuple[object, ...]
        where = ""
        if item_name.strip():
            item = self.conn.execute(
                "SELECT id, name FROM items WHERE normalized_name = ?",
                (normalize_name(item_name),),
            ).fetchone()
            if item is None:
                return []
            if prefer_realtime_if_available:
                histories = self._price_histories_for_item_ids(
                    [int(item["id"])],
                    limit=limit,
                    min_realtime_upvotes=min_realtime_upvotes,
                )
                return list(reversed(histories.get(int(item["id"]), [])))
            rows = self.conn.execute(
                """
                SELECT
                    r.id, r.amount, r.currency, r.source,
                    r.captured_at, r.confidence, r.raw_text, r.screenshot_path,
                    r.realtime_record_id
                FROM price_records r
                WHERE r.item_id = ?
                ORDER BY r.captured_at DESC, r.id DESC
                LIMIT ?
                """,
                (int(item["id"]), limit),
            ).fetchall()
            return [
                PriceRecord(
                    id=int(row["id"]),
                    item_name=str(item["name"]),
                    amount=float(row["amount"]),
                    currency=str(row["currency"]),
                    source=str(row["source"]),
                    captured_at=str(row["captured_at"]),
                    confidence=float(row["confidence"]),
                    raw_text=str(row["raw_text"]),
                    screenshot_path=str(row["screenshot_path"]),
                    realtime_record_id=int(row["realtime_record_id"] or 0),
                )
                for row in rows
            ]
        else:
            params = (limit,)
        rows = self.conn.execute(
            f"""
            SELECT
                r.id, i.name AS item_name, r.amount, r.currency, r.source,
                r.captured_at, r.confidence, r.raw_text, r.screenshot_path,
                r.realtime_record_id
            FROM price_records r
            JOIN items i ON i.id = r.item_id
            {where}
            ORDER BY r.captured_at DESC, r.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            PriceRecord(
                id=int(row["id"]),
                item_name=str(row["item_name"]),
                amount=float(row["amount"]),
                currency=str(row["currency"]),
                source=str(row["source"]),
                captured_at=str(row["captured_at"]),
                confidence=float(row["confidence"]),
                raw_text=str(row["raw_text"]),
                screenshot_path=str(row["screenshot_path"]),
                realtime_record_id=int(row["realtime_record_id"] or 0),
            )
            for row in rows
        ]

    def _price_histories_for_item_ids(
        self,
        item_ids: list[int],
        limit: int = 12,
        min_realtime_upvotes: int = 0,
    ) -> dict[int, list[PriceRecord]]:
        clean_ids = [int(item_id) for item_id in dict.fromkeys(item_ids) if int(item_id) > 0]
        if not clean_ids:
            return {}
        placeholders = ",".join("?" for _ in clean_ids)
        rows = self.conn.execute(
            f"""
            SELECT
                r.item_id, i.name AS item_name, r.id, r.amount, r.currency, r.source,
                r.captured_at, r.confidence, r.raw_text, r.screenshot_path,
                r.realtime_record_id
            FROM price_records r
            JOIN items i ON i.id = r.item_id
            LEFT JOIN realtime_price_records rp ON rp.id = r.realtime_record_id
            WHERE r.item_id IN ({placeholders})
              AND (r.realtime_record_id = 0 OR COALESCE(rp.upvotes, 0) >= ?)
            ORDER BY r.item_id, r.captured_at DESC, r.id DESC
            """,
            tuple([*clean_ids, max(0, int(min_realtime_upvotes or 0))]),
        ).fetchall()
        grouped: dict[int, list[sqlite3.Row]] = {item_id: [] for item_id in clean_ids}
        for row in rows:
            grouped.setdefault(int(row["item_id"]), []).append(row)
        histories: dict[int, list[PriceRecord]] = {}
        for item_id, group in grouped.items():
            realtime_group = [row for row in group if int(row["realtime_record_id"] or 0) > 0]
            selected = (realtime_group or group)[: max(1, int(limit or 12))]
            histories[item_id] = [
                PriceRecord(
                    id=int(row["id"]),
                    item_name=str(row["item_name"]),
                    amount=float(row["amount"]),
                    currency=str(row["currency"]),
                    source=str(row["source"]),
                    captured_at=str(row["captured_at"]),
                    confidence=float(row["confidence"]),
                    raw_text=str(row["raw_text"]),
                    screenshot_path=str(row["screenshot_path"]),
                    realtime_record_id=int(row["realtime_record_id"] or 0),
                )
                for row in reversed(selected)
            ]
        return histories

    def get_market_rows(
        self,
        query: str = "",
        source_filter: str = "",
        favorites_only: bool = False,
        sort_by: str = "latest_at",
        descending: bool = True,
        offset: int = 0,
        limit: int = 500,
        target_currency: str = "",
        conversion_rate: float = 160.0,
        chaos_per_divine: float = 10.0,
        min_realtime_upvotes: int = 0,
    ) -> list[MarketRow]:
        rate = max(0.000001, float(conversion_rate or 160.0))
        target = canonical_currency(target_currency)
        chaos_per_divine = max(0.000001, float(chaos_per_divine or 10.0))
        min_upvotes = max(0, int(min_realtime_upvotes or 0))
        if sort_by == "price":
            if target == "神圣石":
                sort_expr = (
                    "CASE "
                    "WHEN i.normalized_name IN ('神圣石', 'divine orb', 'divine') THEN 1.0 "
                    f"WHEN i.normalized_name IN ('崇高石', 'exalted orb', 'exalt', 'exalted') THEN 1.0 / {rate:.8f} "
                    f"WHEN i.normalized_name IN ('混沌石', 'chaos orb', 'chaos') THEN 1.0 / {chaos_per_divine:.8f} "
                    "WHEN latest.currency IN ('崇高石', '崇高', 'Exalted Orb', 'exalted orb', 'exalt', 'exalted') "
                    f"THEN latest.amount / {rate:.8f} "
                    "WHEN latest.currency IN ('混沌石', '混沌', 'Chaos Orb', 'chaos orb', 'chaos') "
                    f"THEN latest.amount / {chaos_per_divine:.8f} ELSE latest.amount END"
                )
            elif target == "崇高石":
                sort_expr = (
                    "CASE "
                    f"WHEN i.normalized_name IN ('神圣石', 'divine orb', 'divine') THEN {rate:.8f} "
                    "WHEN i.normalized_name IN ('崇高石', 'exalted orb', 'exalt', 'exalted') THEN 1.0 "
                    f"WHEN i.normalized_name IN ('混沌石', 'chaos orb', 'chaos') THEN {rate:.8f} / {chaos_per_divine:.8f} "
                    "WHEN latest.currency IN ('神圣石', '神圣', 'Divine Orb', 'divine orb', 'divine') "
                    f"THEN latest.amount * {rate:.8f} "
                    "WHEN latest.currency IN ('混沌石', '混沌', 'Chaos Orb', 'chaos orb', 'chaos') "
                    f"THEN latest.amount * {rate:.8f} / {chaos_per_divine:.8f} ELSE latest.amount END"
                )
            elif target == "混沌石":
                sort_expr = (
                    "CASE "
                    f"WHEN i.normalized_name IN ('神圣石', 'divine orb', 'divine') THEN {chaos_per_divine:.8f} "
                    f"WHEN i.normalized_name IN ('崇高石', 'exalted orb', 'exalt', 'exalted') THEN {chaos_per_divine:.8f} / {rate:.8f} "
                    "WHEN i.normalized_name IN ('混沌石', 'chaos orb', 'chaos') THEN 1.0 "
                    "WHEN latest.currency IN ('神圣石', '神圣', 'Divine Orb', 'divine orb', 'divine') "
                    f"THEN latest.amount * {chaos_per_divine:.8f} "
                    "WHEN latest.currency IN ('崇高石', '崇高', 'Exalted Orb', 'exalted orb', 'exalt', 'exalted') "
                    f"THEN latest.amount * {chaos_per_divine:.8f} / {rate:.8f} ELSE latest.amount END"
                )
            else:
                sort_expr = "latest.amount"
        else:
            sort_expr = ""
        allowed_sort = {
            "name": "i.name",
            "price": "latest_amount",
            "latest_at": "latest_at",
            "count": "record_count",
            "source": "latest.source",
            "favorite": "favorite",
            "rating": "COALESCE(rp.upvotes, 0)",
            "icon": "COALESCE(icon.local_path, '')",
            "trend": "latest.raw_text",
            "currency": "latest.currency",
        }
        if not sort_expr:
            sort_expr = allowed_sort.get(sort_by, "latest_at")
        direction = "DESC" if descending else "ASC"
        where = []
        params: list[object] = []
        for term in search_terms(query):
            where.append("i.normalized_name LIKE ?")
            params.append(f"%{term}%")
        if source_filter.strip() and source_filter != "全部来源":
            where.append("latest.source = ?")
            params.append(source_filter)
        if favorites_only:
            where.append("f.item_id IS NOT NULL")
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        params = [min_upvotes, *params, limit, offset]
        rows = self.conn.execute(
            f"""
            WITH eligible AS (
                SELECT r.*
                FROM price_records r
                LEFT JOIN realtime_price_records rp_filter ON rp_filter.id = r.realtime_record_id
                WHERE r.realtime_record_id = 0 OR COALESCE(rp_filter.upvotes, 0) >= ?
            ),
            preferred AS (
                SELECT r.*
                FROM eligible r
                WHERE r.realtime_record_id > 0
                   OR NOT EXISTS (
                       SELECT 1
                       FROM eligible realtime
                       WHERE realtime.item_id = r.item_id
                         AND realtime.realtime_record_id > 0
                   )
            ),
            latest AS (
                SELECT r.*
                FROM preferred r
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM preferred newer
                    WHERE newer.item_id = r.item_id
                      AND (
                          newer.captured_at > r.captured_at
                          OR (newer.captured_at = r.captured_at AND newer.id > r.id)
                      )
                )
            ),
            page AS (
                SELECT
                    i.id AS item_id,
                    i.name AS item_name,
                    latest.id AS latest_record_id,
                    latest.amount AS latest_amount,
                    latest.currency AS latest_currency,
                    latest.captured_at AS latest_at,
                    latest.source AS source,
                    latest.raw_text AS latest_raw_text,
                    latest.realtime_record_id AS realtime_record_id,
                    COALESCE(rp.upvotes, 0) AS realtime_upvotes,
                    COALESCE(rp.downvotes, 0) AS realtime_downvotes,
                    COALESCE(icon.local_path, '') AS item_icon_path,
                    f.item_id IS NOT NULL AS favorite,
                    p.item_id IS NOT NULL AS pinned,
                    COUNT(history.id) AS record_count
                FROM items i
                JOIN latest ON latest.item_id = i.id
                JOIN preferred history ON history.item_id = i.id
                LEFT JOIN realtime_price_records rp ON rp.id = latest.realtime_record_id
                LEFT JOIN favorites f ON f.item_id = i.id
                LEFT JOIN pinned_items p ON p.item_id = i.id
                LEFT JOIN (
                    SELECT normalized_name, MAX(local_path) AS local_path
                    FROM icon_assets
                    WHERE kind IN ('item', 'currency') AND local_path <> ''
                    GROUP BY normalized_name
                ) icon ON icon.normalized_name = i.normalized_name
                {where_sql}
                GROUP BY i.id
                ORDER BY pinned DESC, {sort_expr} {direction}
                LIMIT ? OFFSET ?
            )
            SELECT
                page.*,
                page.record_count AS count,
                (
                    SELECT MIN(pr.amount)
                    FROM preferred pr
                    WHERE pr.item_id = page.item_id
                ) AS min_amount,
                (
                    SELECT MAX(pr.amount)
                    FROM preferred pr
                    WHERE pr.item_id = page.item_id
                ) AS max_amount,
                (
                    SELECT AVG(pr.amount)
                    FROM preferred pr
                    WHERE pr.item_id = page.item_id
                ) AS avg_amount
            FROM page
            """,
            tuple(params),
        ).fetchall()
        result = []
        histories_by_item_id = self._price_histories_for_item_ids(
            [int(row["item_id"]) for row in rows],
            limit=12,
            min_realtime_upvotes=min_upvotes,
        )
        conversion_rate = rate
        for row in rows:
            history_currency = str(row["latest_currency"])
            trend_match = __import__("re").search(r"trend=([+-]?\d+(?:\.\d+)?%)", str(row["latest_raw_text"]))
            history = histories_by_item_id.get(int(row["item_id"]), [])
            has_realtime_history = any(record.realtime_record_id > 0 for record in history)
            if len(history) >= 2:
                history_values = [
                    convert_amount(record.amount, record.currency, history_currency, conversion_rate or 160.0, chaos_per_divine)
                    for record in history
                ]
            else:
                history_values = []
            local_trend = trend_percent(history_values)
            display_trend = local_trend if len(history_values) >= 2 else ("" if has_realtime_history else (trend_match.group(1) if trend_match else ""))
            result.append(
                MarketRow(
                    item_id=int(row["item_id"]),
                    item_name=str(row["item_name"]),
                    item_icon_path=str(row["item_icon_path"]),
                    latest_amount=float(row["latest_amount"]),
                    latest_currency=str(row["latest_currency"]),
                    latest_at=str(row["latest_at"]),
                    source=str(row["source"]),
                    count=int(row["count"]),
                    min_amount=float(row["min_amount"]),
                    max_amount=float(row["max_amount"]),
                    avg_amount=float(row["avg_amount"]),
                    sparkline=sparkline(history_values),
                    trend_percent=display_trend,
                    favorite=bool(row["favorite"]),
                    pinned=bool(row["pinned"]),
                    latest_record_id=int(row["latest_record_id"] or 0),
                    realtime_record_id=int(row["realtime_record_id"] or 0),
                    realtime_upvotes=int(row["realtime_upvotes"] or 0),
                    realtime_downvotes=int(row["realtime_downvotes"] or 0),
                )
            )
        return result

    def count_market_rows(
        self,
        query: str = "",
        source_filter: str = "",
        favorites_only: bool = False,
        min_realtime_upvotes: int = 0,
    ) -> int:
        where = []
        params: list[object] = []
        min_upvotes = max(0, int(min_realtime_upvotes or 0))
        for term in search_terms(query):
            where.append("i.normalized_name LIKE ?")
            params.append(f"%{term}%")
        if source_filter.strip() and source_filter != "全部来源":
            where.append("latest.source = ?")
            params.append(source_filter)
        if favorites_only:
            where.append("f.item_id IS NOT NULL")
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        row = self.conn.execute(
            f"""
            WITH eligible AS (
                SELECT r.*
                FROM price_records r
                LEFT JOIN realtime_price_records rp_filter ON rp_filter.id = r.realtime_record_id
                WHERE r.realtime_record_id = 0 OR COALESCE(rp_filter.upvotes, 0) >= ?
            ),
            preferred AS (
                SELECT r.*
                FROM eligible r
                WHERE r.realtime_record_id > 0
                   OR NOT EXISTS (
                       SELECT 1
                       FROM eligible realtime
                       WHERE realtime.item_id = r.item_id
                         AND realtime.realtime_record_id > 0
                   )
            ),
            latest AS (
                SELECT r.*
                FROM preferred r
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM preferred newer
                    WHERE newer.item_id = r.item_id
                      AND (
                          newer.captured_at > r.captured_at
                          OR (newer.captured_at = r.captured_at AND newer.id > r.id)
                      )
                )
            )
            SELECT COUNT(DISTINCT i.id) AS count
            FROM items i
            JOIN latest ON latest.item_id = i.id
            JOIN preferred r ON r.item_id = i.id
            LEFT JOIN realtime_price_records rp ON rp.id = latest.realtime_record_id
            LEFT JOIN favorites f ON f.item_id = i.id
            {where_sql}
            """,
            tuple([min_upvotes, *params]),
        ).fetchone()
        return int(row["count"])

    def get_sources(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT source FROM price_records ORDER BY source"
        ).fetchall()
        return [str(row["source"]) for row in rows]

    def upsert_icon_asset(
        self,
        name: str,
        kind: str,
        page_url: str = "",
        icon_url: str = "",
        local_path: str = "",
        phash: str = "",
    ) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO icon_assets(
                name, normalized_name, kind, page_url, icon_url, local_path, phash, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_name, kind) DO UPDATE SET
                name = excluded.name,
                page_url = COALESCE(NULLIF(excluded.page_url, ''), icon_assets.page_url),
                icon_url = COALESCE(NULLIF(excluded.icon_url, ''), icon_assets.icon_url),
                local_path = COALESCE(NULLIF(excluded.local_path, ''), icon_assets.local_path),
                phash = COALESCE(NULLIF(excluded.phash, ''), icon_assets.phash),
                updated_at = excluded.updated_at
            """,
            (
                name.strip(),
                normalize_name(name),
                kind.strip(),
                page_url.strip(),
                icon_url.strip(),
                local_path.strip(),
                phash.strip(),
                now,
            ),
        )
        self.conn.commit()

    def get_icon_assets(self, kind: str = "") -> list[IconAsset]:
        if kind.strip():
            rows = self.conn.execute(
                """
                SELECT name, kind, page_url, icon_url, local_path, phash
                FROM icon_assets
                WHERE kind = ?
                ORDER BY name
                """,
                (kind.strip(),),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT name, kind, page_url, icon_url, local_path, phash
                FROM icon_assets
                ORDER BY kind, name
                """
            ).fetchall()
        return [
            IconAsset(
                name=str(row["name"]),
                kind=str(row["kind"]),
                page_url=str(row["page_url"]),
                icon_url=str(row["icon_url"]),
                local_path=str(row["local_path"]),
                phash=str(row["phash"]),
            )
            for row in rows
        ]

    def add_market_exchange_record(
        self,
        want_item: str,
        have_item: str,
        market_want_amount: float,
        market_have_amount: float,
        user_want_amount: float,
        user_have_amount: float,
        want_item_match: str = "",
        have_item_match: str = "",
        want_item_known: bool = False,
        have_item_known: bool = False,
        want_item_is_currency: bool = False,
        have_item_is_currency: bool = False,
        source: str = "游戏内置市场截图",
        confidence: float = 0,
        raw_text: str = "",
        screenshot_path: str = "",
        note: str = "",
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO market_exchange_records(
                want_item, have_item,
                want_item_match, have_item_match,
                want_item_known, have_item_known,
                want_item_is_currency, have_item_is_currency,
                market_want_amount, market_have_amount,
                user_want_amount, user_have_amount,
                source, captured_at, confidence, raw_text, screenshot_path, note
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                want_item.strip(),
                have_item.strip(),
                want_item_match.strip(),
                have_item_match.strip(),
                1 if want_item_known else 0,
                1 if have_item_known else 0,
                1 if want_item_is_currency else 0,
                1 if have_item_is_currency else 0,
                float(market_want_amount),
                float(market_have_amount),
                float(user_want_amount),
                float(user_have_amount),
                source.strip() or "游戏内置市场截图",
                utc_now(),
                float(confidence),
                raw_text,
                screenshot_path,
                note,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_market_exchange_records(self, limit: int = 100) -> list[MarketExchangeRecord]:
        rows = self.conn.execute(
            """
            SELECT
                id, want_item, have_item,
                want_item_match, have_item_match,
                want_item_known, have_item_known,
                want_item_is_currency, have_item_is_currency,
                market_want_amount, market_have_amount,
                user_want_amount, user_have_amount,
                source, captured_at, confidence, raw_text, screenshot_path, note
            FROM market_exchange_records
            ORDER BY captured_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            MarketExchangeRecord(
                id=int(row["id"]),
                want_item=str(row["want_item"]),
                have_item=str(row["have_item"]),
                want_item_match=str(row["want_item_match"]),
                have_item_match=str(row["have_item_match"]),
                want_item_known=bool(row["want_item_known"]),
                have_item_known=bool(row["have_item_known"]),
                want_item_is_currency=bool(row["want_item_is_currency"]),
                have_item_is_currency=bool(row["have_item_is_currency"]),
                market_want_amount=float(row["market_want_amount"]),
                market_have_amount=float(row["market_have_amount"]),
                user_want_amount=float(row["user_want_amount"]),
                user_have_amount=float(row["user_have_amount"]),
                source=str(row["source"]),
                captured_at=str(row["captured_at"]),
                confidence=float(row["confidence"]),
                raw_text=str(row["raw_text"]),
                screenshot_path=str(row["screenshot_path"]),
                note=str(row["note"]),
            )
            for row in rows
        ]

    def add_realtime_price_record(
        self,
        item_name: str,
        side: str,
        amount: float,
        currency: str,
        want_item: str = "",
        have_item: str = "",
        market_want_amount: float = 0,
        market_have_amount: float = 0,
        user_want_amount: float = 0,
        user_have_amount: float = 0,
        item_match: str = "",
        item_known: bool = False,
        source: str = "实时价格导入",
        confidence: float = 0,
        raw_text: str = "",
        screenshot_path: str = "",
        note: str = "",
        mirror_to_price_records: bool = True,
        remote_key: str = "",
    ) -> int:
        clean_item = item_name.strip()
        clean_currency = canonical_currency(currency.strip())
        clean_side = side.strip() or "未知"
        clean_remote_key = remote_key.strip() or f"local:{uuid.uuid4().hex}"
        cur = self.conn.execute(
            """
            INSERT INTO realtime_price_records(
                item_name, item_match, item_known, side, amount, currency,
                want_item, have_item, market_want_amount, market_have_amount,
                user_want_amount, user_have_amount,
                source, captured_at, confidence, raw_text, screenshot_path, note, remote_key
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_item,
                item_match.strip(),
                1 if item_known else 0,
                clean_side,
                float(amount),
                clean_currency,
                want_item.strip(),
                have_item.strip(),
                float(market_want_amount),
                float(market_have_amount),
                float(user_want_amount),
                float(user_have_amount),
                source.strip() or "实时价格导入",
                utc_now(),
                float(confidence),
                raw_text,
                screenshot_path,
                note,
                clean_remote_key,
            ),
        )
        self.conn.commit()
        realtime_id = int(cur.lastrowid)
        if mirror_to_price_records and clean_item and float(amount) > 0 and clean_currency:
            price_record_id = self.add_price_record(
                clean_item,
                float(amount),
                clean_currency,
                f"{source.strip() or '实时价格导入'}-{clean_side}",
                confidence=confidence,
                raw_text=raw_text,
                screenshot_path=screenshot_path,
                realtime_record_id=realtime_id,
            )
            self.conn.execute(
                "UPDATE realtime_price_records SET mirrored_price_record_id = ? WHERE id = ?",
                (price_record_id, realtime_id),
            )
            self.conn.commit()
        return realtime_id

    def get_realtime_price_records(self, limit: int = 100) -> list[RealtimePriceRecord]:
        rows = self.conn.execute(
            """
            SELECT
                id, item_name, item_match, item_known, side, amount, currency,
                want_item, have_item, market_want_amount, market_have_amount,
                user_want_amount, user_have_amount,
                source, captured_at, confidence, raw_text, screenshot_path, note,
                upvotes, downvotes, mirrored_price_record_id, remote_key
            FROM realtime_price_records
            ORDER BY captured_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            RealtimePriceRecord(
                id=int(row["id"]),
                item_name=str(row["item_name"]),
                item_match=str(row["item_match"]),
                item_known=bool(row["item_known"]),
                side=str(row["side"]),
                amount=float(row["amount"]),
                currency=str(row["currency"]),
                want_item=str(row["want_item"]),
                have_item=str(row["have_item"]),
                market_want_amount=float(row["market_want_amount"]),
                market_have_amount=float(row["market_have_amount"]),
                user_want_amount=float(row["user_want_amount"]),
                user_have_amount=float(row["user_have_amount"]),
                source=str(row["source"]),
                captured_at=str(row["captured_at"]),
                confidence=float(row["confidence"]),
                raw_text=str(row["raw_text"]),
                screenshot_path=str(row["screenshot_path"]),
                note=str(row["note"]),
                upvotes=int(row["upvotes"] or 0),
                downvotes=int(row["downvotes"] or 0),
                mirrored_price_record_id=int(row["mirrored_price_record_id"] or 0),
                remote_key=str(row["remote_key"] or ""),
            )
            for row in rows
        ]

    def get_realtime_price_record(self, record_id: int) -> RealtimePriceRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id, item_name, item_match, item_known, side, amount, currency,
                want_item, have_item, market_want_amount, market_have_amount,
                user_want_amount, user_have_amount,
                source, captured_at, confidence, raw_text, screenshot_path, note,
                upvotes, downvotes, mirrored_price_record_id, remote_key
            FROM realtime_price_records
            WHERE id = ?
            """,
            (int(record_id),),
        ).fetchone()
        if row is None:
            return None
        return RealtimePriceRecord(
            id=int(row["id"]),
            item_name=str(row["item_name"]),
            item_match=str(row["item_match"]),
            item_known=bool(row["item_known"]),
            side=str(row["side"]),
            amount=float(row["amount"]),
            currency=str(row["currency"]),
            want_item=str(row["want_item"]),
            have_item=str(row["have_item"]),
            market_want_amount=float(row["market_want_amount"]),
            market_have_amount=float(row["market_have_amount"]),
            user_want_amount=float(row["user_want_amount"]),
            user_have_amount=float(row["user_have_amount"]),
            source=str(row["source"]),
            captured_at=str(row["captured_at"]),
            confidence=float(row["confidence"]),
            raw_text=str(row["raw_text"]),
            screenshot_path=str(row["screenshot_path"]),
            note=str(row["note"]),
            upvotes=int(row["upvotes"] or 0),
            downvotes=int(row["downvotes"] or 0),
            mirrored_price_record_id=int(row["mirrored_price_record_id"] or 0),
            remote_key=str(row["remote_key"] or ""),
        )

    def get_realtime_remote_signatures(self) -> dict[str, tuple[object, ...]]:
        rows = self.conn.execute(
            """
            SELECT
                remote_key, item_name, item_match, item_known, side, amount, currency,
                want_item, have_item, market_want_amount, market_have_amount,
                user_want_amount, user_have_amount, source, captured_at, confidence,
                note, upvotes
            FROM realtime_price_records
            WHERE remote_key <> ''
            """
        ).fetchall()
        return {
            str(row["remote_key"]): (
                str(row["item_name"]),
                str(row["item_match"]),
                int(row["item_known"] or 0),
                str(row["side"]),
                round(float(row["amount"]), 8),
                canonical_currency(str(row["currency"])),
                str(row["want_item"]),
                str(row["have_item"]),
                round(float(row["market_want_amount"]), 8),
                round(float(row["market_have_amount"]), 8),
                round(float(row["user_want_amount"]), 8),
                round(float(row["user_have_amount"]), 8),
                str(row["source"]),
                str(row["captured_at"]),
                round(float(row["confidence"]), 8),
                str(row["note"]),
                max(0, int(row["upvotes"] or 0)),
            )
            for row in rows
        }

    def upsert_synced_realtime_price_record(
        self,
        remote_key: str,
        item_name: str,
        side: str,
        amount: float,
        currency: str,
        upvotes: int = 0,
        want_item: str = "",
        have_item: str = "",
        market_want_amount: float = 0,
        market_have_amount: float = 0,
        user_want_amount: float = 0,
        user_have_amount: float = 0,
        item_match: str = "",
        item_known: bool = False,
        source: str = "实时价格导入",
        captured_at: str = "",
        confidence: float = 0,
        raw_text: str = "",
        screenshot_path: str = "",
        note: str = "",
    ) -> int:
        clean_remote_key = remote_key.strip()
        if not clean_remote_key:
            raise ValueError("remote_key is required")
        clean_item = item_name.strip()
        clean_currency = canonical_currency(currency.strip())
        clean_side = side.strip() or "未知"
        clean_source = source.strip() or "实时价格导入"
        clean_captured_at = captured_at.strip() or utc_now()
        existing = self.conn.execute(
            """
            SELECT id, mirrored_price_record_id
            FROM realtime_price_records
            WHERE remote_key = ?
            """,
            (clean_remote_key,),
        ).fetchone()
        if existing is None:
            realtime_id = self.add_realtime_price_record(
                item_name=clean_item,
                side=clean_side,
                amount=float(amount),
                currency=clean_currency,
                want_item=want_item,
                have_item=have_item,
                market_want_amount=market_want_amount,
                market_have_amount=market_have_amount,
                user_want_amount=user_want_amount,
                user_have_amount=user_have_amount,
                item_match=item_match,
                item_known=item_known,
                source=clean_source,
                confidence=confidence,
                raw_text=raw_text,
                screenshot_path=screenshot_path,
                note=note,
                mirror_to_price_records=False,
                remote_key=clean_remote_key,
            )
            self.conn.execute(
                """
                UPDATE realtime_price_records
                SET captured_at = ?, upvotes = ?, downvotes = 0
                WHERE id = ?
                """,
                (clean_captured_at, max(0, int(upvotes or 0)), realtime_id),
            )
            price_record_id = 0
        else:
            realtime_id = int(existing["id"])
            price_record_id = int(existing["mirrored_price_record_id"] or 0)
            self.conn.execute(
                """
                UPDATE realtime_price_records
                SET item_name = ?,
                    item_match = ?,
                    item_known = ?,
                    side = ?,
                    amount = ?,
                    currency = ?,
                    want_item = ?,
                    have_item = ?,
                    market_want_amount = ?,
                    market_have_amount = ?,
                    user_want_amount = ?,
                    user_have_amount = ?,
                    source = ?,
                    captured_at = ?,
                    confidence = ?,
                    raw_text = ?,
                    screenshot_path = ?,
                    note = ?,
                    upvotes = ?,
                    downvotes = 0
                WHERE id = ?
                """,
                (
                    clean_item,
                    item_match.strip(),
                    1 if item_known else 0,
                    clean_side,
                    float(amount),
                    clean_currency,
                    want_item.strip(),
                    have_item.strip(),
                    float(market_want_amount),
                    float(market_have_amount),
                    float(user_want_amount),
                    float(user_have_amount),
                    clean_source,
                    clean_captured_at,
                    float(confidence),
                    raw_text,
                    screenshot_path,
                    note,
                    max(0, int(upvotes or 0)),
                    realtime_id,
                ),
            )
        if clean_item and float(amount) > 0 and clean_currency:
            item_id = self.upsert_item(clean_item)
            price_source = f"{clean_source}-{clean_side}"
            if price_record_id > 0:
                self.conn.execute(
                    """
                    UPDATE price_records
                    SET item_id = ?,
                        amount = ?,
                        currency = ?,
                        source = ?,
                        captured_at = ?,
                        confidence = ?,
                        raw_text = ?,
                        screenshot_path = ?,
                        realtime_record_id = ?
                    WHERE id = ?
                    """,
                    (
                        item_id,
                        float(amount),
                        clean_currency,
                        price_source,
                        clean_captured_at,
                        float(confidence),
                        raw_text,
                        screenshot_path,
                        realtime_id,
                        price_record_id,
                    ),
                )
            else:
                cur = self.conn.execute(
                    """
                    INSERT INTO price_records(
                        item_id, amount, currency, source, captured_at,
                        confidence, raw_text, screenshot_path, realtime_record_id
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        float(amount),
                        clean_currency,
                        price_source,
                        clean_captured_at,
                        float(confidence),
                        raw_text,
                        screenshot_path,
                        realtime_id,
                    ),
                )
                price_record_id = int(cur.lastrowid)
                self.conn.execute(
                    "UPDATE realtime_price_records SET mirrored_price_record_id = ? WHERE id = ?",
                    (price_record_id, realtime_id),
                )
        self.conn.commit()
        return realtime_id

    def vote_realtime_price_record(self, record_id: int, vote: int) -> tuple[int, int]:
        if record_id <= 0:
            return 0, 0
        if vote > 0:
            self.conn.execute(
                "UPDATE realtime_price_records SET upvotes = upvotes + 1 WHERE id = ?",
                (int(record_id),),
            )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT upvotes, downvotes FROM realtime_price_records WHERE id = ?",
            (int(record_id),),
        ).fetchone()
        if row is None:
            return 0, 0
        return int(row["upvotes"] or 0), int(row["downvotes"] or 0)

    def realtime_rating_score(self, record_id: int) -> int:
        row = self.conn.execute(
            "SELECT upvotes, downvotes FROM realtime_price_records WHERE id = ?",
            (int(record_id),),
        ).fetchone()
        if row is None:
            return 0
        return int(row["upvotes"] or 0) - int(row["downvotes"] or 0)

    def _currency_quote_candidates(
        self,
        item_aliases: tuple[str, ...],
        currency_aliases: tuple[str, ...],
    ) -> list[tuple[float, str, int]]:
        return [
            (amount, captured_at, record_id)
            for amount, captured_at, record_id, _source, _realtime_id, _upvotes, _downvotes in self._currency_quote_rows(
                item_aliases,
                currency_aliases,
            )
        ]

    def _currency_quote_rows(
        self,
        item_aliases: tuple[str, ...],
        currency_aliases: tuple[str, ...],
        min_realtime_upvotes: int = 0,
    ) -> list[tuple[float, str, int, str, int, int, int]]:
        normalized_items = tuple(normalize_name(name) for name in item_aliases)
        normalized_currencies = tuple(alias.strip().lower() for alias in currency_aliases)
        if not normalized_items or not normalized_currencies:
            return []
        min_upvotes = max(0, int(min_realtime_upvotes or 0))
        params: list[object] = [*normalized_items, *normalized_currencies, min_upvotes]
        rows = self.conn.execute(
            f"""
            SELECT
                r.amount,
                r.captured_at,
                r.id,
                r.source,
                r.realtime_record_id,
                COALESCE(rp.upvotes, 0) AS upvotes,
                COALESCE(rp.downvotes, 0) AS downvotes
            FROM price_records r
            JOIN items i ON i.id = r.item_id
            LEFT JOIN realtime_price_records rp ON rp.id = r.realtime_record_id
            WHERE i.normalized_name IN ({",".join("?" for _ in normalized_items)})
              AND lower(trim(r.currency)) IN ({",".join("?" for _ in normalized_currencies)})
              AND r.amount > 0
              AND (r.realtime_record_id = 0 OR COALESCE(rp.upvotes, 0) >= ?)
            ORDER BY r.captured_at DESC, r.id DESC
            """,
            tuple(params),
        ).fetchall()
        return [
            (
                float(row["amount"]),
                str(row["captured_at"]),
                int(row["id"]),
                str(row["source"]),
                int(row["realtime_record_id"] or 0),
                int(row["upvotes"] or 0),
                int(row["downvotes"] or 0),
            )
            for row in rows
        ]

    @staticmethod
    def _base_currency_aliases(currency: str) -> tuple[str, ...]:
        value = canonical_currency(currency)
        if value == "神圣石":
            return ("神圣石", "Divine Orb", "divine")
        if value == "崇高石":
            return ("崇高石", "Exalted Orb", "exalt", "exalted")
        if value == "混沌石":
            return ("混沌石", "Chaos Orb", "chaos")
        return ()

    @staticmethod
    def _valid_base_currency_pair_amount(source_currency: str, target_currency: str, amount: float) -> bool:
        if amount <= 0:
            return False
        source = canonical_currency(source_currency)
        target = canonical_currency(target_currency)
        if {source, target} == {"神圣石", "崇高石"}:
            divine_to_exalted = amount if source == "神圣石" else 1.0 / amount
            return 10 <= divine_to_exalted <= 1000
        return True

    def get_base_currency_pair_stats(
        self,
        item_currency: str,
        target_currency: str,
        min_realtime_upvotes: int = 0,
    ) -> PriceStats | None:
        source = canonical_currency(item_currency)
        target = canonical_currency(target_currency)
        base_currencies = {"神圣石", "崇高石", "混沌石"}
        if source not in base_currencies or target not in base_currencies:
            return None
        if source == target:
            return PriceStats(
                item_name=source,
                count=1,
                latest_amount=1.0,
                latest_currency=target,
                latest_at="",
                min_amount=1.0,
                max_amount=1.0,
                avg_amount=1.0,
                latest_source="基础通货兑换",
            )

        source_aliases = self._base_currency_aliases(source)
        target_aliases = self._base_currency_aliases(target)
        candidates: list[tuple[str, int, float, str, int, int, int]] = []

        for amount, captured_at, record_id, quote_source, realtime_id, upvotes, downvotes in self._currency_quote_rows(
            source_aliases,
            target_aliases,
            min_realtime_upvotes=min_realtime_upvotes,
        ):
            if self._valid_base_currency_pair_amount(source, target, amount):
                candidates.append((captured_at, record_id, amount, quote_source, realtime_id, upvotes, downvotes))

        for amount, captured_at, record_id, quote_source, realtime_id, upvotes, downvotes in self._currency_quote_rows(
            target_aliases,
            source_aliases,
            min_realtime_upvotes=min_realtime_upvotes,
        ):
            converted = 1.0 / amount
            if self._valid_base_currency_pair_amount(source, target, converted):
                candidates.append((captured_at, record_id, converted, quote_source, realtime_id, upvotes, downvotes))

        if not candidates:
            return None
        realtime_candidates = [candidate for candidate in candidates if candidate[4] > 0]
        if realtime_candidates:
            candidates = realtime_candidates
        captured_at, record_id, amount, quote_source, realtime_id, upvotes, downvotes = sorted(candidates, reverse=True)[0]
        return PriceStats(
            item_name=source,
            count=len(candidates),
            latest_amount=amount,
            latest_currency=target,
            latest_at=captured_at,
            min_amount=amount,
            max_amount=amount,
            avg_amount=amount,
            latest_source=quote_source,
            latest_record_id=record_id,
            realtime_record_id=realtime_id,
            realtime_upvotes=upvotes,
            realtime_downvotes=downvotes,
        )

    def get_base_currency_pair_history(
        self,
        item_currency: str,
        target_currency: str,
        limit: int = 12,
        min_realtime_upvotes: int = 0,
    ) -> list[PriceRecord]:
        source = canonical_currency(item_currency)
        target = canonical_currency(target_currency)
        base_currencies = {"神圣石", "崇高石", "混沌石"}
        if source not in base_currencies or target not in base_currencies or source == target:
            return []
        source_aliases = self._base_currency_aliases(source)
        target_aliases = self._base_currency_aliases(target)
        candidates: list[tuple[str, int, float, str, int]] = []

        for amount, captured_at, record_id, quote_source, realtime_id, _upvotes, _downvotes in self._currency_quote_rows(
            source_aliases,
            target_aliases,
            min_realtime_upvotes=min_realtime_upvotes,
        ):
            if self._valid_base_currency_pair_amount(source, target, amount):
                candidates.append((captured_at, record_id, amount, quote_source, realtime_id))

        for amount, captured_at, record_id, quote_source, realtime_id, _upvotes, _downvotes in self._currency_quote_rows(
            target_aliases,
            source_aliases,
            min_realtime_upvotes=min_realtime_upvotes,
        ):
            converted = 1.0 / amount
            if self._valid_base_currency_pair_amount(source, target, converted):
                candidates.append((captured_at, record_id, converted, quote_source, realtime_id))

        realtime_candidates = [candidate for candidate in candidates if candidate[4] > 0]
        if realtime_candidates:
            candidates = realtime_candidates
        candidates = sorted(candidates, reverse=True)[: max(1, int(limit or 12))]
        candidates.reverse()
        return [
            PriceRecord(
                id=record_id,
                item_name=source,
                amount=amount,
                currency=target,
                source=quote_source,
                captured_at=captured_at,
                confidence=1.0,
                raw_text="",
                screenshot_path="",
                realtime_record_id=realtime_id,
            )
            for captured_at, record_id, amount, quote_source, realtime_id in candidates
        ]

    def get_exalted_per_divine(self) -> float:
        divine_aliases = ("神圣石", "Divine Orb", "divine")
        exalted_aliases = ("崇高石", "Exalted Orb", "exalt", "exalted")
        candidates: list[tuple[str, int, float]] = []
        for amount, captured_at, record_id in self._currency_quote_candidates(divine_aliases, exalted_aliases):
            if 10 <= amount <= 1000:
                candidates.append((captured_at, record_id, amount))
        for amount, captured_at, record_id in self._currency_quote_candidates(exalted_aliases, divine_aliases):
            rate = 1.0 / amount
            if 10 <= rate <= 1000:
                candidates.append((captured_at, record_id, rate))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][2]
        return 160.0

    def get_chaos_per_divine(self) -> float:
        divine_aliases = ("神圣石", "Divine Orb", "divine")
        exalted_aliases = ("崇高石", "Exalted Orb", "exalt", "exalted")
        chaos_aliases = ("混沌石", "Chaos Orb", "chaos")
        exalted_per_divine = self.get_exalted_per_divine()
        candidates: list[tuple[str, int, float]] = []
        for amount, captured_at, record_id in self._currency_quote_candidates(divine_aliases, chaos_aliases):
            candidates.append((captured_at, record_id, amount))
        for amount, captured_at, record_id in self._currency_quote_candidates(chaos_aliases, divine_aliases):
            candidates.append((captured_at, record_id, 1.0 / amount))
        for amount, captured_at, record_id in self._currency_quote_candidates(exalted_aliases, chaos_aliases):
            candidates.append((captured_at, record_id, amount * exalted_per_divine))
        for amount, captured_at, record_id in self._currency_quote_candidates(chaos_aliases, exalted_aliases):
            candidates.append((captured_at, record_id, exalted_per_divine / amount))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][2]
        return 10.0

    def get_price_history(
        self,
        item_name: str,
        limit: int = 20,
        min_realtime_upvotes: int = 0,
        prefer_realtime_if_available: bool = False,
    ) -> list[PriceRecord]:
        rows = self.get_recent_records(
            item_name,
            limit,
            min_realtime_upvotes=min_realtime_upvotes,
            prefer_realtime_if_available=prefer_realtime_if_available,
        )
        return list(reversed(rows))

    def set_favorite(self, item_name: str, favorite: bool) -> None:
        item_id = self.upsert_item(item_name)
        if favorite:
            self.conn.execute(
                "INSERT OR IGNORE INTO favorites(item_id, created_at) VALUES(?, ?)",
                (item_id, utc_now()),
            )
        else:
            self.conn.execute("DELETE FROM favorites WHERE item_id = ?", (item_id,))
        self.conn.commit()

    def set_pinned(self, item_name: str, pinned: bool) -> None:
        item_id = self.upsert_item(item_name)
        if pinned:
            self.conn.execute(
                "INSERT OR IGNORE INTO pinned_items(item_id, created_at) VALUES(?, ?)",
                (item_id, utc_now()),
            )
        else:
            self.conn.execute("DELETE FROM pinned_items WHERE item_id = ?", (item_id,))
        self.conn.commit()

    def is_pinned(self, item_name: str) -> bool:
        normalized = normalize_name(item_name)
        row = self.conn.execute(
            """
            SELECT p.item_id
            FROM items i
            JOIN pinned_items p ON p.item_id = i.id
            WHERE i.normalized_name = ?
            """,
            (normalized,),
        ).fetchone()
        return row is not None

    def delete_item(self, item_name: str) -> None:
        normalized = normalize_name(item_name)
        row = self.conn.execute("SELECT id FROM items WHERE normalized_name = ?", (normalized,)).fetchone()
        if row is None:
            return
        item_id = int(row["id"])
        realtime_ids = [
            int(record["realtime_record_id"])
            for record in self.conn.execute(
                "SELECT realtime_record_id FROM price_records WHERE item_id = ? AND realtime_record_id > 0",
                (item_id,),
            ).fetchall()
        ]
        self.conn.execute("DELETE FROM favorites WHERE item_id = ?", (item_id,))
        self.conn.execute("DELETE FROM pinned_items WHERE item_id = ?", (item_id,))
        self.conn.execute("DELETE FROM price_records WHERE item_id = ?", (item_id,))
        self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        if realtime_ids:
            self.conn.execute(
                f"DELETE FROM realtime_price_records WHERE id IN ({','.join('?' for _ in realtime_ids)})",
                tuple(realtime_ids),
            )
        self.conn.execute(
            """
            DELETE FROM realtime_price_records
            WHERE lower(trim(item_name)) = ?
               OR lower(trim(item_match)) = ?
            """,
            (normalized, normalized),
        )
        self.conn.commit()

    def clear_all_data(self) -> None:
        self.conn.execute("DELETE FROM favorites")
        self.conn.execute("DELETE FROM pinned_items")
        self.conn.execute("DELETE FROM price_records")
        self.conn.execute("DELETE FROM realtime_price_records")
        self.conn.execute("DELETE FROM market_exchange_records")
        self.conn.execute("DELETE FROM items")
        self.conn.commit()


def sparkline(values: list[float]) -> str:
    if not values:
        return ""
    ticks = "▁▂▃▄▅▆▇█"
    low = min(values)
    high = max(values)
    if high == low:
        return ticks[0] * min(len(values), 12)
    chars = []
    for value in values[-12:]:
        idx = round((value - low) / (high - low) * (len(ticks) - 1))
        chars.append(ticks[idx])
    return "".join(chars)


def trend_percent(values: list[float]) -> str:
    if len(values) < 2 or values[0] == 0:
        return ""
    value = (values[-1] - values[0]) / values[0] * 100
    return f"{value:+.0f}%"


def canonical_currency(currency: str) -> str:
    value = currency.strip().lower()
    if value in {"exalted orb", "exalt", "exalted", "崇高", "崇高石"}:
        return "崇高石"
    if value in {"divine orb", "divine", "神圣", "神圣石"}:
        return "神圣石"
    if value in {"chaos orb", "chaos", "混沌", "混沌石"}:
        return "混沌石"
    return currency


def convert_amount(
    amount: float,
    source_currency: str,
    target_currency: str,
    exalted_per_divine: float,
    chaos_per_divine: float = 0,
) -> float:
    source = canonical_currency(source_currency)
    target = canonical_currency(target_currency)
    if source == target:
        return amount
    values_in_divine = {"神圣石": 1.0, "崇高石": 1.0 / max(0.000001, exalted_per_divine)}
    if chaos_per_divine:
        values_in_divine["混沌石"] = 1.0 / max(0.000001, chaos_per_divine)
    if source in values_in_divine and target in values_in_divine:
        return amount * values_in_divine[source] / values_in_divine[target]
    return amount


def display_amount_for_item(
    item_name: str,
    amount: float,
    source_currency: str,
    target_currency: str,
    exalted_per_divine: float,
    chaos_per_divine: float = 0,
) -> float:
    item_currency = canonical_currency(item_name)
    target = canonical_currency(target_currency)
    if item_currency in {"神圣石", "崇高石", "混沌石"} and target in {"神圣石", "崇高石", "混沌石"}:
        return convert_amount(1.0, item_currency, target, exalted_per_divine, chaos_per_divine)
    return convert_amount(amount, source_currency, target_currency, exalted_per_divine, chaos_per_divine)
