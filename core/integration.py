"""
Hook for video editor: call this when export finishes.

Example usage in video editor (run from project root or after pip install -e .):

    from core.integration import upload_after_export
    results = upload_after_export(
        video_path="/exports/final_video.mp4",
        title="My Edited Video",
        tags=["edit", "tutorial"]
    )
"""
from pathlib import Path
from typing import Any

from uploaders.base import VideoMetadata
from core.config_manager import ConfigManager
from core.uploader_factory import get_uploader as _get_uploader
from core.video_processor import VideoProcessor


def upload_after_export(
    video_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    platforms: list[str] | None = None,
    profile: str = "default",
    thumbnail_path: str | None = None,
    is_private: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Import and call this function from your video editor when export finishes.

    Returns:
        {
            "youtube":   {"success": True,  "url": "https://youtu.be/xxx"},
            "tiktok":    {"success": True,  "url": "https://tiktok.com/@user/video/xxx"},
            "instagram": {"success": False, "error": "Session expired"}
        }
    """
    tags = tags or []
    platforms = platforms if platforms is not None else ["all"]
    manager = ConfigManager(profile=profile)
    if platforms == ["all"] or "all" in platforms:
        platform_list = manager.list_platforms()
    else:
        platform_list = [p.strip().lower() for p in platforms if p.strip()]

    if not platform_list:
        return {}

    processor = VideoProcessor()
    validation = processor.validate(video_path)
    if not validation.is_valid:
        return {p: {"success": False, "error": "; ".join(validation.errors)} for p in platform_list}

    thumb = thumbnail_path
    if not thumb:
        try:
            thumb = processor.extract_thumbnail(video_path, at_second=1.0)
        except Exception:
            pass

    metadata = VideoMetadata(
        title=title,
        description=description,
        tags=tags,
        thumbnail_path=thumb,
        is_private=is_private,
    )

    out: dict[str, dict[str, Any]] = {}
    for platform in platform_list:
        try:
            uploader = _get_uploader(profile, platform)
            result = uploader.upload(video_path, metadata)
            out[platform] = {
                "success": result.success,
                "url": result.url,
                "error": result.error,
            }
        except Exception as e:
            out[platform] = {"success": False, "error": str(e)}
    return out
