import json

import pytest

from bgm_factory.config import AppConfig
from bgm_factory.youtube_auth import credential_paths, validate_client_secret


def test_validate_installed_client_secret(tmp_path) -> None:
    client = tmp_path / "client_secret.json"
    client.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "example.apps.googleusercontent.com",
                    "client_secret": "secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        ),
        encoding="utf-8",
    )

    validate_client_secret(client)


def test_validate_rejects_web_client(tmp_path) -> None:
    client = tmp_path / "client_secret.json"
    client.write_text(json.dumps({"web": {"client_id": "example"}}), encoding="utf-8")

    with pytest.raises(TypeError, match="Desktop app"):
        validate_client_secret(client)


def test_credential_paths_stay_under_config_secrets(tmp_path) -> None:
    paths = type("Paths", (), {"config_root": tmp_path})()

    client, token = credential_paths(paths, AppConfig())

    assert client == tmp_path / "secrets" / "client_secret.json"
    assert token == tmp_path / "secrets" / "token.json"
