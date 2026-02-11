_FILE_IMPORT_ERROR = (
    "brussels file support requires optional dependencies 'pydantic' and 'obstore'. "
    "Install with `pip install brussels[files]`."
)

try:
    from obstore.store import ObjectStore as _ObjectStoreDependencyCheck  # type: ignore[import-not-found]
    from pydantic import BaseModel as _PydanticDependencyCheck  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:
    raise ImportError(_FILE_IMPORT_ERROR) from exc
else:
    from .file import RemoteFile, UploadStatus
    from .helpers import find_cleanup_candidates, is_cleanup_candidate
    from .storage import RemoteFieldHandle, RemoteStorage, cleanup_remote_fields

__all__ = [
    "RemoteFieldHandle",
    "RemoteFile",
    "RemoteStorage",
    "UploadStatus",
    "cleanup_remote_fields",
    "find_cleanup_candidates",
    "is_cleanup_candidate",
]
