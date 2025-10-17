from typing import Optional

from aiogram.enums import MessageEntityType

from bot_platform.telegram.dispatcher import normalize_entity_type, resolve_reply_target


def test_normalize_entity_type_from_enum():
    assert normalize_entity_type(MessageEntityType.MENTION) == "mention"
    assert normalize_entity_type(MessageEntityType.BOT_COMMAND) == "bot_command"
    assert normalize_entity_type(MessageEntityType.TEXT_MENTION) == "text_mention"


def test_normalize_entity_type_from_string():
    assert normalize_entity_type("mention") == "mention"
    assert normalize_entity_type("BOT_COMMAND") == "bot_command"


class _DummyEntityType:
    def __str__(self) -> str:
        return "MessageEntityType.TEXT_MENTION"


def test_normalize_entity_type_from_unknown_object():
    assert normalize_entity_type(_DummyEntityType()) == "messageentitytype.text_mention"


class _StubChat:
    def __init__(self, chat_id: int | None):
        self.id = chat_id


class _StubMessage:
    def __init__(self, chat_id: int | None, reply_to: Optional["_StubMessage"] = None):
        self.chat = _StubChat(chat_id)
        self.reply_to_message = reply_to


def test_resolve_reply_target_returns_none_without_reply():
    message = _StubMessage(chat_id=10)

    assert resolve_reply_target(message) is None


def test_resolve_reply_target_prefers_same_chat_reply():
    original = _StubMessage(chat_id=10)
    message = _StubMessage(chat_id=10, reply_to=original)

    assert resolve_reply_target(message) is original


def test_resolve_reply_target_ignores_different_chat():
    original = _StubMessage(chat_id=99)
    message = _StubMessage(chat_id=10, reply_to=original)

    assert resolve_reply_target(message) is None
