"""YouTube uploader using Data API v3 with OAuth2 and resumable uploads."""
import json
import os
import logging
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from uploaders.base import BaseUploader, VideoMetadata, UploadResult
from core.exceptions import AuthenticationError, QuotaExceededError, PlatformError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
RESUMABLE_THRESHOLD_MB = 5
CHUNK_SIZE_MB = 8


class YouTubeUploader(BaseUploader):
    """Upload videos to YouTube via Data API v3 with OAuth2 and optional resumable upload."""

    def __init__(self, credentials: dict[str, Any]) -> None:
        super().__init__(credentials)
        self._root = Path(__file__).resolve().parent.parent
        self._client_secret_path = credentials.get("client_secret_path") or "config/youtube_client_secret.json"
        self._token_path = credentials.get("token_path") or "config/youtube_token.json"
        if not os.path.isabs(self._client_secret_path):
            self._client_secret_path = str(self._root / self._client_secret_path)
        if not os.path.isabs(self._token_path):
            self._token_path = str(self._root / self._token_path)
        self._youtube = None

    def _get_credentials(self) -> Credentials:
        creds = None
        if os.path.exists(self._token_path):
            try:
                creds = Credentials.from_authorized_user_file(self._token_path, SCOPES)
            except Exception as e:
                logger.warning("Could not load token: %s", e)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None
            if not creds:
                if not os.path.exists(self._client_secret_path):
                    raise AuthenticationError(
                        "YouTube client secret not found. Run: social-uploader config --platform youtube"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self._client_secret_path, SCOPES)
                creds = flow.run_local_server(port=0)
            os.makedirs(os.path.dirname(self._token_path) or ".", exist_ok=True)
            with open(self._token_path, "w") as f:
                f.write(creds.to_json())
        return creds

    def _get_client(self):
        if self._youtube is None:
            creds = self._get_credentials()
            self._youtube = build("youtube", "v3", credentials=creds)
        return self._youtube

    def get_platform_name(self) -> str:
        return "YouTube"

    def validate_credentials(self) -> bool:
        try:
            client = self._get_client()
            client.channels().list(part="snippet", mine=True).execute()
            return True
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            try:
                err = json.loads(e.content.decode("utf-8")) if e.content else {}
            except Exception:
                err = {}
            errors = err.get("error", {}).get("errors", []) or []
            reason = (err.get("error", {}).get("message") or "").lower()
            for item in errors:
                err_reason = (item.get("reason") or "").lower()
                if err_reason == "quotaexceeded" or "quota" in reason:
                    raise QuotaExceededError("YouTube daily quota exceeded, retry scheduled for tomorrow")
                if err_reason == "invalidcredentials" or status == 401:
                    raise AuthenticationError("Run: social-uploader config --platform youtube")
                if "forbidden" in err_reason or status == 403:
                    raise PlatformError("Account not authorized, check OAuth scopes")
            raise AuthenticationError("Run: social-uploader config --platform youtube")
        except AuthenticationError:
            raise
        except QuotaExceededError:
            raise
        except PlatformError:
            raise
        except Exception as e:
            logger.exception("YouTube credential validation failed: %s", e)
            raise AuthenticationError("Run: social-uploader config --platform youtube")

    def upload(self, video_path: str, metadata: VideoMetadata) -> UploadResult:
        try:
            client = self._get_client()
            file_size = os.path.getsize(video_path)
            resumable = file_size > (RESUMABLE_THRESHOLD_MB * 1024 * 1024)
            media = MediaFileUpload(
                video_path,
                mimetype="video/*",
                resumable=resumable,
                chunksize=CHUNK_SIZE_MB * 1024 * 1024 if resumable else -1,
            )
            privacy = "private" if metadata.is_private else "public"
            if metadata.schedule_at:
                privacy = "private"  # schedule requires private then set time
            body = {
                "snippet": {
                    "title": metadata.title[:100],
                    "description": metadata.description or "",
                    "tags": metadata.tags[:500] if metadata.tags else [],
                    "categoryId": "22",
                },
                "status": {"privacyStatus": privacy},
            }
            request = client.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                status, response = request.next_chunk()
            video_id = response.get("id")
            if not video_id:
                return UploadResult(platform="YouTube", success=False, error="No video id in response")

            # Thumbnail upload
            if metadata.thumbnail_path and os.path.isfile(metadata.thumbnail_path):
                try:
                    client.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(metadata.thumbnail_path, mimetype="image/jpeg"),
                    ).execute()
                except HttpError as e:
                    logger.warning("Thumbnail upload failed: %s", e)

            url = f"https://youtu.be/{video_id}"
            return UploadResult(platform="YouTube", success=True, url=url, upload_id=video_id)

        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            try:
                err = json.loads(e.content.decode("utf-8")) if e.content else {}
            except Exception:
                err = {}
            errors = err.get("error", {}).get("errors", []) or []
            reason = (err.get("error", {}).get("message") or "").lower()
            for item in errors:
                err_reason = (item.get("reason") or "").lower()
                if err_reason == "quotaexceeded" or "quota" in reason:
                    raise QuotaExceededError("YouTube daily quota exceeded, retry scheduled for tomorrow")
                if err_reason == "invalidcredentials" or status == 401:
                    raise AuthenticationError("Run: social-uploader config --platform youtube")
                if "forbidden" in err_reason or status == 403:
                    raise PlatformError("Account not authorized, check OAuth scopes")
            return UploadResult(
                platform="YouTube",
                success=False,
                error=e.content.decode("utf-8") if e.content else str(e),
            )
        except (AuthenticationError, QuotaExceededError, PlatformError):
            raise
        except Exception as e:
            logger.exception("YouTube upload failed: %s", e)
            return UploadResult(platform="YouTube", success=False, error=str(e))
