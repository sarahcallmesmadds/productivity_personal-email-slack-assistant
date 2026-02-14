from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Header, HTTPException, Request

from assistant.config import load_config
from assistant.models import LinkedInDraftRequest
from assistant.db import init_db
from assistant.drafts.generator import DraftGenerator
from assistant.drafts.store import DraftStore
from assistant.email.classifier import EmailClassifier
from assistant.email.gmail_client import GmailClient
from assistant.email.scanner import EmailScanner
from assistant.notifications.notifier import SlackNotifier
from assistant.slack_monitor.listener import SlackMonitor
from assistant.voice.analyzer import VoiceAnalyzer
from assistant.voice.feedback import VoiceFeedbackProcessor
from assistant.voice.profile import VoiceProfileManager

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    db = init_db(config.db_path)

    app.state.config = config
    app.state.db = db

    logger.info("Assistant starting — db at %s", config.db_path)

    # Shared components
    gmail_client = GmailClient(config, db)
    notifier = SlackNotifier(config)
    draft_store = DraftStore(db)
    draft_generator = DraftGenerator(config, db)
    feedback_processor = VoiceFeedbackProcessor(db)
    email_classifier = EmailClassifier(config)
    voice_manager = VoiceProfileManager(db)

    # Bootstrap voice profile if not yet done
    if voice_manager.get_profile() is None:
        logger.info("No voice profile found — bootstrapping from sent emails...")
        try:
            analyzer = VoiceAnalyzer(config, db)
            sent_emails = gmail_client.get_sent_emails(max_results=100)
            if sent_emails:
                analyzer.analyze_emails(sent_emails)
                logger.info("Voice profile bootstrapped from %d sent emails", len(sent_emails))
            else:
                logger.warning("No sent emails found for voice bootstrap")
        except Exception:
            logger.exception("Voice bootstrap failed — will use defaults")

    # Email scanner (APScheduler)
    email_scanner = EmailScanner(
        config=config,
        gmail_client=gmail_client,
        classifier=email_classifier,
        draft_generator=draft_generator,
        draft_store=draft_store,
        notifier=notifier,
        db=db,
    )
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        email_scanner.scan,
        "interval",
        minutes=config.email_scan_interval_minutes,
        id="email_scan",
        next_run_time=datetime.utcnow(),  # Run immediately on startup
    )

    # Daily voice profile update
    scheduler.add_job(
        _update_voice_profile,
        "cron",
        hour=3,  # 3 AM daily
        id="voice_update",
        args=[config, db, gmail_client, voice_manager],
    )

    scheduler.start()
    logger.info("Email scanner started (every %d min)", config.email_scan_interval_minutes)

    # Slack monitor (Socket Mode in background thread)
    slack_monitor = SlackMonitor(
        config=config,
        draft_store=draft_store,
        draft_generator=draft_generator,
        notifier=notifier,
        gmail_client=gmail_client,
        feedback_processor=feedback_processor,
        db=db,
    )
    slack_thread = slack_monitor.start_in_thread()

    app.state.draft_store = draft_store
    app.state.draft_generator = draft_generator
    app.state.gmail_client = gmail_client

    logger.info("Assistant fully started")

    yield

    scheduler.shutdown(wait=False)
    db.close()
    logger.info("Assistant shut down")


def _update_voice_profile(
    config, db, gmail_client: GmailClient, voice_manager: VoiceProfileManager
):
    """Daily job to update voice profile from recent sent emails."""
    try:
        analyzer = VoiceAnalyzer(config, db)
        sent_emails = gmail_client.get_sent_emails(max_results=50)
        if sent_emails:
            analyzer.analyze_emails(sent_emails)
            logger.info("Voice profile updated from %d sent emails", len(sent_emails))
    except Exception:
        logger.exception("Voice profile update failed")


app = FastAPI(title="Personal Assistant Agent", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/linkedin/draft")
def linkedin_draft(req: Request, body: LinkedInDraftRequest, authorization: str = Header()):
    """Generate a draft response for a LinkedIn DM. Called by the Chrome extension."""
    # Auth check
    expected = f"Bearer {req.app.state.config.api_secret}"
    if not req.app.state.config.api_secret or authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    generator: DraftGenerator = req.app.state.draft_generator
    return generator.generate_linkedin_draft(body)
