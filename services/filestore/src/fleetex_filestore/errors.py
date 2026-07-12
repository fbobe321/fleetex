"""Persistor/handler errors, mirroring @overleaf/object-persistor + filestore.

HTTP mapping (RequestLogger.errorHandler): NotFoundError -> 404 (empty), every
other error -> 500 with the exception message as plain text. There is no
400/403/416 in this service.
"""


class PersistorError(Exception):
    """Base for all persistor/handler errors (-> HTTP 500 unless NotFound)."""


class NotFoundError(PersistorError):
    """Object/key does not exist (-> HTTP 404). ENOENT/NoSuchKey/AccessDenied map here."""


class WriteError(PersistorError):
    pass


class ReadError(PersistorError):
    pass


class InvalidParametersError(PersistorError):
    pass


class AlreadyWrittenError(PersistorError):
    pass


class NotImplementedFsError(PersistorError):
    """FS backend can't honor an option (e.g. ifNoneMatch, autoGunzip)."""


class ConversionError(PersistorError):
    pass
