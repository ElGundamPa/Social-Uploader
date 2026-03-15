"""Pre-upload video validation and thumbnail extraction."""
import os
import tempfile
from pathlib import Path
from typing import Any

import cv2
from pydantic import BaseModel

from core.exceptions import VideoValidationError

# Platform limits: (max_size_gb, max_duration_sec, min_duration_sec)
PLATFORM_LIMITS = {
    "youtube": (256, 12 * 3600, 0),
    "tiktok": (4, 60 * 60, 3),
    "instagram": (4, 90 * 60, 0),  # Reels recommended max 15 min
}


class ValidationResult(BaseModel):
    """Result of video file validation."""

    is_valid: bool
    duration_seconds: float = 0.0
    file_size_mb: float = 0.0
    codec: str = ""
    resolution: str = ""
    errors: list[str] = []


class VideoProcessor:
    """Validate videos and extract thumbnails before upload."""

    def __init__(self) -> None:
        self._root = Path(__file__).resolve().parent.parent

    def validate(self, video_path: str) -> ValidationResult:
        """Validate video file: exists, readable, duration, size, codec, resolution."""
        errors: list[str] = []
        if not video_path or not os.path.isfile(video_path):
            return ValidationResult(is_valid=False, errors=["File not found or not a file"])
        try:
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        except OSError as e:
            return ValidationResult(is_valid=False, errors=[f"Cannot read file size: {e}"])
        duration_seconds = 0.0
        codec = ""
        resolution = ""
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                errors.append("Could not open video file")
            else:
                fps = cap.get(cv2.CAP_PROP_FPS) or 1
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if frame_count and frame_count > 0 and fps > 0:
                    duration_seconds = frame_count / fps
                fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                codec = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)) if fourcc else "unknown"
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                resolution = f"{w}x{h}" if w and h else ""
                cap.release()
        except Exception as e:
            errors.append(f"OpenCV error: {e}")
        if not errors and duration_seconds <= 0:
            errors.append("Could not determine duration")
        return ValidationResult(
            is_valid=len(errors) == 0,
            duration_seconds=duration_seconds,
            file_size_mb=round(file_size_mb, 2),
            codec=codec.strip() or "unknown",
            resolution=resolution or "unknown",
            errors=errors,
        )

    def check_platform_limits(
        self, validation: ValidationResult, platform: str
    ) -> list[str]:
        """Return list of errors if video exceeds platform limits."""
        errs: list[str] = []
        limits = PLATFORM_LIMITS.get(platform.lower())
        if not limits:
            return errs
        max_gb, max_sec, min_sec = limits
        size_gb = validation.file_size_mb / 1024
        if size_gb > max_gb:
            errs.append(f"File size {validation.file_size_mb:.2f} MB exceeds {platform} limit ({max_gb} GB)")
        if validation.duration_seconds > max_sec:
            errs.append(f"Duration {validation.duration_seconds:.0f}s exceeds {platform} limit ({max_sec // 3600}h)")
        if min_sec and validation.duration_seconds < min_sec:
            errs.append(f"Duration {validation.duration_seconds:.1f}s below {platform} minimum ({min_sec}s)")
        return errs

    def extract_thumbnail(self, video_path: str, at_second: float = 1.0) -> str:
        """Extract a frame as JPEG thumbnail; return path to the saved image."""
        if not os.path.isfile(video_path):
            raise VideoValidationError("File not found")
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise VideoValidationError("Could not open video for thumbnail")
        fps = cap.get(cv2.CAP_PROP_FPS) or 1
        frame_index = int(at_second * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_index))
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            cap = cv2.VideoCapture(video_path)
            ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                raise VideoValidationError("Could not read frame for thumbnail")
        base = Path(video_path).stem
        fd, path = tempfile.mkstemp(suffix=".jpg", prefix=f"{base}_thumb_")
        os.close(fd)
        cv2.imwrite(path, frame)
        return path

    def get_video_info(self, video_path: str) -> dict[str, Any]:
        """Return dict with duration_seconds, file_size_mb, codec, resolution."""
        v = self.validate(video_path)
        return {
            "duration_seconds": v.duration_seconds,
            "file_size_mb": v.file_size_mb,
            "codec": v.codec,
            "resolution": v.resolution,
            "is_valid": v.is_valid,
            "errors": v.errors,
        }
