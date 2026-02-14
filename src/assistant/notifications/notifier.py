from __future__ import annotations

import logging

from slack_sdk import WebClient

from assistant.config import Config
from assistant.models import Draft, EmailClassification, EmailMessage

logger = logging.getLogger(__name__)

PRIORITY_EMOJI = {
    "urgent": ":rotating_light:",
    "high": ":large_orange_diamond:",
    "standard": ":white_circle:",
}


class SlackNotifier:
    def __init__(self, config: Config):
        self.client = WebClient(token=config.slack_bot_token)
        self.user_id = config.slack_user_id

    def send_email_draft_notification(
        self,
        draft: Draft,
        email: EmailMessage,
        classification: EmailClassification,
    ) -> str:
        """Send a Slack DM with the original email and draft response, with action buttons.
        Returns the message timestamp for later updates."""
        priority_emoji = PRIORITY_EMOJI.get(classification.priority.value, ":white_circle:")
        priority_label = classification.priority.value.upper()

        # Truncate original body for the notification
        original_body = email.body_snippet[:1500]
        draft_text = draft.draft_text[:2000]

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{priority_emoji} EMAIL NEEDS RESPONSE — {priority_label}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*From:* {email.from_name or email.from_email}"},
                    {"type": "mrkdwn", "text": f"*Received:* {email.date.strftime('%I:%M %p')}"},
                    {"type": "mrkdwn", "text": f"*Subject:* {email.subject}"},
                    {"type": "mrkdwn", "text": f"*Category:* {classification.category.value}"},
                ],
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "*Original Message*"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": original_body},
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "*Draft Response*"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": draft_text},
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Send"},
                        "style": "primary",
                        "action_id": "approve_draft",
                        "value": draft.id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit"},
                        "action_id": "edit_draft",
                        "value": draft.id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": "reject_draft",
                        "value": draft.id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Skip"},
                        "action_id": "skip_draft",
                        "value": draft.id,
                    },
                ],
            },
        ]

        response = self.client.chat_postMessage(
            channel=self.user_id,  # DM to user
            text=f"Email draft: {email.subject} from {email.from_email}",
            blocks=blocks,
        )
        ts = response["ts"]
        channel = response["channel"]
        logger.info("Sent draft notification for %s (ts=%s)", draft.id, ts)
        return ts, channel

    def send_fyi_notification(self, email: EmailMessage, classification: EmailClassification):
        """Send a simpler FYI notification (no draft, no buttons)."""
        priority_emoji = PRIORITY_EMOJI.get(classification.priority.value, ":white_circle:")

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{priority_emoji} *FYI — {email.subject}*\n"
                        f"From: {email.from_name or email.from_email}\n"
                        f"{classification.summary}"
                    ),
                },
            },
        ]

        self.client.chat_postMessage(
            channel=self.user_id,
            text=f"FYI: {email.subject} from {email.from_email}",
            blocks=blocks,
        )
        logger.info("Sent FYI notification for %s", email.subject)

    def update_draft_status(self, channel: str, ts: str, status_text: str, draft: Draft):
        """Update an existing draft notification to show its new status."""
        draft_text = draft.edited_text or draft.draft_text

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"~{draft.original_subject}~ — *{status_text}*\n"
                        f"From: {draft.original_from}"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"_{status_text} at {draft.sent_at or draft.rejected_at or 'now'}_"},
                ],
            },
        ]

        try:
            self.client.chat_update(
                channel=channel,
                ts=ts,
                text=f"Draft {status_text.lower()}: {draft.original_subject}",
                blocks=blocks,
            )
        except Exception:
            logger.exception("Failed to update draft notification %s", ts)

    def send_ephemeral_draft(self, channel_id: str, thread_ts: str, draft_text: str):
        """Post an ephemeral draft reply in a Slack thread (only visible to the user)."""
        self.client.chat_postEphemeral(
            channel=channel_id,
            user=self.user_id,
            thread_ts=thread_ts,
            text=f"Draft response (only visible to you):\n\n{draft_text}",
        )
        logger.info("Posted ephemeral draft in channel %s thread %s", channel_id, thread_ts)
