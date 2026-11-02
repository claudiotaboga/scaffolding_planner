"""Minimal document store on SQLite (MVP). Same JSON documents map 1:1 to PostgreSQL JSONB tables
(projects, drawings, runs, mappings) — swap the connection layer, keep the documents."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("VSR_DB", ROOT / "var" / "vsr.sqlite"))
FILES_DIR = Path(os.environ.get("VSR_FILES", ROOT / "var" / "files"))

_lock = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drawings (id TEXT PRIMARY KEY, project_id TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (run_id TEXT, project_id TEXT, area_id TEXT, created TEXT, doc TEXT NOT NULL,
                                 PRIMARY KEY (run_id, project_id, area_id));
CREATE TABLE IF NOT EXISTS mappings (template TEXT, kind TEXT, doc TEXT NOT NULL, PRIMARY KEY (template, kind));
"""


class Store:
    def __init__(self, db_path: Path | str = DB_PATH, files_dir: Path | str = FILES_DIR):
        self.db_path = Path(db_path)
        self.files_dir = Path(files_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def _put(self, sql: str, args: tuple):
        with _lock:
            self.conn.execute(sql, args)
            self.conn.commit()

    # projects
    def save_project(self, doc: dict):
        self._put("INSERT OR REPLACE INTO projects VALUES (?, ?)", (doc["id"], json.dumps(doc)))

    def get_project(self, pid: str) -> Optional[dict]:
        r = self.conn.execute("SELECT doc FROM projects WHERE id=?", (pid,)).fetchone()
        return json.loads(r[0]) if r else None

    def list_projects(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.conn.execute("SELECT doc FROM projects ORDER BY id")]

    def delete_project(self, pid: str):
        for t, c in (("projects", "id"), ("drawings", "project_id"), ("runs", "project_id")):
            self._put(f"DELETE FROM {t} WHERE {c}=?", (pid,))

    # drawings
    def save_drawing(self, doc: dict):
        self._put("INSERT OR REPLACE INTO drawings VALUES (?, ?, ?)", (doc["id"], doc["project_id"], json.dumps(doc)))

    def get_drawing(self, did: str) -> Optional[dict]:
        r = self.conn.execute("SELECT doc FROM drawings WHERE id=?", (did,)).fetchone()
        return json.loads(r[0]) if r else None

    def list_drawings(self, pid: str) -> list[dict]:
        return [json.loads(r[0]) for r in self.conn.execute("SELECT doc FROM drawings WHERE project_id=?", (pid,))]

    # runs (immutable)
    def save_run(self, pid: str, aid: str, run: dict):
        self._put("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?)",
                  (run["run_id"], pid, aid, run["created"], json.dumps(run)))

    def get_run(self, rid: str) -> Optional[dict]:
        r = self.conn.execute("SELECT doc FROM runs WHERE run_id=? ORDER BY created DESC", (rid,)).fetchone()
        return json.loads(r[0]) if r else None

    def latest_runs(self, pid: str) -> dict[str, dict]:
        out = {}
        for aid, doc in self.conn.execute("SELECT area_id, doc FROM runs WHERE project_id=? ORDER BY created", (pid,)):
            out[aid] = json.loads(doc)
        return out

    def list_runs(self, pid: str) -> list[dict]:
        return [{"run_id": r[0], "area_id": r[1], "created": r[2]} for r in self.conn.execute(
            "SELECT run_id, area_id, created FROM runs WHERE project_id=? ORDER BY created DESC", (pid,))]

    # mapping templates
    def save_mapping(self, template: str, kind: str, mapping: dict):
        self._put("INSERT OR REPLACE INTO mappings VALUES (?, ?, ?)", (template, kind, json.dumps(mapping)))

    def get_mapping(self, template: str, kind: str) -> Optional[dict]:
        r = self.conn.execute("SELECT doc FROM mappings WHERE template=? AND kind=?", (template, kind)).fetchone()
        return json.loads(r[0]) if r else None

    def list_mappings(self) -> list[dict]:
        return [{"template": r[0], "kind": r[1], "mapping": json.loads(r[2])}
                for r in self.conn.execute("SELECT template, kind, doc FROM mappings")]
