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
    from .helpers import (
        RemoteFile,
        RemoteStorage,
        UploadStatus,
        find_cleanup_candidates,
        is_cleanup_candidate,
    )

__all__ = [
    "RemoteFile",
    "RemoteStorage",
    "UploadStatus",
    "find_cleanup_candidates",
    "is_cleanup_candidate",
]
