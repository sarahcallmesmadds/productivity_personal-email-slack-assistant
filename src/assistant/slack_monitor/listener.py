from __future__ import annotations

import logging
import sqlite3
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from assistant.config import Config
from assistant.drafts.generator import DraftGenerator
from assistant.drafts.store import DraftStore
from assistant.email.gmail_client import GmailClient
from assistant.models import DraftSource, DraftStatus, SlackMessage
from assistant.notifications.notifier import SlackNotifier
from assistant.slack_monitor.classifier import SlackClassifier
from assistant.voice.feedback import VoiceFeedbackProcessor

logger = logging.getLogger(__name__)


class SlackMonitor:
    """Slack Bolt app that monitors channels/DMs and handles interactive approval flows."""

    def __init__(
        self,
        config: Config,
        draft_store: DraftStore,
        draft_generator: DraftGenerator,
        notifier: SlackNotifier,
        gmail_client: GmailClient,
        feedback_processor: VoiceFeedbackProcessor,
        db: sqlite3.Connection,
    ):
        self.config = config
        self.drafts = draft_store
        self.generator = draft_generator
        self.notifier = notifier
        self.gmail = gmail_client
        self.feedback = feedback_processor
        self.classifier = SlackClassifier(config)
        self.db = db
        self.monitored_channels = set(config.slack_channel_ids)

        # Build the Slack Bolt app
        self.app = App(token=config.slack_bot_token)
        self._register_handlers()

    def start(self):
        """Start the Slack Bolt app in Socket Mode (blocking — run in a thread)."""
        handler = SocketModeHandler(self.app, self.config.slack_app_token)
        logger.info("Slack monitor starting in Socket Mode...")
        handler.start()

    def start_in_thread(self) -> threading.Thread:
        """Start the Slack monitor in a background daemon thread."""
        thread = threading.Thread(target=self.start, daemon=True, name="slack-monitor")
        thread.start()
        logger.info("Slack monitor thread started")
        return thread

    def _register_handlers(self):
        """Register all Slack event and action handlers."""

        # --- Message events (channel monitoring) ---
        @self.app.event("message")
        def handle_message(event, client: WebClient):
            self._handle_message_event(event, client)

        # --- Interactive actions (draft approval flow) ---
        @self.app.action("approve_draft")
        def handle_approve(ack, body, client):
            ack()
            self._handle_approve(body, client)

        @self.app.action("edit_draft")
        def handle_edit(ack, body, client):
            ack()
            self._handle_edit(body, client)

        @self.app.action("reject_draft")
        def handle_reject(ack, body, client):
            ack()
            self._handle_reject(body, client)

        @self.app.action("skip_draft")
        def handle_skip(ack, body, client):
            ack()
            self._handle_skip(body, client)

        # --- Modal submission (edited draft) ---
        @self.app.view("edit_draft_submit")
        def handle_edit_submit(ack, body, client, view):
            ack()
            self._handle_edit_submit(body, client, view)

    # -------------------------------------------------------------------------
    # Message monitoring
    # -------------------------------------------------------------------------

    def _handle_message_event(self, event: dict, client: WebClient):
        """Handle incoming Slack messages — classify and draft if needed."""
        # Skip bot messages and own messages
        if event.get("bot_id") or event.get("subtype"):
            return
        if event.get("user") == self.config.slack_user_id:
            return

        channel_id = event.get("channel", "")

        # Only process messages from monitored channels or DMs to the user
        channel_type = event.get("channel_type", "")
        is_dm = channel_type == "im"
        is_monitored = channel_id in self.monitored_channels

        if not is_dm and not is_monitored:
            return

        # Check for @mention of the user
        text = event.get("text", "")
        has_mention = f"<@{self.config.slack_user_id}>" in text

        # For monitored channels without a direct mention, still classify
        # but the classifier will decide if Sarah needs to respond
        message_ts = event.get("ts", "")
        thread_ts = event.get("thread_ts")

        # Skip already processed
        if self.drafts.is_processed(message_ts, "slack"):
            return

        # Get user info for context
        user_name = None
        try:
            user_info = client.users_info(user=event.get("user", ""))
            user_name = user_info["user"].get("real_name") or user_info["user"].get("name")
        except Exception:
            pass

        # Get channel name
        channel_name = None
        if not is_dm:
            try:
                channel_info = client.conversations_info(channel=channel_id)
                channel_name = channel_info["channel"].get("name")
            except Exception:
                pass

        message = SlackMessage(
            ts=message_ts,
            thread_ts=thread_ts,
            channel_id=channel_id,
            channel_name=channel_name or ("DM" if is_dm else channel_id),
            user_id=event.get("user", ""),
            user_name=user_name,
            text=text,
            is_thread_reply=bool(thread_ts),
        )

        # Get thread context if this is a thread reply
        thread_context = None
        if thread_ts:
            try:
                result = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=10)
                thread_msgs = result.get("messages", [])
                # Exclude the current message
                earlier = [
                    f"{m.get('user', 'unknown')}: {m.get('text', '')[:300]}"
                    for m in thread_msgs
                    if m.get("ts") != message_ts
                ]
                if earlier:
                    thread_context = "\n".join(earlier[-5:])
            except Exception:
                pass

        # Classify
        classification = self.classifier.classify(message, thread_context)

        # Mark as processed
        self.drafts.mark_processed(message_ts, "slack", classification.model_dump_json())

        if not classification.needs_response:
            logger.debug("Slack message in %s doesn't need response: %s", channel_name, classification.reason)
            return

        logger.info(
            "Slack message needs response: channel=%s from=%s urgency=%s",
            channel_name, user_name, classification.urgency,
        )

        # Generate draft
        draft_text = self.generator.generate_slack_draft(
            message, classification, thread_context
        )

        # Post ephemeral draft in-thread
        reply_thread_ts = thread_ts or message_ts
        self.notifier.send_ephemeral_draft(channel_id, reply_thread_ts, draft_text)

        # Also store the draft for reference
        self.drafts.create(
            source=DraftSource.SLACK,
            original_from=user_name or event.get("user", "unknown"),
            original_body=text,
            original_message_id=message_ts,
            draft_text=draft_text,
            original_subject=channel_name,
            original_thread_id=reply_thread_ts,
            original_channel_id=channel_id,
            category=None,
            priority=classification.urgency,
            summary=classification.summary,
        )

    # -------------------------------------------------------------------------
    # Interactive handlers (email draft approval flow)
    # -------------------------------------------------------------------------

    def _handle_approve(self, body: dict, client: WebClient):
        """Handle 'Send' button click — send the email and update notification."""
        draft_id = body["actions"][0]["value"]
        draft = self.drafts.get(draft_id)
        if not draft:
            logger.error("Draft %s not found", draft_id)
            return

        final_text = self.drafts.get_final_text(draft)

        if draft.source == DraftSource.EMAIL:
            # Send via Gmail
            try:
                self.gmail.send_reply(
                    thread_id=draft.original_thread_id,
                    to=draft.original_from,
                    body=final_text,
                    subject=draft.draft_subject,
                )
                # Archive the original
                self.gmail.archive(draft.original_message_id)
            except Exception:
                logger.exception("Failed to send email for draft %s", draft_id)
                return

        self.drafts.update_status(draft_id, DraftStatus.SENT)

        # Check if user edited — record for voice learning
        if draft.edited_text:
            self.feedback.record_edit_diff(draft_id, draft.draft_text, draft.edited_text)

        # Update the Slack notification
        draft = self.drafts.get(draft_id)  # Refresh
        if draft.slack_notification_ts and draft.slack_notification_channel:
            self.notifier.update_draft_status(
                draft.slack_notification_channel, draft.slack_notification_ts, "Sent", draft
            )

        logger.info("Draft %s approved and sent", draft_id)

    def _handle_edit(self, body: dict, client: WebClient):
        """Handle 'Edit' button click — open a modal with the draft text."""
        draft_id = body["actions"][0]["value"]
        draft = self.drafts.get(draft_id)
        if not draft:
            return

        current_text = draft.edited_text or draft.draft_text

        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "edit_draft_submit",
                "private_metadata": draft_id,
                "title": {"type": "plain_text", "text": "Edit Draft"},
                "submit": {"type": "plain_text", "text": "Save"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "draft_input",
                        "label": {"type": "plain_text", "text": "Draft Response"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "draft_text",
                            "multiline": True,
                            "initial_value": current_text,
                        },
                    }
                ],
            },
        )

    def _handle_reject(self, body: dict, client: WebClient):
        """Handle 'Reject' button click."""
        draft_id = body["actions"][0]["value"]
        self.drafts.update_status(draft_id, DraftStatus.REJECTED)

        draft = self.drafts.get(draft_id)
        if draft and draft.slack_notification_ts and draft.slack_notification_channel:
            self.notifier.update_draft_status(
                draft.slack_notification_channel, draft.slack_notification_ts, "Rejected", draft
            )
        logger.info("Draft %s rejected", draft_id)

    def _handle_skip(self, body: dict, client: WebClient):
        """Handle 'Skip' button click."""
        draft_id = body["actions"][0]["value"]
        self.drafts.update_status(draft_id, DraftStatus.SKIPPED)

        draft = self.drafts.get(draft_id)
        if draft and draft.slack_notification_ts and draft.slack_notification_channel:
            self.notifier.update_draft_status(
                draft.slack_notification_channel, draft.slack_notification_ts, "Skipped", draft
            )
        logger.info("Draft %s skipped", draft_id)

    def _handle_edit_submit(self, body: dict, client: WebClient, view: dict):
        """Handle edited draft submission from modal."""
        draft_id = view["private_metadata"]
        edited_text = view["state"]["values"]["draft_input"]["draft_text"]["value"]

        self.drafts.update_edited_text(draft_id, edited_text)

        draft = self.drafts.get(draft_id)
        if not draft:
            return

        # Re-send the notification with updated text and buttons
        # We need to update the existing message to show the edited draft
        if draft.slack_notification_ts and draft.slack_notification_channel:
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Re: {draft.original_subject}*\n"
                            f"From: {draft.original_from}\n"
                            f"_{draft.summary}_"
                        ),
                    },
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "*Edited Draft*"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": edited_text[:2000]},
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
                    ],
                },
            ]

            try:
                client.chat_update(
                    channel=draft.slack_notification_channel,
                    ts=draft.slack_notification_ts,
                    text=f"Edited draft: {draft.original_subject}",
                    blocks=blocks,
                )
            except Exception:
                logger.exception("Failed to update edited draft notification")

        logger.info("Draft %s edited by user", draft_id)
