from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# --- Email classification ---


class EmailCategory(str, Enum):
    INVESTOR_INTRO = "investor_intro"
    PORTFOLIO_REQUEST = "portfolio_request"
    PARTNERSHIP_FOLLOWUP = "partnership_followup"
    EVENT_INVITATION = "event_invitation"
    DEAL_FLOW = "deal_flow"
    INTERNAL_ACTION = "internal_action"
    INTERNAL_FYI = "internal_fyi"
    SCHEDULING = "scheduling"
    FOLLOW_UP_NEEDED = "follow_up_needed"
    NEWSLETTER = "newsletter"
    MARKETING = "marketing"
    AUTOMATED = "automated"


class EmailPriority(str, Enum):
    URGENT = "urgent"
    HIGH = "high"
    STANDARD = "standard"


class EmailAction(str, Enum):
    DRAFT_RESPONSE = "draft_response"
    FYI_ONLY = "fyi_only"
    SKIP = "skip"
    ARCHIVE = "archive"


class EmailClassification(BaseModel):
    category: EmailCategory
    priority: EmailPriority
    action: EmailAction
    summary: str
    draft_guidance: str | None = None


class EmailMessage(BaseModel):
    message_id: str
    thread_id: str
    from_email: str
    from_name: str | None = None
    to: list[str] = []
    cc: list[str] = []
    subject: str
    body_snippet: str
    body_full: str | None = None
    date: datetime
    labels: list[str] = []
    is_reply: bool = False


# --- Slack classification ---


class SlackClassification(BaseModel):
    needs_response: bool
    reason: str
    urgency: str  # high, medium, low
    summary: str
    draft_guidance: str | None = None


class SlackMessage(BaseModel):
    ts: str
    thread_ts: str | None = None
    channel_id: str
    channel_name: str | None = None
    user_id: str
    user_name: str | None = None
    text: str
    is_thread_reply: bool = False


# --- Drafts ---


class DraftStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    SKIPPED = "skipped"
    EXPIRED = "expired"


class DraftSource(str, Enum):
    EMAIL = "email"
    SLACK = "slack"


class Draft(BaseModel):
    id: str = Field(description="UUID")
    source: DraftSource
    status: DraftStatus = DraftStatus.PENDING_REVIEW
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Original message context
    original_from: str
    original_subject: str | None = None
    original_body: str
    original_message_id: str
    original_thread_id: str | None = None
    original_channel_id: str | None = None

    # Classification
    category: str | None = None
    priority: str | None = None
    summary: str | None = None

    # Draft content
    draft_text: str
    draft_subject: str | None = None

    # Approval tracking
    slack_notification_ts: str | None = None
    slack_notification_channel: str | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    sent_at: datetime | None = None
    edited_text: str | None = None


# --- LinkedIn ---


class LinkedInDraftRequest(BaseModel):
    sender_name: str
    sender_headline: str | None = None
    message_text: str
    conversation_context: list[str] = []
    conversation_id: str


class LinkedInDraftResponse(BaseModel):
    draft_text: str
    needs_response: bool
    urgency: str
    summary: str
