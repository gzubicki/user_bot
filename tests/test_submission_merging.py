from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from bot_platform.models import (
    MediaType,
    ModerationStatus,
    Persona,
    PersonaIdentity,
    Submission,
)
from bot_platform.services import moderation as moderation_service


class _AsyncSessionAdapter:
    """Minimalny adapter udający AsyncSession na potrzeby testów."""

    def __init__(self, sync_session: SyncSession) -> None:
        self._sync_session = sync_session

    def add(self, instance) -> None:  # type: ignore[no-untyped-def]
        self._sync_session.add(instance)

    async def execute(self, statement):  # type: ignore[no-untyped-def]
        return self._sync_session.execute(statement)

    async def flush(self) -> None:
        self._sync_session.flush()

    async def refresh(self, instance) -> None:  # type: ignore[no-untyped-def]
        self._sync_session.refresh(instance)

    async def commit(self) -> None:
        self._sync_session.commit()

    async def close(self) -> None:
        self._sync_session.close()

    @property
    def bind(self):  # type: ignore[no-untyped-def]
        return self._sync_session.bind


@asynccontextmanager
async def _session_scope() -> _AsyncSessionAdapter:
    engine = create_engine("sqlite:///:memory:", future=True)
    Persona.__table__.create(engine)
    PersonaIdentity.__table__.create(engine)
    Submission.__table__.create(engine)
    sync_session = SyncSession(engine, future=True)
    async_session = _AsyncSessionAdapter(sync_session)

    try:
        yield async_session
    finally:
        await async_session.close()
        engine.dispose()


def _create_submission(
    persona: Persona,
    *,
    user_id: int,
    chat_id: int,
    created_at: datetime,
    text: str,
    media_type: MediaType = MediaType.TEXT,
    file_id: str | None = None,
) -> Submission:
    return Submission(
        persona_id=persona.id,
        submitted_by_user_id=user_id,
        submitted_chat_id=chat_id,
        submitted_by_username=None,
        submitted_by_name=None,
        quoted_user_id=None,
        quoted_username=None,
        quoted_name=None,
        media_type=media_type,
        text_content=text,
        file_id=file_id,
        status=ModerationStatus.PENDING,
        created_at=created_at,
    )


def test_find_recent_text_submission_prefers_latest() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester", language="pl")
            session.add(persona)
            await session.flush()

            now = datetime.utcnow()
            older = _create_submission(
                persona,
                user_id=10,
                chat_id=20,
                created_at=now - timedelta(seconds=30),
                text="Pierwsza wiadomość",
            )
            newer = _create_submission(
                persona,
                user_id=10,
                chat_id=20,
                created_at=now - timedelta(seconds=5),
                text="Druga wiadomość",
            )
            session.add(older)
            session.add(newer)
            await session.flush()

            found = await moderation_service.find_recent_text_submission(
                session,
                persona_id=persona.id,
                submitted_by_user_id=10,
                submitted_chat_id=20,
                max_age=timedelta(seconds=60),
            )

            assert found is not None
            assert found.id == newer.id

    asyncio.run(scenario())


def test_find_recent_text_submission_respects_time_window() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester 2", language="pl")
            session.add(persona)
            await session.flush()

            now = datetime.utcnow()
            stale = _create_submission(
                persona,
                user_id=30,
                chat_id=40,
                created_at=now - timedelta(seconds=10),
                text="Stara wiadomość",
            )
            session.add(stale)
            await session.flush()

            found = await moderation_service.find_recent_text_submission(
                session,
                persona_id=persona.id,
                submitted_by_user_id=30,
                submitted_chat_id=40,
                max_age=timedelta(seconds=5),
            )

            assert found is None

    asyncio.run(scenario())


def test_find_recent_text_submission_ignores_non_text() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester 3", language="pl")
            session.add(persona)
            await session.flush()

            now = datetime.utcnow()
            image_submission = _create_submission(
                persona,
                user_id=50,
                chat_id=60,
                created_at=now - timedelta(seconds=2),
                text="obraz",
                media_type=MediaType.IMAGE,
                file_id="file-123",
            )
            session.add(image_submission)
            await session.flush()

            found = await moderation_service.find_recent_text_submission(
                session,
                persona_id=persona.id,
                submitted_by_user_id=50,
                submitted_chat_id=60,
                max_age=timedelta(seconds=30),
            )

            assert found is None

    asyncio.run(scenario())
