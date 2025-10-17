from datetime import UTC, datetime, timedelta

from bot_platform.telegram.dispatcher import (
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
    signature = (42, "file123", "treść")
    _remember_chat_response(1001, None, signature, now=now)

    assert _is_duplicate_chat_response(1001, None, signature, now=now + timedelta(minutes=4))


def test_duplicate_response_allows_different_signature() -> None:
    now = datetime.now(UTC)
    first_signature = (101, None, "pierwsza")
    second_signature = (202, None, "druga")
    _remember_chat_response("1001", None, first_signature, now=now)

    assert not _is_duplicate_chat_response(1001, None, second_signature, now=now + timedelta(minutes=1))


def test_duplicate_response_expires_after_ttl() -> None:
    now = datetime.now(UTC)
    signature = (7, "plik", "tekst")
    _remember_chat_response(555, 888, signature, now=now)

    assert not _is_duplicate_chat_response(555, 888, signature, now=now + timedelta(minutes=6))
