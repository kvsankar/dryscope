"""SQLite cache for LLM and embedding results."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path


def _make_key(content: str, model: str, prompt_version: str) -> str:
    """Create a cache key from content hash + model + prompt version."""
    raw = f"{content}|{model}|{prompt_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class CacheStats:
    """Cache statistics."""

    entry_count: int
    embedding_count: int
    coding_count: int
    db_size_bytes: int
    hit_count: int
    miss_count: int


class Cache:
    """SQLite-backed cache for embeddings and LLM responses."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,
        )
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()
        self._configure_connection()
        self._init_db()

    def _configure_connection(self) -> None:
        """Tune SQLite for concurrent readers/writers across processes."""
        self.conn.execute("PRAGMA busy_timeout=30000")
        # Switching journal mode can race with another process opening the same
        # cache. Retry briefly, then continue: an already-initialized cache can
        # still be used even if this connection could not flip the mode itself.
        attempts = 5
        for attempt in range(attempts):
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == attempts - 1:
                    break
                time.sleep(0.1 * (attempt + 1))
        self.conn.execute("PRAGMA synchronous=NORMAL")

    def _execute_write(self, sql: str, params: tuple[object, ...]) -> None:
        """Execute a write with simple retry for transient lock contention."""
        attempts = 5
        for attempt in range(attempts):
            try:
                self.conn.execute(sql, params)
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == attempts - 1:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def _init_db(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def get_embedding(self, content: str, model: str) -> list[float] | None:
        """Retrieve a cached embedding vector."""
        key = _make_key(content, model, "embedding_v1")
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM cache WHERE key = ? AND kind = 'embedding'",
                (key,),
            ).fetchone()
            if row is not None:
                self._hits += 1
                return json.loads(row[0])
            self._misses += 1
        return None

    def set_embedding(self, content: str, model: str, vector: list[float]) -> None:
        """Store an embedding vector in the cache."""
        key = _make_key(content, model, "embedding_v1")
        with self._lock:
            self._execute_write(
                "INSERT OR REPLACE INTO cache (key, kind, value) VALUES (?, 'embedding', ?)",
                (key, json.dumps(vector)),
            )

    def get_coding(self, content: str, model: str, prompt_version: str) -> str | None:
        """Retrieve a cached LLM coding response."""
        key = _make_key(content, model, prompt_version)
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM cache WHERE key = ? AND kind = 'coding'",
                (key,),
            ).fetchone()
            if row is not None:
                self._hits += 1
                return row[0]
            self._misses += 1
        return None

    def set_coding(self, content: str, model: str, prompt_version: str, response: str) -> None:
        """Store an LLM coding response in the cache."""
        key = _make_key(content, model, prompt_version)
        with self._lock:
            self._execute_write(
                "INSERT OR REPLACE INTO cache (key, kind, value) VALUES (?, 'coding', ?)",
                (key, response),
            )

    def commit(self) -> None:
        """Flush pending writes to disk."""
        self.conn.commit()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            embeddings = self.conn.execute(
                "SELECT COUNT(*) FROM cache WHERE kind = 'embedding'"
            ).fetchone()[0]
            codings = self.conn.execute(
                "SELECT COUNT(*) FROM cache WHERE kind = 'coding'"
            ).fetchone()[0]
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            return CacheStats(
                entry_count=total,
                embedding_count=embeddings,
                coding_count=codings,
                db_size_bytes=db_size,
                hit_count=self._hits,
                miss_count=self._misses,
            )

    def clear(self) -> None:
        """Delete all cache entries."""
        with self._lock:
            self.conn.execute("DELETE FROM cache")
            self.conn.commit()

    def close(self) -> None:
        """Commit pending writes and close the database connection."""
        self.conn.commit()
        self.conn.close()
