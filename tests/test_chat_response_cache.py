from datetime import UTC, datetime, timedelta

from types import SimpleNamespace

from bot_platform.models import MediaType
from bot_platform.telegram.dispatcher import (
    _build_quote_signature,
    _clear_response_cache,
    _is_duplicate_chat_response,
    _remember_chat_response,
)


def setup_function() -> None:
    _clear_response_cache()


def teardown_function() -> None:
    _clear_response_cache()


def test_duplicate_response_detected_within_ttl() -> None:
    now = datetime.now(UTC)
    signature = ("file123", "treść", MediaType.TEXT.value)
    _remember_chat_response(1001, None, signature, now=now)

    assert _is_duplicate_chat_response(1001, None, signature, now=now + timedelta(minutes=4))


def test_duplicate_response_allows_different_signature() -> None:
    now = datetime.now(UTC)
    first_signature = (None, "pierwsza", MediaType.TEXT.value)
    second_signature = (None, "druga", MediaType.TEXT.value)
    _remember_chat_response("1001", None, first_signature, now=now)

    assert not _is_duplicate_chat_response(1001, None, second_signature, now=now + timedelta(minutes=1))


def test_duplicate_response_expires_after_ttl() -> None:
    now = datetime.now(UTC)
    signature = ("plik", "tekst", MediaType.AUDIO.value)
    _remember_chat_response(555, 888, signature, now=now)

    assert not _is_duplicate_chat_response(555, 888, signature, now=now + timedelta(minutes=6))


def test_duplicate_detection_reuses_normalized_text_signature() -> None:
    now = datetime.now(UTC)
    quote_a = SimpleNamespace(
        text_content=" To jest  TEST \n",
        file_id=None,
        media_type=MediaType.TEXT,
    )
    quote_b = SimpleNamespace(
        text_content="to JEST test",
        file_id=None,
        media_type=MediaType.TEXT,
    )

    first_signature = _build_quote_signature(quote_a)
    second_signature = _build_quote_signature(quote_b)

    _remember_chat_response(42, None, first_signature, now=now)

    assert _is_duplicate_chat_response(42, None, second_signature, now=now + timedelta(seconds=45))
