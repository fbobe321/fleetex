"""CLSI errors, each carrying the HTTP status and compile-status the Node original maps."""


class ClsiError(Exception):
    http_status = 500
    compile_status = "error"


class InvalidRequestError(ClsiError):
    http_status = 500  # Node routes RequestParser errors through the generic 500 handler
    compile_status = "error"


class NotFoundError(ClsiError):
    http_status = 404


class AlreadyCompilingError(ClsiError):
    http_status = 423
    compile_status = "compile-in-progress"


class TooManyCompileRequestsError(ClsiError):
    http_status = 503
    compile_status = "unavailable"


class FilesOutOfSyncError(ClsiError):
    http_status = 409
    compile_status = "conflict"


class CompileTerminatedError(ClsiError):
    http_status = 200
    compile_status = "terminated"


class CompileTimedOutError(ClsiError):
    http_status = 200
    compile_status = "timedout"
