import sqlite3
from threading import Lock
from pathlib import Path
from typing import Iterable

from .config import settings


DB_PATH = settings.data_dir / "panel.sqlite"
_init_lock = Lock()
_initialized = False


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    global _initialized
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                domain TEXT NOT NULL UNIQUE,
                php_version TEXT NOT NULL DEFAULT '8.3',
                db_engine TEXT NOT NULL DEFAULT 'mariadb',
                db_name TEXT NOT NULL,
                db_user TEXT NOT NULL,
                db_password TEXT NOT NULL,
                sftp_password TEXT NOT NULL,
                sftp_port INTEGER NOT NULL DEFAULT 0,
                waf_enabled INTEGER NOT NULL DEFAULT 0,
                php_ini_preset TEXT NOT NULL DEFAULT 'standard',
                resource_preset TEXT NOT NULL DEFAULT 'medium',
                cms_app TEXT NOT NULL DEFAULT 'none',
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sites)").fetchall()}
        if "waf_enabled" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN waf_enabled INTEGER NOT NULL DEFAULT 0")
        if "php_ini_preset" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN php_ini_preset TEXT NOT NULL DEFAULT 'standard'")
        if "resource_preset" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN resource_preset TEXT NOT NULL DEFAULT 'medium'")
        if "cms_app" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN cms_app TEXT NOT NULL DEFAULT 'none'")
        if "sftp_port" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN sftp_port INTEGER NOT NULL DEFAULT 0")
        used_ports = {
            row["sftp_port"]
            for row in conn.execute("SELECT sftp_port FROM sites WHERE sftp_port > 0").fetchall()
        }
        next_port = 22000
        for row in conn.execute("SELECT id FROM sites WHERE sftp_port = 0 ORDER BY id").fetchall():
            while next_port in used_ports:
                next_port += 1
            conn.execute("UPDATE sites SET sftp_port = ? WHERE id = ?", (next_port, row["id"]))
            used_ports.add(next_port)
            next_port += 1
        conn.commit()
    _initialized = True


def ensure_db() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if not _initialized:
            init_db()


def query_all(sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
    ensure_db()
    with connect() as conn:
        return list(conn.execute(sql, tuple(params)).fetchall())


def query_one(sql: str, params: Iterable = ()) -> sqlite3.Row | None:
    ensure_db()
    with connect() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable = ()) -> None:
    ensure_db()
    with connect() as conn:
        conn.execute(sql, tuple(params))
        conn.commit()
