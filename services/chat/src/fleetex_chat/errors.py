"""Domain errors mirroring the Node service's MissingThreadError / MissingMessageError."""


class MissingThreadError(Exception):
    """The requested room/thread does not exist (and was not created)."""


class MissingMessageError(Exception):
    """The requested message does not exist in the room."""
