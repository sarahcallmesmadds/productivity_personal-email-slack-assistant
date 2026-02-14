# CLAUDE.md — Personal Email & Slack Assistant

## What this is
A Python app (Railway-hosted) that monitors Gmail and Slack, classifies messages, drafts responses in Sarah's voice, and handles approval flows.

## Architecture
- One FastAPI container on Railway with persistent SQLite volume
- Email scanner: APScheduler polls Gmail every 5 min
- Slack monitor: Bolt Socket Mode listens in real-time
- Voice engine: learns writing style from sent emails + feedback

## Key patterns
- Email drafts → Slack DM with Block Kit buttons (Send/Edit/Reject)
- Slack drafts → ephemeral messages in-thread (copy-paste, no buttons)
- Voice profile stored in SQLite, updated daily + from edit diffs
- Gmail uses incremental sync (historyId) after first scan

## Running locally
```bash
source .venv/bin/activate
# Set env vars in .env (see .env.example)
uvicorn assistant.app:app --reload
```

## Deploying
```bash
# Push to Railway — Dockerfile handles the rest
# Set all env vars in Railway dashboard
# Mount persistent volume at /app/data for SQLite
```

## Project layout
- `src/assistant/app.py` — FastAPI entry point + lifespan
- `src/assistant/email/` — Gmail client, scanner, classifier
- `src/assistant/slack_monitor/` — Bolt listener, classifier, interactive handlers
- `src/assistant/drafts/` — store (SQLite CRUD), generator (Claude-powered)
- `src/assistant/voice/` — analyzer, profile manager, feedback processor
- `src/assistant/notifications/` — Slack DM notifier (Block Kit)
- `scripts/gmail_auth.py` — one-time OAuth consent flow

## Tech stack
Python 3.12, FastAPI, slack-bolt, google-api-python-client, anthropic, APScheduler, SQLite
