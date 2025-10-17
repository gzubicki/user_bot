from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

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
async def test_select_relevant_quote_uses_random_choice_for_empty_query(monkeypatch):
    persona = SimpleNamespace(id=1)
    candidates = [_StubQuote(idx, f"Cytat {idx}") for idx in range(3)]

    async def fake_search(session, persona_arg, *, query, language_priority, limit):
        assert query == ""
        return candidates

    async def fake_random_quote(session, persona_arg):
        raise AssertionError("random_quote nie powinien zostać wywołany")

    captured: dict[str, list[_StubQuote]] = {}

    def fake_choice(options: list[_StubQuote]) -> _StubQuote:
        captured["options"] = options
        return options[-1]

    monkeypatch.setattr(quotes_service, "search_quotes_by_relevance", fake_search)
    monkeypatch.setattr(quotes_service, "random_quote", fake_random_quote)
    monkeypatch.setattr(quotes_service, "choice", fake_choice)

    selected = await quotes_service.select_relevant_quote(
        session=None,
        persona=persona,
        query="",
        language_priority=None,
    )

    assert selected is candidates[-1]
    assert captured["options"] == candidates


@pytest.mark.anyio
async def test_select_relevant_quote_prefers_best_match_for_query(monkeypatch):
    persona = SimpleNamespace(id=2)
    best = _StubQuote(1, "Najlepszy")
    others = [best, _StubQuote(2, "Inny"), _StubQuote(3, "Jeszcze inny")]

    async def fake_search(session, persona_arg, *, query, language_priority, limit):
        assert query == "szukaj"
        return others

    async def fake_random_quote(session, persona_arg):
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
