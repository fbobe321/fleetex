"""Domain errors and their HTTP mapping.

NotFoundError -> 404; DocModifiedError -> 409; DocVersionDecrementedError -> 409;
everything else (DocRevValueError, DocWithoutLinesError, Md5MismatchError, ...)
-> 500 (except unArchive which maps DocRevValueError -> 409).
"""


class DocstoreError(Exception):
    pass


class NotFoundError(DocstoreError):
    pass


class DocModifiedError(DocstoreError):
    pass


class DocVersionDecrementedError(DocstoreError):
    pass


class DocRevValueError(DocstoreError):
    pass


class DocWithoutLinesError(DocstoreError):
    pass


class Md5MismatchError(DocstoreError):
    pass


class WriteError(DocstoreError):
    pass
