"""Google OAuth flow + token persistence.

Personal-tool model:
- One Google Cloud project with the Calendar API enabled and a Desktop OAuth
  client (downloaded as client_secret.json).
- Read-only scope (calendar.readonly) — we never write back to the calendar.
- Refresh token cached locally so the user only auths once.

This module does not own any UX — `prep-agent calendar auth` (CLI) and the
Streamlit page both call into it.
"""
from __future__ import annotations

from pathlib import Path
from typing import cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class GoogleAuthError(RuntimeError):
    """Auth setup mistake we should describe to the user, not raise raw."""


def load_credentials(token_path: Path) -> Credentials | None:
    """Load existing creds, refresh transparently if expired.

    Returns None if no token has been minted yet.
    """
    if not token_path.exists():
        return None
    creds = cast(
        Credentials,
        Credentials.from_authorized_user_file(str(token_path), SCOPES),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _persist(creds, token_path)
    return creds


def run_oauth_flow(client_secret_path: Path, token_path: Path) -> Credentials:
    """Open a browser, capture the redirect, write the token file. Blocking."""
    if not client_secret_path.exists():
        raise GoogleAuthError(
            f"Missing client secret file at {client_secret_path}. "
            "Create an OAuth 'Desktop app' credential in Google Cloud Console, "
            "download the JSON, and save it to that path (or override via "
            "GOOGLE_CLIENT_SECRET_PATH)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    # port=0 → pick a free port for the local redirect listener
    creds = cast(Credentials, flow.run_local_server(port=0))
    _persist(creds, token_path)
    return creds


def get_or_refresh_credentials(
    client_secret_path: Path,
    token_path: Path,
) -> Credentials:
    """One-shot: return valid creds, prompting OAuth if no token exists."""
    creds = load_credentials(token_path)
    if creds and creds.valid:
        return creds
    return run_oauth_flow(client_secret_path, token_path)


def _persist(creds: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(cast(str, creds.to_json()))
