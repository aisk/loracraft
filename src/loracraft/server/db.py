"""SQLite storage. Plain sqlite3, one connection per request."""

import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,  -- ids name files and URLs, so never reuse one
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'character',  -- character | style | concept
    trigger     TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    tagging_profile TEXT NOT NULL DEFAULT '',       -- TaggingProfile JSON, last used for auto-captioning
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,  -- ids name files and URLs, so never reuse one
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,          -- file name inside the project's images directory
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    caption     TEXT NOT NULL DEFAULT '',
    caption_source TEXT NOT NULL DEFAULT '',        -- which model and goal produced the caption, if any
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (project_id, filename)
);
CREATE INDEX IF NOT EXISTS images_project ON images(project_id);

-- Captions proposed by a vision model, waiting for the user to accept or discard.
CREATE TABLE IF NOT EXISTS tag_suggestions (
    image_id    INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    caption     TEXT NOT NULL,
    groups      TEXT NOT NULL,          -- JSON: tags by category
    issues      TEXT NOT NULL,          -- JSON: tags that were dropped, corrected or not recognised
    model       TEXT NOT NULL,
    goal        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,  -- ids name files and URLs, so never reuse one
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | stopped | failed
    config      TEXT NOT NULL,                   -- TrainConfig JSON, including the dataset snapshot
    notes       TEXT NOT NULL DEFAULT '',
    rating      INTEGER NOT NULL DEFAULT 0,
    best_checkpoint TEXT NOT NULL DEFAULT '',   -- file name of the checkpoint the user picked
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# Statements that bring a database created by an earlier version up to SCHEMA, oldest first.
# A database's `user_version` is the number of entries already applied to it; append, never edit.
MIGRATIONS: list[str] = []


def default_workspace() -> Path:
    """The per-user data directory of this platform."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "loracraft"


def workspace() -> Path:
    """Root directory for all user data: the database, images, runs."""
    home = os.environ.get("LORACRAFT_HOME")
    root = Path(home).resolve() if home else default_workspace()
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_dir(project_id: int) -> Path:
    path = workspace() / "projects" / str(project_id)
    (path / "images").mkdir(parents=True, exist_ok=True)
    (path / "thumbs").mkdir(exist_ok=True)
    (path / "runs").mkdir(exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    # One connection per request; FastAPI may hop threads within a request.
    conn = sqlite3.connect(workspace() / "loracraft.db", check_same_thread=False, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session():
    """A connection for use outside a request: commits on success, rolls back on error, always closes."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    with session() as conn:
        fresh = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'projects'").fetchone() is None
        conn.executescript(SCHEMA)
        # A fresh database is created from SCHEMA, which already includes every migration.
        version = len(MIGRATIONS) if fresh else conn.execute("PRAGMA user_version").fetchone()[0]
        for statement in MIGRATIONS[version:]:
            conn.executescript(statement)
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")


def get_db():
    """FastAPI dependency: a connection that commits on success."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
