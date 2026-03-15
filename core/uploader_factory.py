"""Shared factory for creating uploader instances by platform name."""
from core.config_manager import ConfigManager


def get_uploader(profile: str, platform: str):
    """Return uploader instance for the given profile and platform."""
    manager = ConfigManager(profile=profile)
    creds = manager.load_credentials(platform)
    return get_uploader_from_credentials(platform, creds)


def get_uploader_from_credentials(platform: str, credentials: dict):
    """Return uploader instance for the given platform and credentials dict."""
    if platform == "youtube":
        from uploaders.youtube import YouTubeUploader
        return YouTubeUploader(credentials)
    if platform == "tiktok":
        from uploaders.tiktok import TikTokUploader
        return TikTokUploader(credentials)
    if platform == "instagram":
        from uploaders.instagram import InstagramUploader
        return InstagramUploader(credentials)
    raise ValueError(f"Unknown platform: {platform}")
