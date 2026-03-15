"""Abstract base class for platform uploaders."""
from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel


class VideoMetadata(BaseModel):
    """Metadata for a video upload."""

    title: str
    description: str = ""
    tags: list[str] = []
    thumbnail_path: Optional[str] = None
    is_private: bool = False
    schedule_at: Optional[str] = None  # ISO format datetime string


class UploadResult(BaseModel):
    """Result of a single platform upload."""

    platform: str
    success: bool
    url: Optional[str] = None
    error: Optional[str] = None
    upload_id: Optional[str] = None


class BaseUploader(ABC):
    """Abstract base for YouTube, TikTok, Instagram uploaders."""

    def __init__(self, credentials: dict[str, Any]) -> None:
        self.credentials = credentials

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Validate credentials with a test API call. Return True if valid."""
        ...

    @abstractmethod
    def upload(self, video_path: str, metadata: VideoMetadata) -> UploadResult:
        """Upload video to the platform. Return UploadResult."""
        ...

    @abstractmethod
    def get_platform_name(self) -> str:
        """Return display name of the platform."""
        ...
