"""document-updater errors."""


class DocUpdaterError(Exception):
    pass


class NotFoundError(DocUpdaterError):
    pass


class OpRangeNotAvailableError(DocUpdaterError):
    """Requested ops are older than what's buffered in Redis (client must resync)."""


class VersionMismatchError(DocUpdaterError):
    pass


class OpAtFutureVersionError(DocUpdaterError):
    pass


class OpTooOldError(DocUpdaterError):
    pass


class DeleteMismatchError(DocUpdaterError):
    pass
