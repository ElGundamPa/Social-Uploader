"""Custom exception hierarchy for Social Uploader."""


class SocialUploaderError(Exception):
    """Base exception for all Social Uploader errors."""

    pass


class AuthenticationError(SocialUploaderError):
    """Invalid or expired credentials."""

    pass


class QuotaExceededError(SocialUploaderError):
    """Platform API quota exceeded."""

    pass


class VideoValidationError(SocialUploaderError):
    """Video file failed validation."""

    pass


class NetworkError(SocialUploaderError):
    """Network or connection error."""

    pass


class PlatformError(SocialUploaderError):
    """Platform-specific API or permission error."""

    pass
