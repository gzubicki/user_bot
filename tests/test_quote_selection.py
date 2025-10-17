from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional, Sequence

import pytest

from bot_platform.models import MediaType
from bot_platform.services import quotes as quotes_service


@dataclass
class _StubQuote:
    id: int
    text_content: str
    media_type: MediaType = MediaType.TEXT
    file_id: str | None = None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_select_relevant_quote_uses_random_quote_for_empty_query(monkeypatch):
    persona = SimpleNamespace(id=1)
    expected = _StubQuote(42, "Losowy cytat")

    async def fake_search(*args, **kwargs):
        raise AssertionError("search_quotes_by_relevance nie powinno być wywołane")

    async def fake_random_quote(session, persona_arg, *, language_priority):
        assert session is None
        assert persona_arg is persona
        assert language_priority is None
        return expected

    monkeypatch.setattr(quotes_service, "search_quotes_by_relevance", fake_search)
    monkeypatch.setattr(quotes_service, "random_quote", fake_random_quote)

    selected = await quotes_service.select_relevant_quote(
        session=None,
        persona=persona,
        query="",
        language_priority=None,
    )

    assert selected is expected


@pytest.mark.anyio
async def test_select_relevant_quote_falls_back_to_unfiltered_random(monkeypatch):
    persona = SimpleNamespace(id=5)
    attempts: list[Optional[Sequence[str]]] = []

    async def fake_search(*args, **kwargs):
        raise AssertionError("search_quotes_by_relevance nie powinno być wywołane")

    async def fake_random_quote(session, persona_arg, *, language_priority):
        attempts.append(language_priority)
        if language_priority:
            return None
        return _StubQuote(99, "Fallback")

    monkeypatch.setattr(quotes_service, "search_quotes_by_relevance", fake_search)
    monkeypatch.setattr(quotes_service, "random_quote", fake_random_quote)

    selected = await quotes_service.select_relevant_quote(
        session=None,
        persona=persona,
        query="",
        language_priority=["pl", "en"],
    )

    assert selected.id == 99
    assert attempts == [["pl", "en"], None]


@pytest.mark.anyio
async def test_select_relevant_quote_prefers_best_match_for_query(monkeypatch):
    persona = SimpleNamespace(id=2)
    best = _StubQuote(1, "Najlepszy")
    others = [best, _StubQuote(2, "Inny"), _StubQuote(3, "Jeszcze inny")]

    async def fake_search(session, persona_arg, *, query, language_priority, limit):
        assert query == "szukaj"
        return others

    async def fake_random_quote(session, persona_arg, *, language_priority):
        assert language_priority is None
        raise AssertionError("random_quote nie powinien zostać wywołany")

    monkeypatch.setattr(quotes_service, "search_quotes_by_relevance", fake_search)
    monkeypatch.setattr(quotes_service, "random_quote", fake_random_quote)

    selected = await quotes_service.select_relevant_quote(
        session=None,
        persona=persona,
        query="szukaj",
        language_priority=None,
    )

    assert selected is best
