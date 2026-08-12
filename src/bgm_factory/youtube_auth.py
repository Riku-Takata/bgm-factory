from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import AppConfig
from .paths import ServerPaths

YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)


@dataclass(frozen=True)
class YouTubeConnection:
    authorized: bool
    channel_id: str | None = None
    channel_title: str | None = None
    token_expiry: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def credential_paths(paths: ServerPaths, config: AppConfig) -> tuple[Path, Path]:
    secret_dir = paths.config_root / "secrets"
    return (
        secret_dir / config.youtube.client_secret_file,
        secret_dir / config.youtube.token_file,
    )


def validate_client_secret(client_secret_path: Path) -> None:
    if not client_secret_path.is_file():
        raise FileNotFoundError(f"OAuth client file not found: {client_secret_path}")
    with client_secret_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    client = payload.get("installed")
    if not isinstance(client, dict):
        raise TypeError("OAuth client must be a Google Desktop app ('installed') client")
    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    missing = [name for name in required if not client.get(name)]
    if missing:
        raise ValueError(f"OAuth client is missing required fields: {', '.join(missing)}")


def _save_credentials(credentials: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{token_path.name}.", suffix=".tmp", dir=token_path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temporary:
            temporary.write(credentials.to_json())
        os.replace(temporary_name, token_path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def authorize(
    paths: ServerPaths,
    config: AppConfig,
    *,
    open_browser: bool = True,
    timeout_seconds: int = 600,
) -> Credentials:
    client_secret_path, token_path = credential_paths(paths, config)
    validate_client_secret(client_secret_path)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path), scopes=YOUTUBE_SCOPES
    )
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=open_browser,
        timeout_seconds=timeout_seconds,
        prompt="consent select_account",
        authorization_prompt_message="Open this URL to authorize BGM Factory:\n{url}",
        success_message="BGM FactoryのYouTube認証が完了しました。この画面を閉じてください。",
    )
    _save_credentials(credentials, token_path)
    return credentials


def load_credentials(paths: ServerPaths, config: AppConfig) -> Credentials:
    _, token_path = credential_paths(paths, config)
    if not token_path.is_file():
        raise FileNotFoundError("YouTube OAuth token not found. Run 'bgm-factory youtube-auth'.")
    credentials = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_SCOPES)
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            raise RuntimeError("YouTube OAuth token refresh failed; authorize again") from exc
        _save_credentials(credentials, token_path)
    if not credentials.valid:
        raise RuntimeError("YouTube OAuth token is invalid; authorize again")
    return credentials


def connection_status(paths: ServerPaths, config: AppConfig) -> YouTubeConnection:
    try:
        credentials = load_credentials(paths, config)
        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        response = youtube.channels().list(part="id,snippet", mine=True).execute()
        items = response.get("items", [])
        if not items:
            return YouTubeConnection(False, error="No YouTube channel found for this account")
        channel = items[0]
        channel_id = channel.get("id")
        expected_channel_id = config.youtube.expected_channel_id
        if expected_channel_id and channel_id != expected_channel_id:
            return YouTubeConnection(
                False,
                channel_id=channel_id,
                channel_title=channel.get("snippet", {}).get("title"),
                error=f"Authorized channel does not match expected channel {expected_channel_id}",
            )
        expiry = credentials.expiry
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return YouTubeConnection(
            True,
            channel_id=channel_id,
            channel_title=channel.get("snippet", {}).get("title"),
            token_expiry=expiry.astimezone(UTC).isoformat() if expiry else None,
        )
    except (FileNotFoundError, ValueError, RuntimeError, OSError, GoogleAuthError, HttpError) as exc:
        return YouTubeConnection(False, error=str(exc))


def authorization_summary(credentials: Credentials) -> dict:
    expiry = credentials.expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return {
        "authorized": credentials.valid,
        "token_expiry": expiry.astimezone(UTC).isoformat() if expiry else None,
        "checked_at": datetime.now(UTC).isoformat(),
    }
