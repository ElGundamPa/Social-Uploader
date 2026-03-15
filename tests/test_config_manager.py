"""Tests for ConfigManager."""
import json
import os
import tempfile
from pathlib import Path
import pytest
import yaml

from core.config_manager import ConfigManager
from core.exceptions import SocialUploaderError


@pytest.fixture
def temp_config_dir(tmp_path):
    """Use a temporary directory as project root with config/."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return tmp_path


@pytest.fixture
def manager(temp_config_dir):
    """ConfigManager using temp dir as root."""
    m = ConfigManager(profile="default")
    m._root = temp_config_dir
    m._config_dir = temp_config_dir / "config"
    m._credentials_path = m._config_dir / "credentials.yaml"
    m._history_path = m._config_dir / "upload_history.json"
    m._config_dir.mkdir(parents=True, exist_ok=True)
    return m


def test_save_and_load_credentials(manager):
    """Save credentials for a platform and load them back."""
    manager._config_dir.mkdir(parents=True, exist_ok=True)
    creds = {"enabled": True, "client_key": "test_key", "client_secret": "test_secret"}
    manager.save_credentials("tiktok", creds)
    loaded = manager.load_credentials("tiktok")
    assert loaded.get("enabled") is True
    assert loaded.get("client_key") == "test_key"
    assert loaded.get("client_secret") == "test_secret"


def test_encryption_decryption(manager):
    """Encrypted values decrypt back to original (via save/load)."""
    manager.save_credentials("tiktok", {"enabled": True, "client_key": "secret_key", "client_secret": "secret_secret"})
    loaded = manager.load_credentials("tiktok")
    assert loaded["client_key"] == "secret_key"
    assert loaded["client_secret"] == "secret_secret"


def test_invalid_profile_raises_error(manager):
    """Loading credentials for a non-existent profile raises."""
    manager._config_dir.mkdir(parents=True, exist_ok=True)
    # File exists but profile "default" is missing
    with open(manager._credentials_path, "w") as f:
        yaml.safe_dump({"profiles": {"other_profile": {}}}, f)
    with pytest.raises(SocialUploaderError):
        manager.load_credentials("youtube")


def test_upload_history_limit(manager):
    """get_upload_history returns at most limit entries."""
    manager._config_dir.mkdir(parents=True, exist_ok=True)
    history = [{"title": f"Upload {i}", "platforms": ["youtube"]} for i in range(30)]
    with open(manager._history_path, "w") as f:
        json.dump(history, f)
    result = manager.get_upload_history(limit=20)
    assert len(result) == 20
    assert result[0]["title"] == "Upload 29"  # last 20, reversed
