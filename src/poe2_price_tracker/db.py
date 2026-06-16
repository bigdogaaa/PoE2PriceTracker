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
    item_name: str
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


class PriceDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
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

    def search_items(self, query: str, limit: int = 12) -> list[str]:
        normalized = normalize_name(query)
        if not normalized:
            return []
        rows = self.conn.execute(
            """
            SELECT name, normalized_name
            FROM items
            WHERE normalized_name LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (f"%{normalized}%", limit),
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
            score = SequenceMatcher(None, normalized, norm).ratio()
            if score >= 0.45:
                scored.append((score, name))
        scored.sort(reverse=True)
        return direct + [name for _, name in scored[: max(0, limit - len(direct))]]

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
        if query.strip():
            where.append("i.normalized_name LIKE ?")
            params.append(f"%{normalize_name(query)}%")
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
            trend_match = __import__("re").search(r"trend=([+-]?\d+(?:\.\d+)?%)", str(row["latest_raw_text"]))
            result.append(
                MarketRow(
                    item_name=str(row["item_name"]),
                    latest_amount=float(row["latest_amount"]),
                    latest_currency=str(row["latest_currency"]),
                    latest_at=str(row["latest_at"]),
                    source=str(row["source"]),
                    count=int(row["count"]),
                    min_amount=float(row["min_amount"]),
                    max_amount=float(row["max_amount"]),
                    avg_amount=float(row["avg_amount"]),
                    sparkline=sparkline([record.amount for record in history]),
                    trend_percent=trend_match.group(1) if trend_match else trend_percent([record.amount for record in history]),
                    favorite=bool(row["favorite"]),
                    pinned=bool(row["pinned"]),
                )
            )
        return result

    def count_market_rows(self, query: str = "", source_filter: str = "", favorites_only: bool = False) -> int:
        where = []
        params: list[object] = []
        if query.strip():
            where.append("i.normalized_name LIKE ?")
            params.append(f"%{normalize_name(query)}%")
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
