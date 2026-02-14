from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)


class VoiceFeedbackProcessor:
    """Processes feedback from draft edits and text responses to improve voice."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def record_edit_diff(self, draft_id: str, original_draft: str, edited_text: str):
        """Record the diff between what the agent drafted and what the user actually sent."""
        if original_draft.strip() == edited_text.strip():
            return  # No change

        diff_content = (
            f"ORIGINAL DRAFT:\n{original_draft}\n\n"
            f"USER EDITED TO:\n{edited_text}"
        )
        self.db.execute(
            "INSERT INTO voice_feedback (draft_id, feedback_type, feedback_content, created_at) VALUES (?, ?, ?, ?)",
            (draft_id, "edit_diff", diff_content, datetime.utcnow().isoformat()),
        )
        self.db.commit()
        logger.info("Recorded edit diff for draft %s", draft_id)

    def record_text_feedback(self, draft_id: str | None, feedback: str):
        """Record text feedback like 'too formal' or 'perfect'."""
        self.db.execute(
            "INSERT INTO voice_feedback (draft_id, feedback_type, feedback_content, created_at) VALUES (?, ?, ?, ?)",
            (draft_id, "text_feedback", feedback, datetime.utcnow().isoformat()),
        )
        self.db.commit()
        logger.info("Recorded text feedback: %s", feedback[:50])

    def get_feedback_summary(self, limit: int = 20) -> str:
        """Get a summary of recent feedback for inclusion in draft prompts."""
        rows = self.db.execute(
            "SELECT feedback_type, feedback_content FROM voice_feedback ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

        if not rows:
            return ""

        lines = []
        for row in rows:
            if row["feedback_type"] == "text_feedback":
                lines.append(f"- User feedback: {row['feedback_content']}")
            elif row["feedback_type"] == "edit_diff":
                lines.append(f"- User edited a draft:\n{row['feedback_content'][:500]}")

        return "\n".join(lines)
