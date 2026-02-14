from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

load_dotenv()


class Config(BaseModel):
    # Claude
    anthropic_api_key: str
    model: str = "claude-sonnet-4-20250514"

    # Gmail OAuth2 (JSON strings from env vars)
    gmail_credentials_json: str
    gmail_token_json: str
    gmail_user_email: str

    # Slack
    slack_bot_token: str
    slack_app_token: str
    slack_user_id: str

    # Monitoring
    slack_channel_ids: list[str] = []
    email_scan_interval_minutes: int = 5

    # API auth
    api_secret: str = ""

    # Database
    db_path: str = "data/assistant.db"

    @field_validator("slack_channel_ids", mode="before")
    @classmethod
    def parse_channel_ids(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v


def load_config() -> Config:
    return Config(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        model=os.environ.get("MODEL", "claude-sonnet-4-20250514"),
        gmail_credentials_json=os.environ["GMAIL_CREDENTIALS_JSON"],
        gmail_token_json=os.environ["GMAIL_TOKEN_JSON"],
        gmail_user_email=os.environ["GMAIL_USER_EMAIL"],
        slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
        slack_app_token=os.environ["SLACK_APP_TOKEN"],
        slack_user_id=os.environ["SLACK_USER_ID"],
        slack_channel_ids=os.environ.get("SLACK_CHANNEL_IDS", ""),
        email_scan_interval_minutes=int(
            os.environ.get("EMAIL_SCAN_INTERVAL_MINUTES", "5")
        ),
        api_secret=os.environ.get("API_SECRET", ""),
        db_path=os.environ.get("DB_PATH", "data/assistant.db"),
    )
