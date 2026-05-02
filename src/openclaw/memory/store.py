"""Memory store. SQLite-backed, profile-scoped. Spec §13.

v0.1 ships exactly one table — typed preferences. The schema is intentionally
minimal: there is no LLM-arbitrary memory.write tool. All writes go through
schema-validated, typed paths.

Every table includes profile_id as a column and is queried by profile_id at
the database layer. v0.1 sets profile_id = "default" for all rows; v0.2
turns on multi-profile without a schema migration.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

VALID_PREFERENCE_KEYS = frozenset({"default_signature", "summary_style"})


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                profile_id TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (profile_id, key)
            );
            """
        )
        self._conn.commit()

    def get_preference(self, profile_id: str, key: str) -> str | None:
        cur = self._conn.execute(
            "SELECT value FROM preferences WHERE profile_id = ? AND key = ?",
            (profile_id, key),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set_preference(self, profile_id: str, key: str, value: str) -> None:
        if key not in VALID_PREFERENCE_KEYS:
            raise ValueError(f"Invalid preference key: {key}")
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO preferences (profile_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id, key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (profile_id, key, value, now),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
