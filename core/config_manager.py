"""Load/save credentials with encryption and profile support."""
import json
import os
import platform
import uuid
import hashlib
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from cryptography.fernet import Fernet

from core.exceptions import SocialUploaderError

# Sensitive keys we encrypt in credentials.yaml
_ENCRYPTED_KEYS = {
    "youtube": {"client_secret_path", "token_path"},
    "tiktok": {"client_key", "client_secret", "access_token"},
    "instagram": {"username", "password"},
}


def _get_machine_id() -> str:
    """Derive a stable machine identifier (Windows-friendly)."""
    try:
        return str(uuid.getnode())
    except Exception:
        return platform.node()


def _get_encryption_key() -> bytes:
    """Derive Fernet key from machine UUID / env PIN."""
    import platform
    pin = os.environ.get("UPLOADER_ENCRYPTION_PIN", "").strip()
    raw = (pin or _get_machine_id()).encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return key


def _ensure_config_dir(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)


def _encrypt_value(fernet: Fernet, value: str) -> str:
    if not value:
        return ""
    return fernet.encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_value(fernet: Fernet, value: str) -> str:
    if not value or not value.strip():
        return ""
    try:
        return fernet.decrypt(value.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


class ConfigManager:
    """Manage per-profile credentials with optional encryption at rest."""

    def __init__(self, profile: str = "default") -> None:
        self.profile = profile
        self._root = Path(__file__).resolve().parent.parent
        self._config_dir = self._root / "config"
        self._credentials_path = self._config_dir / "credentials.yaml"
        self._history_path = self._config_dir / "upload_history.json"
        self._fernet = Fernet(_get_encryption_key())

    def _load_raw_config(self) -> dict[str, Any]:
        _ensure_config_dir(self._config_dir)
        if not self._credentials_path.exists():
            return {"profiles": {}}
        with open(self._credentials_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"profiles": {}}

    def _save_raw_config(self, data: dict[str, Any]) -> None:
        _ensure_config_dir(self._config_dir)
        with open(self._credentials_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)

    def load_credentials(self, platform: str) -> dict[str, Any]:
        """Load credentials for a platform (decrypting sensitive fields)."""
        raw = self._load_raw_config()
        profiles = raw.get("profiles", {})
        if self.profile not in profiles:
            raise SocialUploaderError(f"Profile '{self.profile}' not found. Run: social-uploader setup --profile {self.profile}")
        profile_data = profiles[self.profile]
        platform_data = profile_data.get(platform)
        if not platform_data:
            return {}
        platform_data = dict(platform_data)
        encrypted_keys = _ENCRYPTED_KEYS.get(platform, set())
        for key in encrypted_keys:
            if key in platform_data and platform_data[key]:
                platform_data[key] = _decrypt_value(self._fernet, platform_data[key])
        return platform_data

    def save_credentials(self, platform: str, credentials: dict[str, Any]) -> None:
        """Save credentials for a platform (encrypting sensitive fields)."""
        raw = self._load_raw_config()
        if "profiles" not in raw:
            raw["profiles"] = {}
        if self.profile not in raw["profiles"]:
            raw["profiles"][self.profile] = {}
        to_save = dict(credentials)
        encrypted_keys = _ENCRYPTED_KEYS.get(platform, set())
        for key in encrypted_keys:
            if key in to_save and to_save[key]:
                to_save[key] = _encrypt_value(self._fernet, str(to_save[key]))
        raw["profiles"][self.profile][platform] = to_save
        self._save_raw_config(raw)

    def list_platforms(self) -> list[str]:
        """Return list of enabled platform names for current profile."""
        raw = self._load_raw_config()
        profiles = raw.get("profiles", {})
        if self.profile not in profiles:
            return []
        profile_data = profiles[self.profile]
        return [
            name for name, data in profile_data.items()
            if isinstance(data, dict) and data.get("enabled") is True
        ]

    def is_platform_enabled(self, platform: str) -> bool:
        """Check if a platform is enabled in current profile."""
        return platform in self.list_platforms()

    def save_upload_record(self, record: dict[str, Any]) -> None:
        """Append a record to upload history with timestamp."""
        _ensure_config_dir(self._config_dir)
        history: list[dict] = []
        if self._history_path.exists():
            try:
                with open(self._history_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except (json.JSONDecodeError, IOError):
                history = []
        if not isinstance(history, list):
            history = []
        record_with_ts = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **record,
        }
        history.append(record_with_ts)
        with open(self._history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    def get_upload_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return last N upload history entries."""
        if not self._history_path.exists():
            return []
        try:
            with open(self._history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
        if not isinstance(history, list):
            return []
        return list(history[-limit:])[::-1]
