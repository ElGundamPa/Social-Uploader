"""TikTok uploader using Content Posting API v2 (Direct Post + FILE_UPLOAD)."""
import os
import time
import logging
from pathlib import Path
from typing import Any

import requests

from uploaders.base import BaseUploader, VideoMetadata, UploadResult
from core.exceptions import AuthenticationError, QuotaExceededError, PlatformError, NetworkError

logger = logging.getLogger(__name__)

BASE_URL = "https://open.tiktokapis.com"
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024  # 4GB
MAX_DURATION_SEC = 60 * 60  # 60 min


def _get_access_token(client_key: str, client_secret: str, refresh_token: str | None) -> str:
    """Refresh or obtain access token. In production, store refresh_token from OAuth flow."""
    # If we only have static access_token in credentials, we cannot refresh; caller must provide valid token.
    return ""


class TikTokUploader(BaseUploader):
    """Upload videos to TikTok via Content Posting API v2."""

    def __init__(self, credentials: dict[str, Any]) -> None:
        super().__init__(credentials)
        self._root = Path(__file__).resolve().parent.parent
        self._client_key = credentials.get("client_key", "")
        self._client_secret = credentials.get("client_secret", "")
        self._access_token = credentials.get("access_token", "")
        self._refresh_token = credentials.get("refresh_token")
        self._username = credentials.get("username", "")

    def get_platform_name(self) -> str:
        return "TikTok"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def validate_credentials(self) -> bool:
        """Validate by calling creator info or a lightweight API."""
        try:
            r = requests.post(
                f"{BASE_URL}/v2/post/publish/creator_info/query/",
                headers=self._headers(),
                json={},
                timeout=15,
            )
            data = r.json() if r.text else {}
            err = data.get("error", {})
            code = err.get("code", "")
            if code and code != "ok":
                if "access_token" in code or "token" in (code or "").lower() or r.status_code == 401:
                    raise AuthenticationError("TikTok access token invalid or expired. Run: social-uploader config --platform tiktok")
                if "quota" in (err.get("message") or "").lower():
                    raise QuotaExceededError("TikTok quota exceeded.")
                raise PlatformError(err.get("message", "TikTok API error"))
            return True
        except (AuthenticationError, QuotaExceededError, PlatformError):
            raise
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e))
        except Exception as e:
            logger.exception("TikTok credential validation failed: %s", e)
            raise AuthenticationError("Run: social-uploader config --platform tiktok")

    def upload(self, video_path: str, metadata: VideoMetadata) -> UploadResult:
        try:
            file_size = os.path.getsize(video_path)
            if file_size > MAX_FILE_SIZE:
                return UploadResult(
                    platform="TikTok",
                    success=False,
                    error=f"File size exceeds 4GB limit ({file_size / (1024**3):.2f} GB)",
                )
            chunk_size = min(CHUNK_SIZE, file_size)
            total_chunks = (file_size + chunk_size - 1) // chunk_size

            # 1) Init direct post
            privacy = "SELF_ONLY" if metadata.is_private else "PUBLIC_TO_EVERYONE"
            caption = (metadata.title + "\n" + (metadata.description or "")).strip()[:2200]
            title = caption or metadata.title[:2200]
            body = {
                "post_info": {
                    "privacy_level": privacy,
                    "title": title,
                    "disable_duet": False,
                    "disable_stitch": False,
                    "disable_comment": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": file_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunks,
                },
            }
            r = requests.post(
                f"{BASE_URL}/v2/post/publish/video/init/",
                headers=self._headers(),
                json=body,
                timeout=30,
            )
            data = r.json() if r.text else {}
            err = data.get("error", {})
            if err.get("code") and err.get("code") != "ok":
                msg = err.get("message", "")
                if "access_token" in (err.get("code") or "") or r.status_code == 401:
                    raise AuthenticationError("TikTok access token invalid or expired. Run: social-uploader config --platform tiktok")
                if "spam" in msg.lower() or "quota" in msg.lower():
                    raise QuotaExceededError("TikTok: " + (msg or "spam/rate limit. Retry later."))
                return UploadResult(platform="TikTok", success=False, error=msg or str(err))

            info = data.get("data", {})
            publish_id = info.get("publish_id")
            upload_url = info.get("upload_url")
            if not upload_url or not publish_id:
                return UploadResult(platform="TikTok", success=False, error="No upload_url or publish_id in response")

            # 2) Upload file (single PUT with full file for simplicity; can be chunked)
            content_type = "video/mp4"
            if video_path.lower().endswith(".mov"):
                content_type = "video/quicktime"
            elif video_path.lower().endswith(".webm"):
                content_type = "video/webm"
            with open(video_path, "rb") as f:
                upload_headers = {
                    "Content-Type": content_type,
                    "Content-Length": str(file_size),
                    "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                }
                put = requests.put(upload_url, headers=upload_headers, data=f, timeout=600)
            if put.status_code not in (200, 201, 204):
                return UploadResult(
                    platform="TikTok",
                    success=False,
                    error=f"Upload failed: HTTP {put.status_code}",
                )

            # 3) Poll status until PUBLISH_COMPLETE or FAILED
            for _ in range(60):
                time.sleep(2)
                sr = requests.post(
                    f"{BASE_URL}/v2/post/publish/status/fetch/",
                    headers=self._headers(),
                    json={"publish_id": publish_id},
                    timeout=15,
                )
                sdata = sr.json() if sr.text else {}
                serr = sdata.get("error", {})
                if serr.get("code") and serr.get("code") != "ok":
                    return UploadResult(platform="TikTok", success=False, error=serr.get("message", "Status check failed"))
                status = (sdata.get("data") or {}).get("status", "")
                if status == "PUBLISH_COMPLETE":
                    post_id = (sdata.get("data") or {}).get("publicaly_available_post_id") or (sdata.get("data") or {}).get("post_id")
                    username_slug = self._username or "user"
                    url = (
                        f"https://www.tiktok.com/@{username_slug}/video/{post_id}"
                        if post_id else None
                    )
                    return UploadResult(platform="TikTok", success=True, url=url, upload_id=str(publish_id))
                if status == "FAILED":
                    return UploadResult(platform="TikTok", success=False, error="TikTok processing failed")
                # PROCESSING_UPLOAD, PROCESSING_DOWNLOAD, etc. -> keep polling

            return UploadResult(platform="TikTok", success=False, error="Publish status timeout")

        except (AuthenticationError, QuotaExceededError, PlatformError, NetworkError):
            raise
        except Exception as e:
            logger.exception("TikTok upload failed: %s", e)
            return UploadResult(platform="TikTok", success=False, error=str(e))
