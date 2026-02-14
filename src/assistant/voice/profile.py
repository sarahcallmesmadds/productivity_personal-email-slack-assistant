from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)


class VoiceProfileManager:
    """Manages the voice profile in SQLite — load, save, update."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get_profile(self) -> dict | None:
        """Get the current voice profile as a dict."""
        row = self.db.execute(
            "SELECT profile_json FROM voice_profile ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row and row["profile_json"]:
            return json.loads(row["profile_json"])
        return None

    def save_profile(self, profile: dict, email_count: int):
        """Save or update the voice profile."""
        self.db.execute(
            """INSERT OR REPLACE INTO voice_profile (id, profile_json, updated_at, email_count_analyzed)
               VALUES (1, ?, ?, ?)""",
            (json.dumps(profile), datetime.utcnow().isoformat(), email_count),
        )
        self.db.commit()
        logger.info("Voice profile saved (%d emails analyzed)", email_count)

    def get_examples(self, recipient_type: str | None = None, limit: int = 5) -> list[dict]:
        """Get voice examples, optionally filtered by recipient type."""
        if recipient_type:
            rows = self.db.execute(
                "SELECT * FROM voice_examples WHERE recipient_type = ? ORDER BY created_at DESC LIMIT ?",
                (recipient_type, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM voice_examples ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_example(
        self,
        email_id: str,
        recipient_type: str,
        recipient_domain: str,
        subject: str,
        sent_text: str,
        tone_tags: list[str],
    ):
        """Save a voice example from a sent email."""
        self.db.execute(
            """INSERT OR IGNORE INTO voice_examples
               (email_id, recipient_type, recipient_domain, subject, sent_text, tone_tags, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                email_id,
                recipient_type,
                recipient_domain,
                subject,
                sent_text,
                json.dumps(tone_tags),
                datetime.utcnow().isoformat(),
            ),
        )
        self.db.commit()

    def get_recent_feedback(self, limit: int = 20) -> list[dict]:
        """Get recent voice feedback entries."""
        rows = self.db.execute(
            "SELECT * FROM voice_feedback ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_email_count_analyzed(self) -> int:
        """How many emails have been analyzed for the voice profile."""
        row = self.db.execute(
            "SELECT email_count_analyzed FROM voice_profile WHERE id = 1"
        ).fetchone()
        return row["email_count_analyzed"] if row else 0
