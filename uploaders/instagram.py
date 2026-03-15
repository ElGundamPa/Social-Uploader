"""Instagram uploader using instagrapi (Reels primary, feed video fallback)."""
import os
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    ChallengeRequired,
    TwoFactorRequired,
    BadPassword,
)

from uploaders.base import BaseUploader, VideoMetadata, UploadResult
from core.exceptions import AuthenticationError, PlatformError

logger = logging.getLogger(__name__)

MAX_SIZE_GB = 4
MAX_DURATION_REEL_MIN = 15  # recommended for Reels


class InstagramUploader(BaseUploader):
    """Upload videos to Instagram as Reels (primary) or feed video."""

    def __init__(self, credentials: dict[str, Any], prompt_2fa: Callable[[], str] | None = None) -> None:
        super().__init__(credentials)
        self._root = Path(__file__).resolve().parent.parent
        self._username = credentials.get("username", "")
        self._password = credentials.get("password", "")
        self._session_path = credentials.get("session_path") or "config/instagram_session.json"
        if not os.path.isabs(self._session_path):
            self._session_path = str(self._root / self._session_path)
        self._prompt_2fa = prompt_2fa
        self._client: Client | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> Client:
        with self._lock:
            if self._client is not None:
                return self._client
            cl = Client()
            session_dir = os.path.dirname(self._session_path)
            if session_dir:
                os.makedirs(session_dir, exist_ok=True)
            if os.path.exists(self._session_path):
                try:
                    cl.load_settings(self._session_path)
                    cl.login(self._username, self._password)
                except TwoFactorRequired:
                    code = (self._prompt_2fa or (lambda: input("Instagram 2FA code: ")))()
                    cl.login(self._username, self._password, verification_code=code)
                except (LoginRequired, ChallengeRequired, BadPassword):
                    raise AuthenticationError(
                        "Instagram session expired. Run: social-uploader config --platform instagram"
                    )
                except Exception as e:
                    logger.warning("Instagram session load failed: %s", e)
                    cl = Client()
                    cl.login(self._username, self._password)
            else:
                try:
                    cl.login(self._username, self._password)
                except TwoFactorRequired:
                    code = (self._prompt_2fa or (lambda: input("Instagram 2FA code: ")))()
                    cl.login(self._username, self._password, verification_code=code)
                except (BadPassword, ChallengeRequired):
                    raise AuthenticationError(
                        "Instagram login failed (checkpoint or bad password). "
                        "Run: social-uploader config --platform instagram"
                    )
            cl.dump_settings(self._session_path)
            self._client = cl
            return self._client

    def get_platform_name(self) -> str:
        return "Instagram"

    def validate_credentials(self) -> bool:
        try:
            cl = self._get_client()
            cl.user_info_by_username(cl.username)
            return True
        except (LoginRequired, ChallengeRequired) as e:
            raise AuthenticationError(
                "Instagram session expired or checkpoint required. Run: social-uploader config --platform instagram"
            )
        except Exception as e:
            logger.exception("Instagram credential validation failed: %s", e)
            raise AuthenticationError("Run: social-uploader config --platform instagram")

    def upload(self, video_path: str, metadata: VideoMetadata) -> UploadResult:
        try:
            cl = self._get_client()
            path = Path(video_path)
            if not path.exists():
                return UploadResult(platform="Instagram", success=False, error="File not found")
            caption = metadata.title
            if metadata.description:
                caption = (caption + "\n\n" + metadata.description).strip()
            if metadata.tags:
                caption = caption + "\n\n" + " ".join("#" + t.replace("#", "").strip() for t in metadata.tags)
            caption = (caption or "Uploaded with social-uploader")[:2200]
            thumbnail_path = metadata.thumbnail_path
            if not thumbnail_path or not os.path.isfile(thumbnail_path):
                thumbnail_path = None  # instagrapi can use first frame
            usertags = []
            location = None
            # Prefer Reels (clip_upload); fallback to video_upload for feed
            try:
                media = cl.clip_upload(
                    path,
                    caption=caption,
                    thumbnail=Path(thumbnail_path) if thumbnail_path else path,
                    usertags=usertags,
                    location=location,
                )
            except Exception as reel_err:
                logger.warning("Reel upload failed, trying feed video: %s", reel_err)
                try:
                    media = cl.video_upload(
                        path,
                        caption=caption,
                        thumbnail=Path(thumbnail_path) if thumbnail_path else path,
                        usertags=usertags,
                        location=location,
                    )
                except Exception as feed_err:
                    raise PlatformError(str(feed_err))
            if media and getattr(media, "pk", None):
                url = f"https://www.instagram.com/p/{media.code}/" if getattr(media, "code", None) else None
                return UploadResult(
                    platform="Instagram",
                    success=True,
                    url=url,
                    upload_id=str(media.pk),
                )
            return UploadResult(platform="Instagram", success=False, error="No media returned")
        except (AuthenticationError, PlatformError):
            raise
        except LoginRequired:
            raise AuthenticationError("Instagram session expired. Run: social-uploader config --platform instagram")
        except ChallengeRequired:
            raise AuthenticationError("Instagram checkpoint required. Run: social-uploader config --platform instagram")
        except Exception as e:
            logger.exception("Instagram upload failed: %s", e)
            return UploadResult(platform="Instagram", success=False, error=str(e))
