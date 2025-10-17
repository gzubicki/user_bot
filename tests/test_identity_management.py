"""Testy dotyczące zarządzania tożsamościami person."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from bot_platform.models import Persona, PersonaIdentity
from bot_platform.services import identities as identities_service


class _AsyncSessionAdapter:
    """Minimal adapter udający AsyncSession na potrzeby testów."""

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
    sync_session = SyncSession(engine, future=True)
    async_session = _AsyncSessionAdapter(sync_session)

    try:
        yield async_session
    finally:
        await async_session.close()
        engine.dispose()


def test_add_identity_creates_record() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester", language="pl")
            session.add(persona)
            await session.flush()

            identity = await identities_service.add_identity(
                session,
                persona,
                telegram_user_id=123456,
                admin_user_id=10,
                admin_chat_id=20,
            )
            await session.flush()

            assert identity.id is not None
            assert identity.telegram_user_id == 123456
            assert identity.added_by_user_id == 10
            assert identity.added_in_chat_id == 20
            assert identity.removed_at is None

    asyncio.run(scenario())


def test_add_identity_reactivates_removed() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester2", language="pl")
            session.add(persona)
            await session.flush()

            identity = await identities_service.add_identity(
                session,
                persona,
                telegram_username="@Example",
                admin_user_id=1,
                admin_chat_id=2,
            )
            await session.flush()

            await identities_service.remove_identity(
                session,
                identity,
                admin_user_id=3,
                admin_chat_id=4,
            )
            await session.flush()
            assert identity.removed_at is not None

            reactivated = await identities_service.add_identity(
                session,
                persona,
                telegram_username="@example",
                admin_user_id=5,
                admin_chat_id=6,
            )
            await session.flush()

            assert reactivated.id == identity.id
            assert reactivated.removed_at is None
            assert reactivated.telegram_username == "example"
            assert reactivated.added_by_user_id == 5
            assert reactivated.added_in_chat_id == 6

    asyncio.run(scenario())


def test_add_identity_updates_existing_fields() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester3", language="pl")
            session.add(persona)
            await session.flush()

            identity = await identities_service.add_identity(
                session,
                persona,
                telegram_username="alias",
                admin_user_id=1,
                admin_chat_id=1,
            )
            await session.flush()
            assert identity.telegram_user_id is None

            updated = await identities_service.add_identity(
                session,
                persona,
                telegram_username="alias",
                telegram_user_id=999,
                admin_user_id=2,
                admin_chat_id=3,
            )
            await session.flush()

            assert updated.id == identity.id
            assert updated.telegram_user_id == 999
            assert updated.added_by_user_id == 2

    asyncio.run(scenario())


def test_list_persona_identities_filters_removed() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester4", language="pl")
            session.add(persona)
            await session.flush()

            first = await identities_service.add_identity(
                session,
                persona,
                telegram_user_id=1,
                admin_user_id=1,
                admin_chat_id=1,
            )
            second = await identities_service.add_identity(
                session,
                persona,
                telegram_username="alias",
                admin_user_id=1,
                admin_chat_id=1,
            )
            await session.flush()

            await identities_service.remove_identity(
                session,
                second,
                admin_user_id=2,
                admin_chat_id=3,
            )
            await session.flush()

            active = await identities_service.list_persona_identities(session, persona)
            assert [item.id for item in active] == [first.id]

            all_records = await identities_service.list_persona_identities(
                session, persona, include_removed=True
            )
            assert [item.id for item in all_records] == [first.id, second.id]
            assert all_records[1].removed_at is not None

    asyncio.run(scenario())


def test_get_identity_by_id() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester5", language="pl")
            session.add(persona)
            await session.flush()

            identity = await identities_service.add_identity(
                session,
                persona,
                telegram_user_id=42,
                admin_user_id=1,
                admin_chat_id=1,
            )
            await session.flush()

            fetched = await identities_service.get_identity_by_id(session, identity.id)
            assert fetched is not None
            assert fetched.id == identity.id

            missing = await identities_service.get_identity_by_id(session, identity.id + 1)
            assert missing is None

    asyncio.run(scenario())


def test_add_identity_requires_identifier() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester6", language="pl")
            session.add(persona)
            await session.flush()

            with pytest.raises(ValueError):
                await identities_service.add_identity(
                    session,
                    persona,
                    admin_user_id=1,
                    admin_chat_id=1,
                )

    asyncio.run(scenario())
