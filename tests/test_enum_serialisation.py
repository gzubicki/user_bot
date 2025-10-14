import pytest
from sqlalchemy.dialects import postgresql

from bot_platform.models import (
    BotChatSubscription,
    ModerationAction,
    ModerationStatus,
    MediaType,
    Quote,
    Submission,
    SubscriptionPlan,
)


def _compile_params(statement):
    compiled = statement.compile(dialect=postgresql.dialect())
    return compiled.params


def test_submission_insert_uses_enum_values():
    stmt = Submission.__table__.insert().values(
        persona_id=1,
        submitted_by_user_id=11,
        submitted_chat_id=22,
        media_type=MediaType.TEXT,
        text_content="sample",
        status=ModerationStatus.PENDING,
    )
    params = _compile_params(stmt)
    assert params["media_type"] == "text"
    assert params["status"] == "pending"


def test_quote_insert_uses_enum_values():
    stmt = Quote.__table__.insert().values(
        persona_id=3,
        media_type=MediaType.IMAGE,
    )
    params = _compile_params(stmt)
    assert params["media_type"] == "image"


def test_moderation_action_insert_uses_enum_values():
    stmt = ModerationAction.__table__.insert().values(
        submission_id=5,
        action=ModerationStatus.APPROVED,
    )
    params = _compile_params(stmt)
    assert params["action"] == "approved"


def test_subscription_plan_insert_uses_enum_values():
    stmt = BotChatSubscription.__table__.insert().values(
        bot_id=7,
        chat_id=123456,
        plan=SubscriptionPlan.MONTHLY,
    )
    params = _compile_params(stmt)
    assert params["plan"] == "monthly"
