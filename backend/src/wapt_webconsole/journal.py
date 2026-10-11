"""Audit journal: who did what, on which hosts, with which result (SQLite in the data volume).

The WAPT server only sees its admin account (the only one on Discovery): this journal is the record of the actions
of each console user. Entries are only appended, never edited.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    user TEXT NOT NULL,
    role TEXT NOT NULL,
    ip TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    targets TEXT NOT NULL DEFAULT '[]',
    params TEXT NOT NULL DEFAULT '{}',
    ok INTEGER NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS journal_at ON journal(at);
"""


class Journal:
    def __init__(self, path: Path, retention_days: int = 365):
        self.path = path
        self.retention_days = retention_days
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)
            db.execute("DELETE FROM journal WHERE at < ?", (time.time() - retention_days * 86400,))

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _add(self, entry: tuple) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO journal (at, user, role, ip, action, targets, params, ok, detail) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", entry)

    async def add(self, *, user: str, role: str, ip: str, action: str, targets: list[dict] | None = None,
                  params: dict | None = None, ok: bool = True, detail: str = "") -> None:
        entry = (time.time(), user, role, ip, action, json.dumps(targets or [], ensure_ascii=False),
                 json.dumps(params or {}, ensure_ascii=False), int(ok), detail[:2000])
        await asyncio.to_thread(self._add, entry)

    def _list(self, limit: int, before: int | None, user: str | None, host: str | None) -> list[dict]:
        where, args = [], []
        if before:
            where.append("id < ?")
            args.append(before)
        if user:
            where.append("user = ?")
            args.append(user)
        if host:
            where.append("targets LIKE ?")
            args.append(f'%"{host}"%')
        sql = "SELECT * FROM journal" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY id DESC LIMIT ?"
        with self._connect() as db:
            rows = db.execute(sql, [*args, limit]).fetchall()
        return [{**dict(r), "targets": json.loads(r["targets"]), "params": json.loads(r["params"]), "ok": bool(r["ok"])}
                for r in rows]

    async def list(self, limit: int = 100, before: int | None = None, user: str | None = None,
                   host: str | None = None) -> list[dict]:
        return await asyncio.to_thread(self._list, min(limit, 500), before, user, host)
