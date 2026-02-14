from __future__ import annotations

import base64
import json
import logging
import sqlite3
from datetime import datetime
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from assistant.config import Config
from assistant.models import EmailMessage

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailClient:
    def __init__(self, config: Config, db: sqlite3.Connection):
        token_info = json.loads(config.gmail_token_json)
        self.creds = Credentials.from_authorized_user_info(token_info, SCOPES)
        self.user_email = config.gmail_user_email
        self.db = db
        self._ensure_creds()
        self.service = build("gmail", "v1", credentials=self.creds)

    def _ensure_creds(self):
        if self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
            # Persist refreshed token in scan_state
            self.db.execute(
                "INSERT OR REPLACE INTO scan_state (key, value, updated_at) VALUES (?, ?, ?)",
                ("gmail_token_json", self.creds.to_json(), datetime.utcnow().isoformat()),
            )
            self.db.commit()
            logger.info("Gmail token refreshed and saved")

    def get_unread_messages(self, max_results: int = 20) -> list[EmailMessage]:
        """Fetch unread inbox messages."""
        self._ensure_creds()
        results = (
            self.service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], q="is:unread", maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])
        if not messages:
            return []

        parsed = []
        for msg_stub in messages:
            msg = self._get_message(msg_stub["id"])
            if msg:
                parsed.append(msg)
        return parsed

    def get_sent_emails(self, max_results: int = 100) -> list[EmailMessage]:
        """Fetch sent emails for voice analysis."""
        self._ensure_creds()
        results = (
            self.service.users()
            .messages()
            .list(userId="me", labelIds=["SENT"], maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])
        if not messages:
            return []

        parsed = []
        for msg_stub in messages:
            msg = self._get_message(msg_stub["id"])
            if msg:
                parsed.append(msg)
        return parsed

    def get_thread(self, thread_id: str) -> list[EmailMessage]:
        """Get full thread for context when drafting a reply."""
        self._ensure_creds()
        thread = (
            self.service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
        parsed = []
        for msg_data in thread.get("messages", []):
            msg = self._parse_message(msg_data)
            if msg:
                parsed.append(msg)
        return parsed

    def send_reply(
        self,
        thread_id: str,
        to: str,
        body: str,
        subject: str | None = None,
        message_id_header: str | None = None,
    ) -> str:
        """Send a reply in an existing thread. Returns the sent message ID."""
        self._ensure_creds()
        message = MIMEText(body)
        message["to"] = to
        message["from"] = self.user_email
        if subject:
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            message["subject"] = subject
        if message_id_header:
            message["In-Reply-To"] = message_id_header
            message["References"] = message_id_header

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = (
            self.service.users()
            .messages()
            .send(userId="me", body={"raw": raw, "threadId": thread_id})
            .execute()
        )
        logger.info("Sent reply in thread %s, message id %s", thread_id, sent["id"])
        return sent["id"]

    def archive(self, message_id: str):
        """Remove INBOX label (archive, never delete)."""
        self._ensure_creds()
        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["INBOX"]},
        ).execute()
        logger.info("Archived message %s", message_id)

    def get_history_id(self) -> str:
        """Get current historyId for incremental sync."""
        self._ensure_creds()
        profile = self.service.users().getProfile(userId="me").execute()
        return profile["historyId"]

    def get_new_messages_since(self, history_id: str, max_results: int = 20) -> list[EmailMessage]:
        """Incremental sync: get messages added since the given historyId."""
        self._ensure_creds()
        try:
            history = (
                self.service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=history_id,
                    historyTypes=["messageAdded"],
                    labelId="INBOX",
                    maxResults=max_results,
                )
                .execute()
            )
        except Exception as e:
            if "404" in str(e) or "historyId" in str(e).lower():
                logger.warning("History ID %s expired, falling back to unread scan", history_id)
                return self.get_unread_messages(max_results)
            raise

        new_message_ids = set()
        for record in history.get("history", []):
            for added in record.get("messagesAdded", []):
                msg = added.get("message", {})
                if "INBOX" in msg.get("labelIds", []):
                    new_message_ids.add(msg["id"])

        if not new_message_ids:
            return []

        parsed = []
        for msg_id in new_message_ids:
            msg = self._get_message(msg_id)
            if msg:
                parsed.append(msg)
        return parsed

    def _get_message(self, message_id: str) -> EmailMessage | None:
        """Fetch a single message by ID."""
        try:
            msg_data = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            return self._parse_message(msg_data)
        except Exception:
            logger.exception("Failed to fetch message %s", message_id)
            return None

    def _parse_message(self, msg_data: dict) -> EmailMessage | None:
        """Parse a Gmail API message response into an EmailMessage."""
        try:
            headers = {h["name"].lower(): h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
            body = self._extract_body(msg_data.get("payload", {}))
            snippet = body[:2000] if body else msg_data.get("snippet", "")

            from_header = headers.get("from", "")
            from_email = from_header
            from_name = None
            if "<" in from_header and ">" in from_header:
                from_name = from_header.split("<")[0].strip().strip('"')
                from_email = from_header.split("<")[1].split(">")[0]

            to_header = headers.get("to", "")
            to_list = [addr.strip() for addr in to_header.split(",") if addr.strip()]
            cc_header = headers.get("cc", "")
            cc_list = [addr.strip() for addr in cc_header.split(",") if cc_header and addr.strip()]

            date_str = headers.get("date", "")
            try:
                from email.utils import parsedate_to_datetime
                date = parsedate_to_datetime(date_str)
            except Exception:
                date = datetime.utcnow()

            labels = msg_data.get("labelIds", [])

            return EmailMessage(
                message_id=msg_data["id"],
                thread_id=msg_data.get("threadId", msg_data["id"]),
                from_email=from_email,
                from_name=from_name,
                to=to_list,
                cc=cc_list,
                subject=headers.get("subject", "(no subject)"),
                body_snippet=snippet,
                body_full=body,
                date=date,
                labels=labels,
                is_reply="Re:" in headers.get("subject", ""),
            )
        except Exception:
            logger.exception("Failed to parse message %s", msg_data.get("id"))
            return None

    def _extract_body(self, payload: dict) -> str:
        """Extract plain text body from Gmail message payload."""
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        # Multipart: look for text/plain first, then text/html
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

        # Nested multipart
        for part in parts:
            if part.get("parts"):
                result = self._extract_body(part)
                if result:
                    return result

        # Fallback to HTML if no plain text
        for part in parts:
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                # Basic HTML stripping — good enough for classification
                import re
                text = re.sub(r"<[^>]+>", " ", html)
                text = re.sub(r"\s+", " ", text).strip()
                return text

        return ""
