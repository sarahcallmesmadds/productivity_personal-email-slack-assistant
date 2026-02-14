from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime

from assistant.models import Draft, DraftSource, DraftStatus

logger = logging.getLogger(__name__)


class DraftStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def create(
        self,
        source: DraftSource,
        original_from: str,
        original_body: str,
        original_message_id: str,
        draft_text: str,
        original_subject: str | None = None,
        original_thread_id: str | None = None,
        original_channel_id: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        summary: str | None = None,
        draft_subject: str | None = None,
    ) -> Draft:
        """Create a new draft and return it."""
        draft_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        self.db.execute(
            """INSERT INTO drafts
               (id, source, status, created_at, original_from, original_subject,
                original_body, original_message_id, original_thread_id, original_channel_id,
                category, priority, summary, draft_text, draft_subject)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                draft_id, source.value, DraftStatus.PENDING_REVIEW.value, now,
                original_from, original_subject, original_body, original_message_id,
                original_thread_id, original_channel_id, category, priority,
                summary, draft_text, draft_subject,
            ),
        )
        self.db.commit()
        logger.info("Created draft %s for %s from %s", draft_id, source.value, original_from)

        return self.get(draft_id)

    def get(self, draft_id: str) -> Draft | None:
        """Get a draft by ID."""
        row = self.db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if not row:
            return None
        return self._row_to_draft(row)

    def update_status(self, draft_id: str, status: DraftStatus):
        """Update a draft's status."""
        now = datetime.utcnow().isoformat()
        updates = {"status": status.value}
        if status == DraftStatus.APPROVED:
            updates["approved_at"] = now
        elif status == DraftStatus.REJECTED:
            updates["rejected_at"] = now
        elif status == DraftStatus.SENT:
            updates["sent_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [draft_id]
        self.db.execute(f"UPDATE drafts SET {set_clause} WHERE id = ?", values)
        self.db.commit()
        logger.info("Draft %s status -> %s", draft_id, status.value)

    def update_slack_notification(self, draft_id: str, ts: str, channel: str):
        """Store the Slack notification message timestamp for later updates."""
        self.db.execute(
            "UPDATE drafts SET slack_notification_ts = ?, slack_notification_channel = ? WHERE id = ?",
            (ts, channel, draft_id),
        )
        self.db.commit()

    def update_edited_text(self, draft_id: str, edited_text: str):
        """Store user-edited draft text."""
        self.db.execute(
            "UPDATE drafts SET edited_text = ? WHERE id = ?",
            (edited_text, draft_id),
        )
        self.db.commit()
        logger.info("Draft %s edited by user", draft_id)

    def get_final_text(self, draft: Draft) -> str:
        """Get the final text to send (edited if available, otherwise original draft)."""
        return draft.edited_text or draft.draft_text

    def is_processed(self, message_id: str, source: str) -> bool:
        """Check if a message has already been processed."""
        row = self.db.execute(
            "SELECT 1 FROM processed_messages WHERE message_id = ? AND source = ?",
            (message_id, source),
        ).fetchone()
        return row is not None

    def mark_processed(self, message_id: str, source: str, classification_json: str | None = None):
        """Mark a message as processed."""
        self.db.execute(
            "INSERT OR IGNORE INTO processed_messages (message_id, source, processed_at, classification_json) VALUES (?, ?, ?, ?)",
            (message_id, source, datetime.utcnow().isoformat(), classification_json),
        )
        self.db.commit()

    def _row_to_draft(self, row: sqlite3.Row) -> Draft:
        return Draft(
            id=row["id"],
            source=DraftSource(row["source"]),
            status=DraftStatus(row["status"]),
            created_at=row["created_at"],
            original_from=row["original_from"],
            original_subject=row["original_subject"],
            original_body=row["original_body"],
            original_message_id=row["original_message_id"],
            original_thread_id=row["original_thread_id"],
            original_channel_id=row["original_channel_id"],
            category=row["category"],
            priority=row["priority"],
            summary=row["summary"],
            draft_text=row["draft_text"],
            draft_subject=row["draft_subject"],
            slack_notification_ts=row["slack_notification_ts"],
            slack_notification_channel=row["slack_notification_channel"],
            edited_text=row["edited_text"],
        )
