from __future__ import annotations


class CaptureBackendInitializationError(RuntimeError):
    """Raised when a specific capture backend cannot be initialized."""

    def __init__(self, backend: str, reason: str) -> None:
        self.backend = backend
        self.reason = reason
        super().__init__(f"Capture backend '{backend}' initialization failed: {reason}")


class KMSGrabError(RuntimeError):
    """Raised when DRM/KMS capture fails."""
