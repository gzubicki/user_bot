from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from bot_platform.models import MediaType, Persona, Quote, Submission
from bot_platform.services import quotes as quotes_service


class _AsyncSessionAdapter:
    """Minimalna imitacja AsyncSession do pracy z synchronicznym silnikiem."""

    def __init__(self, sync_session: SyncSession) -> None:
        self._sync_session = sync_session

    def add(self, instance) -> None:  # type: ignore[no-untyped-def]
        self._sync_session.add(instance)

    def add_all(self, instances) -> None:  # type: ignore[no-untyped-def]
        self._sync_session.add_all(instances)

    async def execute(self, statement):  # type: ignore[no-untyped-def]
        return self._sync_session.execute(statement)

    async def flush(self) -> None:
        self._sync_session.flush()

    async def close(self) -> None:
        self._sync_session.close()

    @property
    def bind(self):  # type: ignore[no-untyped-def]
        return self._sync_session.bind


@asynccontextmanager
async def _session_scope() -> _AsyncSessionAdapter:
    engine = create_engine("sqlite:///:memory:", future=True)
    Persona.__table__.create(engine)
    Submission.__table__.create(engine)
    Quote.__table__.create(engine)
    sync_session = SyncSession(engine, future=True)
    async_session = _AsyncSessionAdapter(sync_session)

    try:
        yield async_session
    finally:
        await async_session.close()
        engine.dispose()


def test_aggregate_quote_stats_groups_media_types() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tester", language="pl")
            session.add(persona)
            await session.flush()

            quotes = [
                Quote(
                    persona_id=persona.id,
                    media_type=MediaType.TEXT,
                    text_content="Ala ma kota",
                    language="pl",
                ),
                Quote(
                    persona_id=persona.id,
                    media_type=MediaType.IMAGE,
                    file_id="image-1",
                    language="pl",
                ),
                Quote(
                    persona_id=persona.id,
                    media_type=MediaType.AUDIO,
                    file_id="audio-1",
                    language="pl",
                ),
                Quote(
                    persona_id=persona.id,
                    media_type=MediaType.TEXT,
                    text_content="Inny cytat",
                    language="pl",
                ),
            ]
            session.add_all(quotes)
            await session.flush()

            stats = await quotes_service.aggregate_quote_stats(session)
            summary = stats.get(persona.id)
            assert summary is not None
            assert summary.total_quotes == 4
            assert summary.media_counts.get(MediaType.TEXT) == 2
            assert summary.media_counts.get(MediaType.IMAGE) == 1
            assert summary.media_counts.get(MediaType.AUDIO) == 1

    asyncio.run(scenario())


def test_list_all_quotes_with_personas_returns_ordered_quotes() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            alpha = Persona(name="Alpha", language="pl")
            beta = Persona(name="Beta", language="en")
            session.add_all([alpha, beta])
            await session.flush()

            alpha_quote = Quote(
                persona_id=alpha.id,
                media_type=MediaType.TEXT,
                text_content="Alpha tekst",
                language="pl",
            )
            beta_quote_first = Quote(
                persona_id=beta.id,
                media_type=MediaType.TEXT,
                text_content="Beta pierwszy",
                language="en",
            )
            beta_quote_second = Quote(
                persona_id=beta.id,
                media_type=MediaType.IMAGE,
                file_id="beta-obraz",
                language="en",
            )
            session.add_all([alpha_quote, beta_quote_first, beta_quote_second])
            await session.flush()

            quotes = await quotes_service.list_all_quotes_with_personas(session)

            assert [quote.persona_id for quote in quotes] == [alpha.id, beta.id, beta.id]
            assert [quote.persona.name for quote in quotes] == ["Alpha", "Beta", "Beta"]

    asyncio.run(scenario())


def test_find_quotes_matching_payload_prefers_file_id() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Matcher", language="pl")
            session.add(persona)
            await session.flush()

            text_quote = Quote(
                persona_id=persona.id,
                media_type=MediaType.TEXT,
                text_content="Ala ma kota",
                language="pl",
            )
            image_quote = Quote(
                persona_id=persona.id,
                media_type=MediaType.IMAGE,
                file_id="photo-123",
                text_content="Ilustracja",
                language="pl",
            )
            session.add_all([text_quote, image_quote])
            await session.flush()

            matches = await quotes_service.find_quotes_matching_payload(
                session,
                text_content="Ala ma kota",
                file_id="photo-123",
                limit=3,
            )

            assert len(matches) == 1
            match, origin = matches[0]
            assert match.id == image_quote.id
            assert origin == "file_id"

    asyncio.run(scenario())


def test_find_quotes_matching_payload_matches_normalized_text() -> None:
    async def scenario() -> None:
        async with _session_scope() as session:
            persona = Persona(name="Tekst", language="pl")
            session.add(persona)
            await session.flush()

            target = Quote(
                persona_id=persona.id,
                media_type=MediaType.TEXT,
                text_content="To jest\nwyjątkowy\tcytat",
                language="pl",
            )
            other = Quote(
                persona_id=persona.id,
                media_type=MediaType.TEXT,
                text_content="Inna treść",
                language="pl",
            )
            session.add_all([target, other])
            await session.flush()

            matches = await quotes_service.find_quotes_matching_payload(
                session,
                text_content="  to  jest wyjątkowy   cytat  ",
                file_id=None,
                limit=5,
            )

            assert len(matches) == 1
            match, origin = matches[0]
            assert match.id == target.id
            assert origin == "text"

    asyncio.run(scenario())
