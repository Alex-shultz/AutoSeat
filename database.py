"""
database.py
===========
Database connection management and schema initialisation.
"""

import os
import sqlite3

from flask import g

DB_PATH = os.path.join(os.path.dirname(__file__), "seating.db")


def get_db():
    """Return (and cache) the per-request SQLite connection."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exc=None):
    """Tear-down callback: close the DB connection at end of request."""
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    """Create all tables if they do not already exist."""
    db = sqlite3.connect(DB_PATH)

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    UNIQUE NOT NULL,
            email      TEXT    UNIQUE NOT NULL,
            password   TEXT    NOT NULL,
            role       TEXT    NOT NULL DEFAULT 'planner',
            created_at TEXT    NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT    NOT NULL,
            created_at TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS venues (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            venue_type  TEXT    NOT NULL DEFAULT 'classroom',
            rows        INTEGER NOT NULL,
            cols        INTEGER NOT NULL,
            layout_json TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            name            TEXT    NOT NULL,
            group_name      TEXT    NOT NULL DEFAULT '',
            needs_front_row INTEGER NOT NULL DEFAULT 0,
            needs_aisle     INTEGER NOT NULL DEFAULT 0,
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS arrangements (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER NOT NULL,
            venue_id          INTEGER,
            name              TEXT    NOT NULL,
            status            TEXT    NOT NULL DEFAULT 'unsolved',
            participants_json TEXT    NOT NULL DEFAULT '[]',
            constraints_json  TEXT    NOT NULL DEFAULT '[]',
            result_json       TEXT,
            created_at        TEXT    NOT NULL,
            updated_at        TEXT    NOT NULL,
            FOREIGN KEY(user_id)  REFERENCES users(id),
            FOREIGN KEY(venue_id) REFERENCES venues(id) ON DELETE SET NULL
        )
    """)

    db.commit()
    db.close()
