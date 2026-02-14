from __future__ import annotations

import json
import logging
import sqlite3

import anthropic

from assistant.config import Config
from assistant.models import EmailMessage
from assistant.voice.profile import VoiceProfileManager

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are a writing style analyst. Analyze the following sent emails and create a comprehensive voice profile.

Focus on:
1. **Greeting patterns**: How does the person open emails? (e.g., "Hi [Name]," vs "Hey" vs no greeting)
2. **Closing patterns**: How do they sign off? (e.g., "Best," vs "Thanks," vs nothing)
3. **Sentence length**: Average sentence length. Short and punchy? Or longer, more detailed?
4. **Formality level**: Scale of 1-5 (1=very casual, 5=very formal). Note if it varies by recipient.
5. **Common phrases**: Recurring phrases or expressions they use.
6. **Tone markers**: Direct? Warm? Assertive? Deferential? Collaborative?
7. **Structure patterns**: Do they use bullet points? Numbered lists? Paragraphs? One-liners?
8. **Email length**: Typical email length in sentences.
9. **Personality signals**: Humor? Emojis? Exclamation marks? Abbreviations?
10. **Per-recipient patterns**: Any visible differences between emails to different types of people (investors, internal, partners)?

Return a JSON object with this structure:
{
    "greeting_patterns": ["pattern1", "pattern2"],
    "closing_patterns": ["pattern1", "pattern2"],
    "avg_sentence_length": "short/medium/long",
    "formality_level": 3,
    "common_phrases": ["phrase1", "phrase2"],
    "tone_markers": ["direct", "warm"],
    "structure_preference": "description",
    "typical_email_length": "2-4 sentences",
    "personality_signals": ["description"],
    "per_recipient_notes": {
        "investor": "notes about tone with investors",
        "internal": "notes about tone with teammates",
        "partner": "notes about tone with partners"
    },
    "do_not_use": ["phrases or patterns this person avoids"],
    "overall_voice_summary": "2-3 sentence summary of this person's writing voice"
}

Return ONLY the JSON object, no other text."""

CLASSIFY_RECIPIENT_PROMPT = """Classify the recipient type based on the email context.

From: {from_email}
To: {to_email}
Subject: {subject}

Recipient types:
- "investor" — VC partner, PE firm, investor relations
- "internal" — same company colleague, teammate
- "partner" — external partner, portfolio company contact
- "vendor" — sales rep, vendor, service provider
- "unknown" — can't determine

Return ONLY one word: investor, internal, partner, vendor, or unknown."""


class VoiceAnalyzer:
    """Analyzes sent emails to build a voice profile using Claude."""

    def __init__(self, config: Config, db: sqlite3.Connection):
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.model = config.model
        self.profile_manager = VoiceProfileManager(db)
        self.user_email = config.gmail_user_email

    def analyze_emails(self, emails: list[EmailMessage]) -> dict:
        """Analyze a batch of sent emails and create/update the voice profile."""
        if not emails:
            logger.warning("No emails to analyze")
            return {}

        # Build email samples for analysis
        samples = []
        for email in emails[:100]:  # Cap at 100
            to_str = ", ".join(email.to[:3])
            body = email.body_snippet[:1000]
            samples.append(
                f"To: {to_str}\nSubject: {email.subject}\n---\n{body}"
            )

        samples_text = "\n\n===== EMAIL =====\n\n".join(samples)

        logger.info("Analyzing %d sent emails for voice profile...", len(samples))

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze these {len(samples)} sent emails:\n\n{samples_text}",
                }
            ],
        )

        response_text = response.content[0].text.strip()

        # Parse JSON from response (handle markdown code blocks)
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        try:
            profile = json.loads(response_text)
        except json.JSONDecodeError:
            logger.error("Failed to parse voice profile JSON: %s", response_text[:200])
            return {}

        # Save profile
        self.profile_manager.save_profile(profile, len(samples))

        # Save individual examples with recipient classification
        for email in emails[:50]:  # Save top 50 as examples
            recipient_type = self._classify_recipient(email)
            domain = email.to[0].split("@")[1] if email.to else "unknown"
            self.profile_manager.save_example(
                email_id=email.message_id,
                recipient_type=recipient_type,
                recipient_domain=domain,
                subject=email.subject,
                sent_text=email.body_snippet[:1000],
                tone_tags=[],  # Could be enriched later
            )

        logger.info("Voice profile created from %d emails", len(samples))
        return profile

    def _classify_recipient(self, email: EmailMessage) -> str:
        """Classify the recipient type of a sent email."""
        to_email = email.to[0] if email.to else "unknown"

        # Quick heuristics before calling Claude
        user_domain = self.user_email.split("@")[1] if "@" in self.user_email else ""
        to_domain = to_email.split("@")[1] if "@" in to_email else ""

        if user_domain and to_domain == user_domain:
            return "internal"

        # Use Claude for external recipients
        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",  # Use Haiku for cheap classification
                max_tokens=10,
                messages=[
                    {
                        "role": "user",
                        "content": CLASSIFY_RECIPIENT_PROMPT.format(
                            from_email=self.user_email,
                            to_email=to_email,
                            subject=email.subject,
                        ),
                    }
                ],
            )
            result = response.content[0].text.strip().lower()
            if result in ("investor", "internal", "partner", "vendor"):
                return result
        except Exception:
            logger.exception("Failed to classify recipient for %s", to_email)

        return "unknown"
