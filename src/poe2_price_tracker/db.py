from __future__ import annotations

import sqlite3
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


@dataclass(frozen=True)
class IconAsset:
    name: str
    kind: str
    page_url: str
    icon_url: str
    local_path: str
    phash: str


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
                screenshot_path TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_items_normalized_name
                ON items(normalized_name);
            CREATE INDEX IF NOT EXISTS idx_price_records_item_time
                ON price_records(item_id, captured_at DESC);

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
            """
        )
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
    ) -> int:
        item_id = self.upsert_item(item_name)
        cur = self.conn.execute(
            """
            INSERT INTO price_records(
                item_id, amount, currency, source, captured_at,
                confidence, raw_text, screenshot_path
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                float(amount),
                currency.strip(),
                source,
                utc_now(),
                float(confidence),
                raw_text,
                screenshot_path,
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
                screenshot_path = ?
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

    def get_stats(self, item_name: str) -> PriceStats | None:
        normalized = normalize_name(item_name)
        row = self.conn.execute(
            """
            SELECT
                i.name AS item_name,
                COUNT(r.id) AS count,
                (
                    SELECT amount FROM price_records rr
                    WHERE rr.item_id = i.id
                    ORDER BY captured_at DESC, id DESC LIMIT 1
                ) AS latest_amount,
                (
                    SELECT currency FROM price_records rr
                    WHERE rr.item_id = i.id
                    ORDER BY captured_at DESC, id DESC LIMIT 1
                ) AS latest_currency,
                (
                    SELECT captured_at FROM price_records rr
                    WHERE rr.item_id = i.id
                    ORDER BY captured_at DESC, id DESC LIMIT 1
                ) AS latest_at,
                MIN(r.amount) AS min_amount,
                MAX(r.amount) AS max_amount,
                AVG(r.amount) AS avg_amount
            FROM items i
            JOIN price_records r ON r.item_id = i.id
            WHERE i.normalized_name = ?
            GROUP BY i.id
            """,
            (normalized,),
        ).fetchone()
        if not row:
            matches = self.search_items(item_name, limit=1)
            if not matches:
                return None
            if normalize_name(matches[0]) == normalized:
                return None
            return self.get_stats(matches[0])
        return PriceStats(
            item_name=str(row["item_name"]),
            count=int(row["count"]),
            latest_amount=float(row["latest_amount"]),
            latest_currency=str(row["latest_currency"]),
            latest_at=str(row["latest_at"]),
            min_amount=float(row["min_amount"]),
            max_amount=float(row["max_amount"]),
            avg_amount=float(row["avg_amount"]),
        )

    def get_recent_records(self, item_name: str = "", limit: int = 30) -> list[PriceRecord]:
        params: tuple[object, ...]
        where = ""
        if item_name.strip():
            where = "WHERE i.normalized_name = ?"
            params = (normalize_name(item_name), limit)
        else:
            params = (limit,)
        rows = self.conn.execute(
            f"""
            SELECT
                r.id, i.name AS item_name, r.amount, r.currency, r.source,
                r.captured_at, r.confidence, r.raw_text, r.screenshot_path
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
            )
            for row in rows
        ]

    def get_market_rows(
        self,
        query: str = "",
        source_filter: str = "",
        favorites_only: bool = False,
        sort_by: str = "latest_at",
        descending: bool = True,
        offset: int = 0,
        limit: int = 500,
    ) -> list[MarketRow]:
        allowed_sort = {
            "name": "i.name",
            "price": "latest_amount",
            "latest_at": "latest_at",
            "count": "count",
        }
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
        params.extend((limit, offset))
        rows = self.conn.execute(
            f"""
            WITH latest AS (
                SELECT r.*
                FROM price_records r
                JOIN (
                    SELECT item_id, MAX(id) AS latest_id
                    FROM price_records
                    GROUP BY item_id
                ) x ON x.latest_id = r.id
            )
            SELECT
                i.id AS item_id,
                i.name AS item_name,
                latest.amount AS latest_amount,
                latest.currency AS latest_currency,
                latest.captured_at AS latest_at,
                latest.source AS source,
                latest.raw_text AS latest_raw_text,
                COALESCE(icon.local_path, '') AS item_icon_path,
                COUNT(r.id) AS count,
                MIN(r.amount) AS min_amount,
                MAX(r.amount) AS max_amount,
                AVG(r.amount) AS avg_amount,
                f.item_id IS NOT NULL AS favorite,
                p.item_id IS NOT NULL AS pinned
            FROM items i
            JOIN latest ON latest.item_id = i.id
            JOIN price_records r ON r.item_id = i.id
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
            ORDER BY {sort_expr} {direction}
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        ).fetchall()
        result = []
        for row in rows:
            history = self.get_price_history(str(row["item_name"]), limit=12)
            history_currency = str(row["latest_currency"])
            conversion_rate = self.get_exalted_per_divine()
            history_values = [
                convert_amount(record.amount, record.currency, history_currency, conversion_rate)
                for record in history
            ]
            trend_match = __import__("re").search(r"trend=([+-]?\d+(?:\.\d+)?%)", str(row["latest_raw_text"]))
            local_trend = trend_percent(history_values)
            display_trend = local_trend if len(history_values) >= 2 else (trend_match.group(1) if trend_match else "")
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
                )
            )
        return result

    def count_market_rows(self, query: str = "", source_filter: str = "", favorites_only: bool = False) -> int:
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
        row = self.conn.execute(
            f"""
            WITH latest AS (
                SELECT r.*
                FROM price_records r
                JOIN (
                    SELECT item_id, MAX(id) AS latest_id
                    FROM price_records
                    GROUP BY item_id
                ) x ON x.latest_id = r.id
            )
            SELECT COUNT(DISTINCT i.id) AS count
            FROM items i
            JOIN latest ON latest.item_id = i.id
            JOIN price_records r ON r.item_id = i.id
            LEFT JOIN favorites f ON f.item_id = i.id
            {where_sql}
            """,
            tuple(params),
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

    def get_exalted_per_divine(self) -> float:
        for name in ("神圣石", "Divine Orb"):
            stats = self.get_stats(name)
            if stats and stats.latest_amount > 0 and canonical_currency(stats.latest_currency) == "崇高石":
                return stats.latest_amount
        return 160.0

    def get_price_history(self, item_name: str, limit: int = 20) -> list[PriceRecord]:
        rows = self.get_recent_records(item_name, limit)
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
        self.conn.execute("DELETE FROM favorites WHERE item_id = ?", (item_id,))
        self.conn.execute("DELETE FROM pinned_items WHERE item_id = ?", (item_id,))
        self.conn.execute("DELETE FROM price_records WHERE item_id = ?", (item_id,))
        self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.conn.commit()

    def clear_all_data(self) -> None:
        self.conn.execute("DELETE FROM favorites")
        self.conn.execute("DELETE FROM pinned_items")
        self.conn.execute("DELETE FROM price_records")
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
    return currency


def convert_amount(amount: float, source_currency: str, target_currency: str, exalted_per_divine: float) -> float:
    source = canonical_currency(source_currency)
    target = canonical_currency(target_currency)
    if source == target:
        return amount
    if source == "神圣石" and target == "崇高石":
        return amount * exalted_per_divine
    if source == "崇高石" and target == "神圣石":
        return amount / exalted_per_divine
    return amount
