"""Database helpers for the Docker Hosting Panel.

Adds a `users` table and links `sites.owner_id` to it.
Existing sites are auto-linked to a user with the same username.
"""
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
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

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
                custom_image TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'created',
                owner_id INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Forward-migration columns (older deployments).
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sites)").fetchall()}
        if "waf_enabled" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN waf_enabled INTEGER NOT NULL DEFAULT 0")
        if "php_ini_preset" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN php_ini_preset TEXT NOT NULL DEFAULT 'standard'")
        if "resource_preset" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN resource_preset TEXT NOT NULL DEFAULT 'medium'")
        if "cms_app" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN cms_app TEXT NOT NULL DEFAULT 'none'")
        if "custom_image" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN custom_image TEXT NOT NULL DEFAULT ''")
        if "sftp_port" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN sftp_port INTEGER NOT NULL DEFAULT 0")
        if "owner_id" not in columns:
            conn.execute("ALTER TABLE sites ADD COLUMN owner_id INTEGER REFERENCES users(id)")

        # Seed admin from env (one-time).
        if not conn.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
            from .auth import hash_password
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                (settings.admin_username, hash_password(settings.admin_password)),
            )

        # Seed users for any existing site that doesn't have a user yet.
        # Login password == site's sftp_password (so customers can use what they already have).
        from .auth import hash_password
        existing_usernames = {
            row["username"]
            for row in conn.execute("SELECT username FROM users").fetchall()
        }
        for row in conn.execute("SELECT username, sftp_password FROM sites").fetchall():
            if row["username"] not in existing_usernames:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'user')",
                    (row["username"], hash_password(row["sftp_password"])),
                )
                existing_usernames.add(row["username"])

        # Auto-link sites to users (only those not yet linked).
        conn.execute(
            """
            UPDATE sites SET owner_id = (
                SELECT id FROM users WHERE users.username = sites.username
            )
            WHERE owner_id IS NULL
            """
        )

        # Auto-assign SFTP ports (carry over from existing logic).
        used_ports = {
            row["sftp_port"]
            for row in conn.execute("SELECT sftp_port FROM sites WHERE sftp_port > 0").fetchall()
        }
        next_port = 22000
        for row in conn.execute("SELECT id FROM sites WHERE sftp_port = 0 ORDER BY id").fetchall():
            while next_port in used_ports:
                next_port += 1
            conn.execute(
                "UPDATE sites SET sftp_port = ? WHERE id = ?", (next_port, row["id"])
            )
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


# Convenience helpers -----------------------------------------------------

def get_user_by_username(username: str) -> sqlite3.Row | None:
    return query_one(
        "SELECT id, username, password_hash, role, email FROM users WHERE username = ?",
        (username,),
    )


def list_sites_for_user(username: str) -> list[sqlite3.Row]:
    return query_all(
        """
        SELECT s.* FROM sites s
        JOIN users u ON u.id = s.owner_id
        WHERE u.username = ?
        ORDER BY s.created_at DESC
        """,
        (username,),
    )