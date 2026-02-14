from __future__ import annotations

import json
import logging

import anthropic

from assistant.config import Config
from assistant.models import EmailClassification, EmailMessage

logger = logging.getLogger(__name__)

CLASSIFY_SYSTEM_PROMPT = """You are an email triage assistant for Sarah Madden, Head of Investor Partnerships at Profound (AI visibility platform, Series C, ~$20-25M ARR).

Sarah manages relationships with VC/PE firms and their platform teams. She gets emails from:
- Investors (partners, associates, platform team leads at firms like Sequoia, Kleiner Perkins, Khosla, Lightspeed)
- Portfolio companies (founders, operators asking for intros or platform help)
- Internal Profound team (CEO, CRO Jack Gallo, sales, marketing, product)
- Event organizers (conferences, dinners, LP meetings)
- Vendors and marketers (ignore unless relevant to partnerships)

Classify each email with:
1. category: one of [investor_intro, portfolio_request, partnership_followup, event_invitation, deal_flow, internal_action, internal_fyi, scheduling, follow_up_needed, newsletter, marketing, automated]
2. priority: one of [urgent, high, standard]
3. action: one of [draft_response, fyi_only, skip, archive]
4. summary: 1-sentence plain English summary
5. draft_guidance: if action=draft_response, brief notes on what the response should cover

Priority rules:
- URGENT: Direct asks from known investors, C-suite, or follow-ups where someone is waiting on Sarah
- HIGH: Partnership discussions, portfolio company requests, deal flow, event invites from tier 1 partners
- STANDARD: General scheduling, event invites, intros from unknown sources

All actionable emails get a response regardless of priority.

Action rules:
- draft_response: Emails that clearly need a reply from Sarah
- fyi_only: Emails Sarah should know about but don't need her reply (internal FYIs, CC'd threads where someone else is handling it)
- skip: Newsletters, marketing emails, automated notifications she doesn't need to see
- archive: System notifications (Salesforce, Notion, calendar confirmations, receipts)

Return valid JSON only. No markdown, no code blocks."""


class EmailClassifier:
    def __init__(self, config: Config):
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.model = config.model

    def classify(self, email: EmailMessage) -> EmailClassification:
        """Classify a single email."""
        email_text = self._format_email(email)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            system=CLASSIFY_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"Classify this email:\n\n{email_text}"}
            ],
        )

        response_text = response.content[0].text.strip()
        try:
            data = json.loads(response_text)
            return EmailClassification(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.error("Failed to parse classification: %s\nResponse: %s", e, response_text[:200])
            # Default to FYI so nothing gets lost
            return EmailClassification(
                category="internal_fyi",
                priority="standard",
                action="fyi_only",
                summary=f"Could not classify: {email.subject}",
            )

    def classify_batch(self, emails: list[EmailMessage]) -> list[EmailClassification]:
        """Classify multiple emails. Processes individually to avoid confusion."""
        results = []
        for email in emails:
            try:
                result = self.classify(email)
                results.append(result)
            except Exception:
                logger.exception("Failed to classify email %s", email.message_id)
                results.append(
                    EmailClassification(
                        category="internal_fyi",
                        priority="standard",
                        action="fyi_only",
                        summary=f"Classification failed: {email.subject}",
                    )
                )
        return results

    def _format_email(self, email: EmailMessage) -> str:
        parts = [
            f"From: {email.from_name or ''} <{email.from_email}>",
            f"To: {', '.join(email.to[:5])}",
        ]
        if email.cc:
            parts.append(f"CC: {', '.join(email.cc[:5])}")
        parts.append(f"Subject: {email.subject}")
        parts.append(f"Date: {email.date.strftime('%Y-%m-%d %H:%M')}")
        parts.append(f"Is Reply: {email.is_reply}")
        parts.append(f"\n{email.body_snippet}")
        return "\n".join(parts)
