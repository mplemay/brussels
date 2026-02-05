from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class EncryptedString(TypeDecorator[str]):
    impl = Text()
    cache_ok = True

    def __init__(self, *, key: str | bytes) -> None:
        super().__init__()

        if isinstance(key, str):
            key_bytes = key.encode("utf-8")
        elif isinstance(key, bytes):
            key_bytes = key
        else:
            type_name = type(key).__name__
            msg = f"EncryptedString key must be str or bytes, got {type_name}."
            raise TypeError(msg)

        try:
            self._fernet = Fernet(key_bytes)
        except ValueError as exc:
            msg = "EncryptedString key must be a valid Fernet key."
            raise ValueError(msg) from exc

    def process_bind_param(self, value: str | None, _dialect: Any) -> str | None:  # type: ignore[override]  # noqa: ANN401
        if value is None:
            return None
        if not isinstance(value, str):
            type_name = type(value).__name__
            msg = f"EncryptedString requires str value, got {type_name}."
            raise TypeError(msg)
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def process_result_value(self, value: Any, _dialect: Any) -> str | None:  # type: ignore[override]  # noqa: ANN401
        if value is None:
            return None
        if not isinstance(value, str):
            type_name = type(value).__name__
            msg = f"EncryptedString expected str ciphertext from database, got {type_name}."
            raise TypeError(msg)

        try:
            decrypted = self._fernet.decrypt(value.encode("ascii"))
        except (InvalidToken, UnicodeEncodeError) as exc:
            msg = "EncryptedString failed to decrypt value. Ciphertext may be invalid or key may be wrong."
            raise ValueError(msg) from exc

        try:
            return decrypted.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = "EncryptedString decrypted value is not valid UTF-8 text."
            raise ValueError(msg) from exc
