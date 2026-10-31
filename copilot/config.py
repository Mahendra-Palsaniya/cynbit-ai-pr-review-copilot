"""Read only explicitly supported local secret locations, never log their values."""

import os
from pathlib import Path
import tomllib


def local_credentials():
    key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    secret_file = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
    if not key and secret_file.exists():
        try:
            values = tomllib.loads(secret_file.read_text(encoding="utf-8-sig"))
            key = values.get("OPENAI_API_KEY")
            model = values.get("OPENAI_MODEL", model)
        except (OSError, ValueError):
            return None, model
    return key if isinstance(key, str) and key.strip() else None, model


def github_token():
    token = os.getenv("GITHUB_TOKEN")
    path = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
    if not token and path.exists():
        try:
            token = tomllib.loads(path.read_text(encoding="utf-8-sig")).get(
                "GITHUB_TOKEN"
            )
        except (OSError, ValueError):
            return None
    return token if isinstance(token, str) and token.strip() else None


def github_publish_code():
    value = os.getenv("GITHUB_PUBLISH_CODE")
    path = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
    if not value and path.exists():
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8-sig")).get(
                "GITHUB_PUBLISH_CODE"
            )
        except (OSError, ValueError):
            return None
    return value if isinstance(value, str) and value.strip() else None
