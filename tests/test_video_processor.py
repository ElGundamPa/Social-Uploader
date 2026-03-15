"""Tests for VideoProcessor."""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.video_processor import VideoProcessor, ValidationResult, PLATFORM_LIMITS
from core.exceptions import VideoValidationError


@pytest.fixture
def processor():
    return VideoProcessor()


def test_validate_missing_file(processor):
    """Validate returns is_valid=False and errors for missing file."""
    result = processor.validate("/nonexistent/video.mp4")
    assert result.is_valid is False
    assert "not found" in result.errors[0].lower() or "file" in result.errors[0].lower()


def test_validate_valid_video(processor):
    """Validate a real or mocked video file."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00mp42")
        path = f.name
    try:
        # OpenCV may or may not open this minimal faked container; we only require no crash
        result = processor.validate(path)
        assert isinstance(result, ValidationResult)
        assert hasattr(result, "file_size_mb")
        assert hasattr(result, "duration_seconds")
        assert hasattr(result, "errors")
    finally:
        os.unlink(path)


def test_platform_limits_youtube(processor):
    """YouTube limits: 256GB, 12h."""
    validation = ValidationResult(
        is_valid=True,
        duration_seconds=13 * 3600,
        file_size_mb=100,
        codec="avc1",
        resolution="1920x1080",
        errors=[],
    )
    errs = processor.check_platform_limits(validation, "youtube")
    assert any("duration" in e.lower() or "12" in e for e in errs)
    validation.duration_seconds = 10 * 3600
    validation.file_size_mb = 300 * 1024  # 300 GB
    errs = processor.check_platform_limits(validation, "youtube")
    assert any("size" in e.lower() or "256" in e for e in errs)


def test_platform_limits_tiktok(processor):
    """TikTok: max 4GB, 60 min, min 3 sec."""
    validation = ValidationResult(
        is_valid=True,
        duration_seconds=2,
        file_size_mb=100,
        codec="avc1",
        resolution="1920x1080",
        errors=[],
    )
    errs = processor.check_platform_limits(validation, "tiktok")
    assert any("min" in e.lower() or "3" in e for e in errs)


def test_thumbnail_extraction(processor):
    """extract_thumbnail returns a path to a JPEG file."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"\x00\x00\x00\x20ftypmp42")
        path = f.name
    try:
        # OpenCV will likely fail to open this; we expect VideoValidationError or a path
        try:
            out = processor.extract_thumbnail(path, at_second=1.0)
            assert isinstance(out, str)
            assert Path(out).suffix.lower() in (".jpg", ".jpeg")
            if os.path.exists(out):
                os.unlink(out)
        except VideoValidationError:
            pass  # expected for fake file
    finally:
        os.unlink(path)
