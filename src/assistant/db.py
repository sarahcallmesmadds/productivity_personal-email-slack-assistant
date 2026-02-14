from __future__ import annotations

import os
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    original_from TEXT,
    original_subject TEXT,
    original_body TEXT,
    original_message_id TEXT,
    original_thread_id TEXT,
    original_channel_id TEXT,

    category TEXT,
    priority TEXT,
    summary TEXT,

    draft_text TEXT NOT NULL,
    draft_subject TEXT,

    slack_notification_ts TEXT,
    slack_notification_channel TEXT,
    approved_at TIMESTAMP,
    rejected_at TIMESTAMP,
    sent_at TIMESTAMP,
    edited_text TEXT
);

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    classification_json TEXT
);

CREATE TABLE IF NOT EXISTS scan_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voice_profile (
    id INTEGER PRIMARY KEY,
    profile_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    email_count_analyzed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS voice_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT,
    feedback_type TEXT,
    feedback_content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voice_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT UNIQUE,
    recipient_type TEXT,
    recipient_domain TEXT,
    subject TEXT,
    sent_text TEXT,
    tone_tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    conn = get_db(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
