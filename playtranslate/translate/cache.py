"""SQLite store for translations and the user's own corrections.

* translations: machine output, per game profile. Cleared for a profile when
  its glossary changes, because the glossary changes the output.
* corrections: what the user typed to fix a line. Always wins and is never
  cleared automatically.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    profile TEXT NOT NULL,
    key TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    engine TEXT NOT NULL,
    created REAL NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile, key)
);
CREATE TABLE IF NOT EXISTS corrections (
    profile TEXT NOT NULL,
    key TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    created REAL NOT NULL,
    PRIMARY KEY (profile, key)
);
"""


class TranslationCache:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        with self._lock:
            if self.path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(SCHEMA)

    def get(self, profile: str, key: str) -> tuple[str, str] | None:
        """(target, origin) where origin is 'user' or 'cache'."""
        with self._lock:
            row = self._db.execute(
                "SELECT target FROM corrections WHERE profile=? AND key=?", (profile, key)
            ).fetchone()
            if row:
                return row[0], "user"
            row = self._db.execute(
                "SELECT target FROM translations WHERE profile=? AND key=?", (profile, key)
            ).fetchone()
            if row:
                self._db.execute(
                    "UPDATE translations SET hits = hits + 1 WHERE profile=? AND key=?", (profile, key)
                )
                return row[0], "cache"
        return None

    def put(self, profile: str, key: str, source: str, target: str, engine: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO translations (profile, key, source, target, engine, created, hits)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)",
                (profile, key, source, target, engine, time.time()),
            )

    def correct(self, profile: str, key: str, source: str, target: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO corrections (profile, key, source, target, created) VALUES (?, ?, ?, ?, ?)",
                (profile, key, source, target, time.time()),
            )

    def remove_correction(self, profile: str, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM corrections WHERE profile=? AND key=?", (profile, key))

    def clear_machine(self, profile: str) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM translations WHERE profile=?", (profile,))
            return cur.rowcount

    def rename_profile(self, old: str, new: str) -> None:
        with self._lock:
            for table in ("translations", "corrections"):
                self._db.execute(f"UPDATE OR REPLACE {table} SET profile=? WHERE profile=?", (new, old))

    def stats(self, profile: str) -> dict:
        with self._lock:
            t = self._db.execute("SELECT COUNT(*) FROM translations WHERE profile=?", (profile,)).fetchone()[0]
            c = self._db.execute("SELECT COUNT(*) FROM corrections WHERE profile=?", (profile,)).fetchone()[0]
        return {"translations": t, "corrections": c}

    def import_many(self, profile: str, rows: list[tuple[str, str, str]], engine: str = "pack") -> int:
        """Add (key, source, target) rows that are not cached yet. Never overwrites anything."""
        now = time.time()
        with self._lock:
            before = self._db.total_changes
            self._db.executemany(
                "INSERT OR IGNORE INTO translations (profile, key, source, target, engine, created, hits)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)",
                [(profile, k, s, t, engine, now) for k, s, t in rows],
            )
            return self._db.total_changes - before

    def export(self, profile: str) -> dict[str, str]:
        """source -> target for a game, with the player's corrections winning."""
        with self._lock:
            out = dict(self._db.execute(
                "SELECT source, target FROM translations WHERE profile=? ORDER BY hits DESC", (profile,)).fetchall())
            out.update(dict(self._db.execute(
                "SELECT source, target FROM corrections WHERE profile=?", (profile,)).fetchall()))
        return out

    def close(self) -> None:
        with self._lock:
            self._db.close()
