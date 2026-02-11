_FILE_IMPORT_ERROR = (
    "brussels file support requires optional dependencies 'pydantic' and 'obstore'. "
    "Install with `pip install brussels[file]`."
)

try:
    from obstore.store import ObjectStore as _ObjectStoreDependencyCheck  # type: ignore[import-not-found]
    from pydantic import BaseModel as _PydanticDependencyCheck  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:
    raise ImportError(_FILE_IMPORT_ERROR) from exc
else:
    from .file import RemoteMetadata, UploadStatus
    from .helpers import cleanup_remote_fields, find_cleanup_candidates, is_cleanup_candidate
    from .remote_file import RemoteFile
    from .storage import RemoteStorage

__all__ = [
    "RemoteFile",
    "RemoteMetadata",
    "RemoteStorage",
    "UploadStatus",
    "cleanup_remote_fields",
    "find_cleanup_candidates",
    "is_cleanup_candidate",
]
