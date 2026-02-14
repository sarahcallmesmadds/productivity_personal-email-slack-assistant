from __future__ import annotations

import json
import logging
import sqlite3

from assistant.config import Config
from assistant.drafts.generator import DraftGenerator
from assistant.drafts.store import DraftStore
from assistant.email.classifier import EmailClassifier
from assistant.email.gmail_client import GmailClient
from assistant.models import DraftSource, EmailAction
from assistant.notifications.notifier import SlackNotifier

logger = logging.getLogger(__name__)


class EmailScanner:
    """Polls Gmail for unread emails, classifies them, drafts responses, and notifies via Slack."""

    def __init__(
        self,
        config: Config,
        gmail_client: GmailClient,
        classifier: EmailClassifier,
        draft_generator: DraftGenerator,
        draft_store: DraftStore,
        notifier: SlackNotifier,
        db: sqlite3.Connection,
    ):
        self.config = config
        self.gmail = gmail_client
        self.classifier = classifier
        self.generator = draft_generator
        self.drafts = draft_store
        self.notifier = notifier
        self.db = db

    def scan(self):
        """Run one scan cycle: fetch new emails, classify, draft, notify."""
        logger.info("Starting email scan...")

        try:
            # Try incremental sync first
            history_id = self._get_stored_history_id()
            if history_id:
                emails = self.gmail.get_new_messages_since(history_id)
            else:
                emails = self.gmail.get_unread_messages(max_results=20)

            # Update stored history ID
            new_history_id = self.gmail.get_history_id()
            self._store_history_id(new_history_id)

            if not emails:
                logger.info("No new emails")
                return

            logger.info("Found %d new emails", len(emails))

            for email in emails:
                # Skip if already processed
                if self.drafts.is_processed(email.message_id, "email"):
                    continue

                try:
                    self._process_email(email)
                except Exception:
                    logger.exception("Failed to process email %s", email.message_id)

        except Exception:
            logger.exception("Email scan failed")

    def _process_email(self, email):
        """Process a single email: classify, draft if needed, notify."""
        classification = self.classifier.classify(email)

        # Mark as processed
        self.drafts.mark_processed(
            email.message_id, "email", classification.model_dump_json()
        )

        logger.info(
            "Email from %s: category=%s priority=%s action=%s",
            email.from_email,
            classification.category.value,
            classification.priority.value,
            classification.action.value,
        )

        if classification.action == EmailAction.DRAFT_RESPONSE:
            # Get thread context for better drafting
            thread_context = None
            if email.is_reply:
                try:
                    thread_msgs = self.gmail.get_thread(email.thread_id)
                    if len(thread_msgs) > 1:
                        # Summarize earlier messages (excluding the current one)
                        earlier = [
                            f"From: {m.from_email}\n{m.body_snippet[:500]}"
                            for m in thread_msgs[:-1]
                        ]
                        thread_context = "\n---\n".join(earlier[-3:])  # Last 3 messages
                except Exception:
                    logger.exception("Failed to fetch thread context")

            # Generate draft
            draft_text = self.generator.generate_email_draft(
                email, classification, thread_context
            )

            # Store draft
            draft = self.drafts.create(
                source=DraftSource.EMAIL,
                original_from=email.from_email,
                original_body=email.body_snippet,
                original_message_id=email.message_id,
                draft_text=draft_text,
                original_subject=email.subject,
                original_thread_id=email.thread_id,
                category=classification.category.value,
                priority=classification.priority.value,
                summary=classification.summary,
                draft_subject=email.subject,
            )

            # Notify via Slack DM
            ts, channel = self.notifier.send_email_draft_notification(
                draft, email, classification
            )
            self.drafts.update_slack_notification(draft.id, ts, channel)

        elif classification.action == EmailAction.FYI_ONLY:
            self.notifier.send_fyi_notification(email, classification)

        elif classification.action == EmailAction.ARCHIVE:
            try:
                self.gmail.archive(email.message_id)
                logger.info("Auto-archived %s", email.subject)
            except Exception:
                logger.exception("Failed to auto-archive %s", email.message_id)

        # SKIP action: do nothing

    def _get_stored_history_id(self) -> str | None:
        row = self.db.execute(
            "SELECT value FROM scan_state WHERE key = 'gmail_history_id'"
        ).fetchone()
        return row["value"] if row else None

    def _store_history_id(self, history_id: str):
        self.db.execute(
            "INSERT OR REPLACE INTO scan_state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            ("gmail_history_id", history_id),
        )
        self.db.commit()
