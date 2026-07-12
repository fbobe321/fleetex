"""Errors + ack serialization (port of Router._handleError + Errors.js)."""

from __future__ import annotations


class RealtimeError(Exception):
    pass


class CodedError(RealtimeError):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotAuthorizedError(RealtimeError):
    def __init__(self) -> None:
        super().__init__("not authorized")
        self.message = "not authorized"


class NotJoinedError(RealtimeError):
    def __init__(self) -> None:
        super().__init__("no project_id found on client")
        self.message = "no project_id found on client"


class ClientRequestedMissingOpsError(RealtimeError):
    message = "doc updater could not load requested ops"

    def __init__(self, status_code: int | None = None, first_version_in_redis=None) -> None:
        super().__init__(self.message)
        self.status_code = status_code
        self.first_version_in_redis = first_version_in_redis


class UpdateTooLargeError(RealtimeError):
    def __init__(self, update_size: int) -> None:
        super().__init__("update is too large")
        self.message = "update is too large"
        self.update_size = update_size


class NullBytesInOpError(RealtimeError):
    def __init__(self) -> None:
        super().__init__("null bytes found in op")


class DocumentUpdaterRequestFailedError(RealtimeError):
    def __init__(self, action: str, status_code: int) -> None:
        super().__init__(f"doc updater request failed: {action} ({status_code})")
        self.status_code = status_code


# Messages passed through to the client verbatim (Router._handleError allow-list).
_PASSTHROUGH = {
    "unexpected arguments",
    "no project_id found on client",
    "not authorized",
    "joinLeaveEpoch mismatch",
    "doc updater could not load requested ops",
    "cannot join multiple projects",
    "update is too large",
}


def serialize_error(error: Exception) -> dict:
    """Serialize an error for a socket ack (hides internal details)."""
    message = getattr(error, "message", None) or str(error)
    if isinstance(error, CodedError):
        out = {"message": message}
        if error.code is not None:
            out["code"] = error.code
        return out
    if message in _PASSTHROUGH:
        return {"message": message}
    return {"message": "Something went wrong in real-time service"}
