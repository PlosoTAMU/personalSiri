"""Print the newest "Daily brief" email as text to speak. Also holds the one-time Gmail sign-in.

Read-only Gmail scope. Files, both in ~/.config/ploso/:
  gmail-client.json  OAuth client ("Desktop app") downloaded from Google Cloud
  gmail-token.json   written by `ploso gmail-auth`, refreshed here when it expires
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from datetime import date

from .config import CONFIG_DIR

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT = CONFIG_DIR / "gmail-client.json"
TOKEN = CONFIG_DIR / "gmail-token.json"
QUERY = 'from:me subject:"Daily brief" newer_than:2d'
AUTH_PORT = 8765

# The brief ends with the items it chose not to surface. Not worth hearing every morning.
QUIET_HEADINGS = {"BACKGROUND", "SUPPRESSED", "QUIET"}
_SUBJECT_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _write_token(creds) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(TOKEN, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())


def authorize() -> None:
    """One-time browser consent. Works over ssh: forward the port and open the printed URL."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT.is_file():
        sys.exit(f"Put the OAuth client JSON from Google Cloud at {CLIENT} first. See README.")
    print(f"If this machine has no browser, run on your own machine first:\n"
          f"  ssh -L {AUTH_PORT}:localhost:{AUTH_PORT} <this-host>\nthen open the URL below there.\n")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    creds = flow.run_local_server(port=AUTH_PORT, open_browser=False)
    _write_token(creds)
    print(f"Saved {TOKEN}")


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
        _write_token(creds)
    return creds


def _plain_text(payload: dict) -> str:
    """First text/plain part of a Gmail message payload, depth first."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []):
        text = _plain_text(part)
        if text:
            return text
    return ""


def cut_quiet_tail(text: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() in QUIET_HEADINGS:
            return "\n".join(lines[:i]).rstrip()
    return text.rstrip()


def fetch() -> tuple[str, str] | None:
    """(subject, plain text) of the newest brief, or None when there is none."""
    from googleapiclient.discovery import build

    gmail = build("gmail", "v1", credentials=_credentials(), cache_discovery=False)
    found = gmail.users().messages().list(userId="me", q=QUERY, maxResults=1).execute()
    if not found.get("messages"):
        return None
    msg = gmail.users().messages().get(userId="me", id=found["messages"][0]["id"], format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    return headers.get("subject", ""), _plain_text(msg["payload"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--full", action="store_true", help="include the background and suppressed lists")
    args = ap.parse_args(argv)

    if not TOKEN.is_file():
        print("Gmail is not set up yet. Run ploso gmail-auth on this machine.")
        return 1
    try:
        brief = fetch()
    except Exception as exc:  # noqa: BLE001 - spoken to the user, detail goes to the log
        print("I could not reach Gmail.")
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not brief or not brief[1].strip():
        print("There is no daily brief from the last two days.")
        return 0

    subject, text = brief
    stamp = _SUBJECT_DATE.search(subject)
    if stamp and date(*map(int, stamp.groups())) != date.today():
        when = date(*map(int, stamp.groups())).strftime("%A, %B %-d")
        print(f"Today's brief has not arrived. This is the one from {when}.\n")
    print(text.rstrip() if args.full else cut_quiet_tail(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
