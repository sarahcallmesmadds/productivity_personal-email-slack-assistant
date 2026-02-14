"""
One-time local script to get Gmail OAuth2 tokens.

Run this on your laptop (not on Railway) to authorize the app:

    python scripts/gmail_auth.py

This will:
1. Open a browser for Google OAuth consent
2. Save token.json locally
3. Print the token JSON for you to paste into Railway env vars

Prerequisites:
1. Create a Google Cloud project at https://console.cloud.google.com
2. Enable the Gmail API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download credentials.json to this directory
"""

from __future__ import annotations

import json
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")


def main():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print(f"ERROR: {CREDENTIALS_FILE} not found.")
                print("Download it from Google Cloud Console → APIs → Credentials → OAuth 2.0 Client IDs")
                sys.exit(1)

            print("Opening browser for OAuth consent...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}")

    # Print the values to paste into Railway env vars
    print("\n" + "=" * 60)
    print("Copy these into your Railway environment variables:")
    print("=" * 60)

    with open(CREDENTIALS_FILE) as f:
        creds_json = f.read().strip()
    print(f"\nGMAIL_CREDENTIALS_JSON={creds_json}")

    with open(TOKEN_FILE) as f:
        token_json = f.read().strip()
    print(f"\nGMAIL_TOKEN_JSON={token_json}")

    print("\n" + "=" * 60)
    print("Done. You can now deploy to Railway with these env vars.")


if __name__ == "__main__":
    main()
