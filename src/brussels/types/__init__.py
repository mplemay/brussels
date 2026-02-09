from .datetime_utc import DateTimeUTC
from .json_type import Json

__all__ = ["DateTimeUTC", "Json"]

try:
    from .remote_file import RemoteFile, RemoteFileMetadata, UploadStatus
except ModuleNotFoundError as exc:
    if exc.name != "pydantic":
        raise

    def __getattr__(name: str) -> object:
        if name in {"RemoteFile", "RemoteFileMetadata", "UploadStatus"}:
            msg = "brussels RemoteFile types require pydantic. Install with `pip install brussels[files]`."
            raise ModuleNotFoundError(msg)
        msg = f"module 'brussels.types' has no attribute '{name}'"
        raise AttributeError(msg)
else:
    __all__ += ["RemoteFile", "RemoteFileMetadata", "UploadStatus"]

try:
    from .encrypted_string import EncryptedString
except ModuleNotFoundError as exc:
    if exc.name != "cryptography":
        raise
else:
    __all__ += ["EncryptedString"]
