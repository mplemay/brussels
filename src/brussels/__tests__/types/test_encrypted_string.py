from __future__ import annotations

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import Base

try:
    from brussels.types import EncryptedString
except ImportError:
    pytest.skip("cryptography optional dependency not installed", allow_module_level=True)

MODEL_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


class EncryptedRecord(Base):
    __tablename__ = "encrypted_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    secret: Mapped[str] = mapped_column(EncryptedString(key=MODEL_KEY))


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    try:
        yield engine
    finally:
        engine.dispose()


def test_constructor_accepts_string_key() -> None:
    key = MODEL_KEY
    encrypted = EncryptedString(key=key)

    ciphertext = encrypted.process_bind_param("value", None)
    assert ciphertext is not None
    assert ciphertext != "value"


def test_constructor_accepts_bytes_key() -> None:
    key = MODEL_KEY.encode("ascii")
    encrypted = EncryptedString(key=key)

    ciphertext = encrypted.process_bind_param("value", None)
    assert ciphertext is not None
    assert ciphertext != "value"


def test_constructor_rejects_non_key_type() -> None:
    with pytest.raises(TypeError, match="key must be str or bytes"):
        EncryptedString(key=123)  # type: ignore[arg-type]


def test_constructor_rejects_malformed_key() -> None:
    with pytest.raises(ValueError, match="valid Fernet key"):
        EncryptedString(key="bad-key")


def test_process_bind_param_returns_none() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)
    assert encrypted.process_bind_param(None, None) is None


def test_process_bind_param_rejects_non_str_value() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)
    with pytest.raises(TypeError, match="requires str value"):
        encrypted.process_bind_param(1, None)  # type: ignore[arg-type]


def test_process_bind_param_encrypts_plaintext() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)

    ciphertext = encrypted.process_bind_param("plain-secret", None)
    assert ciphertext is not None
    assert ciphertext != "plain-secret"


def test_process_bind_param_is_nondeterministic_for_same_plaintext() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)

    ciphertext_1 = encrypted.process_bind_param("same-secret", None)
    ciphertext_2 = encrypted.process_bind_param("same-secret", None)

    assert ciphertext_1 is not None
    assert ciphertext_2 is not None
    assert ciphertext_1 != ciphertext_2


def test_process_result_value_returns_none() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)
    assert encrypted.process_result_value(None, None) is None


def test_process_result_value_decrypts_to_plaintext() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)
    ciphertext = encrypted.process_bind_param("top-secret", None)

    assert ciphertext is not None
    plaintext = encrypted.process_result_value(ciphertext, None)
    assert plaintext == "top-secret"


def test_process_result_value_raises_with_wrong_key() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)
    wrong_key = EncryptedString(key="FC-c_21-lM4W6v8kWngjNjVj8T0ohgYVgSS_6G1iD2M=")

    ciphertext = encrypted.process_bind_param("top-secret", None)
    assert ciphertext is not None

    with pytest.raises(ValueError, match="failed to decrypt value"):
        wrong_key.process_result_value(ciphertext, None)


def test_process_result_value_raises_on_malformed_ciphertext() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)
    with pytest.raises(ValueError, match="failed to decrypt value"):
        encrypted.process_result_value("not-a-valid-token", None)


def test_type_decorator_bind_processor() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)
    processor = encrypted.bind_processor(sqlite_dialect())

    assert processor is not None
    ciphertext = processor("processor-secret")
    assert ciphertext != "processor-secret"


def test_type_decorator_result_processor() -> None:
    encrypted = EncryptedString(key=MODEL_KEY)
    bind_processor = encrypted.bind_processor(sqlite_dialect())
    result_processor = encrypted.result_processor(sqlite_dialect(), None)

    assert bind_processor is not None
    assert result_processor is not None

    ciphertext = bind_processor("processor-secret")
    plaintext = result_processor(ciphertext)
    assert plaintext == "processor-secret"


def test_orm_round_trip_stores_ciphertext_at_rest(engine: Engine) -> None:
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        plaintext = "db" + "-value"
        record = EncryptedRecord(secret=plaintext)
        session.add(record)
        session.commit()
        session.refresh(record)

        assert record.secret == plaintext

        raw_value = session.execute(
            text("SELECT secret FROM encrypted_records WHERE id = :id"),
            {"id": record.id},
        ).scalar_one()
        assert isinstance(raw_value, str)
        assert raw_value != plaintext
