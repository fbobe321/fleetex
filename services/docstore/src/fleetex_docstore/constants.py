"""Constants ported from docstore's settings.defaults."""

MAX_DOC_LENGTH = 2 * 1024 * 1024  # 2 MB (sum of line lengths); update -> 413 if exceeded
MAX_DELETED_DOCS = 2000
MAX_JSON_REQUEST_SIZE = 12 * 1024 * 1024
UN_ARCHIVE_BATCH_SIZE = 50
PARALLEL_ARCHIVE_JOBS = 5
ARCHIVING_LOCK_DURATION_MS = 60000
