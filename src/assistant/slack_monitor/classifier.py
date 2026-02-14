from __future__ import annotations

import json
import logging

import anthropic

from assistant.config import Config
from assistant.models import SlackClassification, SlackMessage

logger = logging.getLogger(__name__)

SLACK_CLASSIFY_SYSTEM_PROMPT = """You are a Slack monitoring assistant for Sarah Madden (Head of Investor Partnerships at Profound).

Analyze this Slack message and determine if Sarah needs to respond.

Context about Sarah's role:
- Manages investor/VC/PE relationships and their platform teams
- Handles partnership discussions, portfolio company requests, event coordination
- Reports to CEO, works with CRO Jack Gallo, cross-functional with sales, marketing, product
- Her Slack user ID is {user_id}

A message needs Sarah's response if:
1. Someone directly @mentions Sarah or addresses her by name
2. Someone asks about partnerships, investor relations, or intros that Sarah owns
3. An action item is assigned to Sarah
4. A question in a partnership/investor channel goes unanswered
5. Her manager or C-suite asks something in her domain

A message does NOT need response if:
1. Sarah already replied in the thread
2. Someone else adequately answered
3. It's general chatter or announcements with no ask
4. It's from a bot
5. It's in a channel Sarah monitors but the topic isn't her domain
6. Sarah sent the message herself

Return valid JSON only:
{{"needs_response": true/false, "reason": "why", "urgency": "high/medium/low", "summary": "1 sentence", "draft_guidance": "what to say" or null}}"""


class SlackClassifier:
    def __init__(self, config: Config):
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.model = config.model
        self.user_id = config.slack_user_id

    def classify(self, message: SlackMessage, thread_context: str | None = None) -> SlackClassification:
        """Classify whether a Slack message needs Sarah's response."""
        system = SLACK_CLASSIFY_SYSTEM_PROMPT.format(user_id=self.user_id)

        user_content = (
            f"Channel: {message.channel_name or message.channel_id}\n"
            f"From: {message.user_name or message.user_id}\n"
            f"Message: {message.text}\n"
            f"Is thread reply: {message.is_thread_reply}\n"
        )
        if thread_context:
            user_content += f"\nThread context:\n{thread_context}\n"

        response = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )

        response_text = response.content[0].text.strip()
        try:
            data = json.loads(response_text)
            return SlackClassification(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.error("Failed to parse Slack classification: %s", e)
            return SlackClassification(
                needs_response=False,
                reason="Classification failed",
                urgency="low",
                summary="Could not classify message",
            )
