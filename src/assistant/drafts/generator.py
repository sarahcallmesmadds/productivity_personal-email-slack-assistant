from __future__ import annotations

import logging
import sqlite3

import anthropic

from assistant.config import Config
from assistant.models import EmailClassification, EmailMessage, SlackClassification, SlackMessage
from assistant.voice.feedback import VoiceFeedbackProcessor
from assistant.voice.profile import VoiceProfileManager

logger = logging.getLogger(__name__)

DRAFT_SYSTEM_PROMPT = """You are drafting a response on behalf of Sarah Madden, Head of Investor Partnerships at Profound.

Profound is an AI visibility platform (AEO — AI Engine Optimization) that helps companies show up in AI search (ChatGPT, Perplexity, Google AI Overviews, Gemini). Series C, ~$20-25M ARR, 500+ customers including Ramp, Chime, MongoDB, DocuSign.

{voice_profile_section}

{feedback_section}

{examples_section}

Core rules:
- NEVER fabricate data, meetings, or commitments Sarah hasn't made
- NEVER promise availability or schedule meetings (say "let me check my calendar" or similar)
- If you're unsure about context, note it in brackets: [CHECK: is this the Q4 deal?]
- For investor-facing emails, be warm but not sycophantic
- Always end with a clear next step or ask
- Do NOT use quotes around the draft text
- Write the response ready to send — no placeholder text

You will receive the original message, the classification, and any thread context.
Return ONLY the draft response text. No preamble, no explanation."""


class DraftGenerator:
    def __init__(self, config: Config, db: sqlite3.Connection):
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.model = config.model
        self.profile_manager = VoiceProfileManager(db)
        self.feedback_processor = VoiceFeedbackProcessor(db)

    def generate_email_draft(
        self,
        email: EmailMessage,
        classification: EmailClassification,
        thread_context: str | None = None,
    ) -> str:
        """Generate a draft email response."""
        system = self._build_system_prompt(recipient_type=self._guess_recipient_type(classification))

        user_content = self._format_email_context(email, classification, thread_context)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )

        draft = response.content[0].text.strip()
        # Strip quotes if the model wraps the draft in them
        if draft.startswith('"') and draft.endswith('"'):
            draft = draft[1:-1]
        return draft

    def generate_slack_draft(
        self,
        message: SlackMessage,
        classification: SlackClassification,
        thread_context: str | None = None,
    ) -> str:
        """Generate a draft Slack response."""
        system = self._build_system_prompt(recipient_type="internal")

        user_content = (
            f"Draft a Slack reply to this message.\n\n"
            f"Channel: {message.channel_name or message.channel_id}\n"
            f"From: {message.user_name or message.user_id}\n"
            f"Message: {message.text}\n"
            f"Urgency: {classification.urgency}\n"
            f"Summary: {classification.summary}\n"
        )
        if classification.draft_guidance:
            user_content += f"Guidance: {classification.draft_guidance}\n"
        if thread_context:
            user_content += f"\nThread context:\n{thread_context}\n"

        user_content += (
            "\nWrite a Slack-appropriate response. Keep it concise. "
            "Match the casual/professional tone of the channel. "
            "Do NOT wrap in quotes."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )

        draft = response.content[0].text.strip()
        if draft.startswith('"') and draft.endswith('"'):
            draft = draft[1:-1]
        return draft

    def _build_system_prompt(self, recipient_type: str | None = None) -> str:
        """Build the system prompt with voice profile and feedback."""
        # Voice profile section
        profile = self.profile_manager.get_profile()
        if profile:
            voice_section = (
                "Sarah's writing style (learned from her sent emails):\n"
                f"- Overall voice: {profile.get('overall_voice_summary', 'Direct, warm, specific')}\n"
                f"- Greeting patterns: {', '.join(profile.get('greeting_patterns', []))}\n"
                f"- Closing patterns: {', '.join(profile.get('closing_patterns', []))}\n"
                f"- Sentence length: {profile.get('avg_sentence_length', 'short')}\n"
                f"- Formality: {profile.get('formality_level', 3)}/5\n"
                f"- Tone: {', '.join(profile.get('tone_markers', ['direct', 'warm']))}\n"
                f"- Structure: {profile.get('structure_preference', 'short paragraphs')}\n"
                f"- Typical length: {profile.get('typical_email_length', '2-4 sentences')}\n"
            )
            avoid = profile.get("do_not_use", [])
            if avoid:
                voice_section += f"- NEVER use: {', '.join(avoid)}\n"

            # Per-recipient notes
            if recipient_type and recipient_type in profile.get("per_recipient_notes", {}):
                voice_section += f"- With {recipient_type}s: {profile['per_recipient_notes'][recipient_type]}\n"
        else:
            voice_section = (
                "Sarah's writing style (defaults — will be refined after voice analysis):\n"
                "- Direct and specific. Lead with the answer or action item.\n"
                "- Human tone — not corporate, not overly casual.\n"
                "- No buzzwords (never say 'synergy', 'leverage', 'circle back').\n"
                "- Keep emails under 6 sentences unless complexity requires more.\n"
            )

        # Feedback section
        feedback_summary = self.feedback_processor.get_feedback_summary(limit=20)
        if feedback_summary:
            feedback_section = f"Recent feedback on drafts (adjust your writing accordingly):\n{feedback_summary}"
        else:
            feedback_section = ""

        # Examples section
        examples = self.profile_manager.get_examples(recipient_type=recipient_type, limit=3)
        if examples:
            examples_text = "\n".join(
                f"Example (to {ex.get('recipient_type', 'unknown')}):\nSubject: {ex.get('subject', '')}\n{ex.get('sent_text', '')[:500]}"
                for ex in examples
            )
            examples_section = f"Example emails Sarah has written:\n{examples_text}"
        else:
            examples_section = ""

        return DRAFT_SYSTEM_PROMPT.format(
            voice_profile_section=voice_section,
            feedback_section=feedback_section,
            examples_section=examples_section,
        )

    def _format_email_context(
        self,
        email: EmailMessage,
        classification: EmailClassification,
        thread_context: str | None,
    ) -> str:
        parts = [
            f"Draft a reply to this email.\n",
            f"From: {email.from_name or ''} <{email.from_email}>",
            f"Subject: {email.subject}",
            f"Category: {classification.category.value}",
            f"Priority: {classification.priority.value}",
            f"Summary: {classification.summary}",
        ]
        if classification.draft_guidance:
            parts.append(f"Guidance: {classification.draft_guidance}")
        parts.append(f"\nOriginal message:\n{email.body_snippet}")
        if thread_context:
            parts.append(f"\nEarlier in this thread:\n{thread_context}")
        return "\n".join(parts)

    def _guess_recipient_type(self, classification: EmailClassification) -> str | None:
        category = classification.category.value
        if category in ("investor_intro", "partnership_followup", "deal_flow"):
            return "investor"
        elif category in ("internal_action", "internal_fyi"):
            return "internal"
        elif category in ("portfolio_request",):
            return "partner"
        return None
