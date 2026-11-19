"""Слой хранения: SQLite + FTS5 для фактов и полнотекстового поиска."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


def default_db_path() -> Path:
    """Путь к БД по умолчанию (переопределяется CONTEXT_SAVER_DB)."""
    env = os.environ.get("CONTEXT_SAVER_DB")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".context-saver" / "memory.db").resolve()


class MemoryStorage:
    """Простое хранилище фактов на SQLite с FTS5-поиском."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    content     TEXT NOT NULL,
                    category    TEXT DEFAULT '',
                    tags        TEXT DEFAULT '',
                    created_at  TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
                USING fts5(content, category, tags,
                           content='facts', content_rowid='id');

                CREATE TRIGGER IF NOT EXISTS facts_ai
                AFTER INSERT ON facts BEGIN
                    INSERT INTO facts_fts(rowid, content, category, tags)
                    VALUES (new.id, new.content, new.category, new.tags);
                END;

                CREATE TRIGGER IF NOT EXISTS facts_ad
                AFTER DELETE ON facts BEGIN
                    INSERT INTO facts_fts(facts_fts, rowid, content, category, tags)
                    VALUES ('delete', old.id, old.content, old.category, old.tags);
                END;

                CREATE TRIGGER IF NOT EXISTS facts_au
                AFTER UPDATE ON facts BEGIN
                    INSERT INTO facts_fts(facts_fts, rowid, content, category, tags)
                    VALUES ('delete', old.id, old.content, old.category, old.tags);
                    INSERT INTO facts_fts(rowid, content, category, tags)
                    VALUES (new.id, new.content, new.category, new.tags);
                END;
                """
            )

    # ---------- API ----------

    def save(self, content: str, category: str = "", tags: str = "") -> int:
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO facts (content, category, tags, created_at) "
                "VALUES (?, ?, ?, ?)",
                (content, category, tags, created),
            )
            return int(cur.lastrowid)

    def recall(self, keyword: str, limit: int = 3) -> list[sqlite3.Row]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id, content, category, tags, created_at "
                "FROM facts WHERE content LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (f"%{keyword}%", limit),
            )
            return list(cur.fetchall())

    def search(self, query: str, limit: int = 5) -> list[sqlite3.Row]:
        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT f.id, f.content, f.category, f.tags, f.created_at
                FROM facts_fts
                JOIN facts f ON f.id = facts_fts.rowid
                WHERE facts_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
            return list(cur.fetchall())

    def recent(self, limit: int = 10) -> list[sqlite3.Row]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id, content, category, tags, created_at "
                "FROM facts ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return list(cur.fetchall())

    def forget(self, fact_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            return cur.rowcount > 0

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            per_cat = conn.execute(
                "SELECT category, COUNT(*) c FROM facts "
                "GROUP BY category ORDER BY c DESC"
            ).fetchall()
            size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total_facts": total,
            "by_category": {r["category"] or "(без категории)": r["c"] for r in per_cat},
            "db_path": str(self.db_path),
            "db_size_bytes": size,
        }
