"""Quote management helpers."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..logging_config import get_logger
from ..models import MediaType, Persona, Quote, Submission


logger = get_logger(__name__)


@dataclass(slots=True)
class PersonaQuoteStats:
    """Podsumowanie dostępnych cytatów dla persony."""

    persona_id: int
    total_quotes: int
    media_counts: dict[MediaType, int]

_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ']+", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)
_STOP_WORDS = {
    "a",
    "ale",
    "and",
    "czy",
    "dla",
    "do",
    "i",
    "is",
    "jest",
    "na",
    "nie",
    "o",
    "of",
    "or",
    "oraz",
    "się",
    "the",
    "to",
    "w",
    "z",
}


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens without punctuation."""

    tokens = [match.group(0).lower() for match in _WORD_RE.finditer(text)]
    filtered = [token for token in tokens if token]
    return filtered


def _filter_stop_words(tokens: Sequence[str]) -> list[str]:
    meaningful = [token for token in tokens if token not in _STOP_WORDS]
    return meaningful or list(tokens)


def _prepare_language_priority(language_priority: Optional[Sequence[str]]) -> list[str]:
    if not language_priority:
        return []

    prepared: list[str] = []
    seen: set[str] = set()
    for language in language_priority:
        if not language:
            continue
        normalized = language.lower()
        if "-" in normalized:
            normalized = normalized.split("-", 1)[0]
        if normalized not in seen:
            seen.add(normalized)
            prepared.append(normalized)
    return prepared


def _normalize_quote_text(text: str) -> str:
    """Return a lowercase string with collapsed whitespace suitable for comparisons."""

    if not text:
        return ""

    collapsed = _WHITESPACE_RE.sub(" ", text)
    normalized = collapsed.strip().casefold()
    return normalized


def _score_tokens(query_tokens: Sequence[str], candidate_tokens: Sequence[str]) -> float:
    """Compute a relevance score between two token lists."""

    if not query_tokens or not candidate_tokens:
        return 0.0

    query_tokens = _filter_stop_words(query_tokens)
    candidate_tokens = _filter_stop_words(candidate_tokens)

    query_counter = Counter(query_tokens)
    candidate_counter = Counter(candidate_tokens)

    common_weight = sum(
        min(candidate_counter[token], query_counter[token]) for token in query_counter
    )
    coverage = common_weight / len(query_tokens)

    unique_query = set(query_tokens)
    unique_candidate = set(candidate_tokens)
    jaccard_denominator = len(unique_query | unique_candidate)
    jaccard = 0.0 if jaccard_denominator == 0 else len(unique_query & unique_candidate) / jaccard_denominator

    sequence_ratio = SequenceMatcher(
        None, " ".join(candidate_tokens), " ".join(query_tokens)
    ).ratio()

    length_sum = len(candidate_tokens) + len(query_tokens)
    if length_sum == 0:
        length_penalty = 0.0
    else:
        length_penalty = 1 - abs(len(candidate_tokens) - len(query_tokens)) / length_sum
        length_penalty = max(length_penalty, 0.0)

    score = 0.55 * coverage + 0.25 * jaccard + 0.15 * sequence_ratio + 0.05 * length_penalty
    return score


async def count_quotes(session: AsyncSession, persona: Persona) -> int:
    result = await session.execute(
        select(func.count(Quote.id)).where(Quote.persona_id == persona.id)
    )
    total = int(result.scalar_one())
    logger.debug("Persona ID=%s posiada %s cytatów", persona.id, total)
    return total


def _prepare_media_types(media_types: Optional[Sequence[MediaType]]) -> tuple[MediaType, ...]:
    if not media_types:
        return tuple()

    prepared: list[MediaType] = []
    seen: set[MediaType] = set()
    for media_type in media_types:
        try:
            normalized = (
                media_type
                if isinstance(media_type, MediaType)
                else MediaType(str(media_type))
            )
        except ValueError:
            logger.debug("Ignoruję nieobsługiwany typ nośnika: %s", media_type)
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        prepared.append(normalized)
    return tuple(prepared)


async def random_quote(
    session: AsyncSession,
    persona: Persona,
    *,
    language_priority: Optional[Sequence[str]] = None,
    media_types: Optional[Sequence[MediaType]] = None,
) -> Optional[Quote]:
    prepared_languages = _prepare_language_priority(language_priority)
    prepared_media_types = _prepare_media_types(media_types)

    stmt = select(Quote).where(Quote.persona_id == persona.id)
    if prepared_languages:
        stmt = stmt.where(Quote.language.in_([*prepared_languages, "auto"]))
    if prepared_media_types:
        stmt = stmt.where(Quote.media_type.in_(prepared_media_types))
    stmt = stmt.order_by(func.random()).limit(1)
    result = await session.execute(stmt)
    quote = result.scalars().first()
    if quote is None:
        if prepared_languages or prepared_media_types:
            logger.debug(
                "Brak cytatów dla persony ID=%s spełniających preferencje językowe: %s i typów: %s",
                persona.id,
                ", ".join(prepared_languages) if prepared_languages else "—",
                ", ".join(mt.value for mt in prepared_media_types) if prepared_media_types else "—",
            )
        else:
            logger.warning("Brak cytatów dla persony ID=%s", persona.id)
    else:
        details: list[str] = []
        if prepared_languages:
            details.append(", ".join(prepared_languages))
        if prepared_media_types:
            details.append(", ".join(mt.value for mt in prepared_media_types))
        if details:
            logger.debug(
                "Wylosowano cytat ID=%s dla persony ID=%s (preferencje: %s)",
                quote.id,
                persona.id,
                "; ".join(details),
            )
        else:
            logger.debug("Wylosowano cytat ID=%s dla persony ID=%s", quote.id, persona.id)
    return quote


async def get_quote_by_id(session: AsyncSession, quote_id: int) -> Optional[Quote]:
    stmt = select(Quote).where(Quote.id == quote_id)
    result = await session.execute(stmt)
    quote = result.scalars().first()
    if quote is None:
        logger.warning("Nie znaleziono cytatu o ID=%s", quote_id)
    else:
        logger.debug(
            "Odczytano cytat ID=%s dla persony ID=%s", quote.id, quote.persona_id
        )
    return quote


async def delete_quote(
    session: AsyncSession,
    quote: Quote,
    *,
    removed_by_user_id: Optional[int] = None,
    removed_in_chat_id: Optional[int] = None,
) -> None:
    quote_id = quote.id
    persona_id = quote.persona_id
    await session.delete(quote)
    await session.flush()
    logger.warning(
        "Usunięto cytat ID=%s (persona_id=%s, removed_by=%s, chat_id=%s)",
        quote_id,
        persona_id,
        removed_by_user_id,
        removed_in_chat_id,
    )


def _normalized_quote_text_expression() -> Any:
    text_column = func.coalesce(Quote.text_content, "")
    trimmed = func.trim(text_column)
    collapsed = func.regexp_replace(trimmed, r"\s+", " ", "g")
    lowered = func.lower(collapsed)
    return lowered


async def find_exact_duplicate(
    session: AsyncSession,
    *,
    persona_id: int,
    media_type: MediaType | str,
    text_content: Optional[str] = None,
    file_id: Optional[str] = None,
    file_hash: Optional[bytes] = None,
) -> Optional[tuple[Quote, str]]:
    """Return an existing quote with matching payload and the match origin."""

    media_value = media_type.value if isinstance(media_type, MediaType) else str(media_type)

    async def _fetch_with_conditions(*extra_conditions: Any) -> Optional[Quote]:
        stmt = (
            select(Quote)
            .where(Quote.persona_id == persona_id, Quote.media_type == media_value, *extra_conditions)
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    if file_hash:
        duplicate = await _fetch_with_conditions(Quote.file_hash == file_hash)
        if duplicate is not None:
            logger.debug(
                "Wykryto duplikat cytatu na podstawie hash pliku (persona_id=%s, quote_id=%s)",
                persona_id,
                duplicate.id,
            )
            return duplicate, "file_hash"

    if file_id:
        duplicate = await _fetch_with_conditions(Quote.file_id == file_id)
        if duplicate is not None:
            logger.debug(
                "Wykryto duplikat cytatu na podstawie identyfikatora pliku (persona_id=%s, quote_id=%s)",
                persona_id,
                duplicate.id,
            )
            return duplicate, "file_id"

    normalized_text = _normalize_quote_text(text_content or "")
    if normalized_text:
        normalized_expression = _normalized_quote_text_expression()
        duplicate = await _fetch_with_conditions(normalized_expression == normalized_text)
        if duplicate is not None:
            logger.debug(
                "Wykryto duplikat cytatu na podstawie treści (persona_id=%s, quote_id=%s)",
                persona_id,
                duplicate.id,
            )
            return duplicate, "text"

    return None


async def find_quotes_by_language(
    session: AsyncSession,
    persona: Persona,
    *,
    language: Optional[str] = None,
    limit: int = 5,
) -> list[Quote]:
    stmt = select(Quote).where(Quote.persona_id == persona.id)
    if language:
        stmt = stmt.where(Quote.language == language)
    stmt = stmt.order_by(Quote.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    quotes = list(result.scalars().all())
    logger.info(
        "Pobrano %s cytatów dla persony ID=%s (język=%s)",
        len(quotes),
        persona.id,
        language or "*",
    )
    return quotes


async def search_quotes_by_relevance(
    session: AsyncSession,
    persona: Persona,
    *,
    query: str,
    language_priority: Optional[Sequence[str]] = None,
    limit: int = 5,
    sample_size: int = 50,
) -> list[Quote]:
    """Return quotes ordered by lexical relevance to the provided query."""

    if limit <= 0:
        return []

    normalized_query = (query or "").strip()
    prepared_languages = _prepare_language_priority(language_priority)

    stmt = select(Quote).where(Quote.persona_id == persona.id)
    if prepared_languages:
        stmt = stmt.where(Quote.language.in_([*prepared_languages, "auto"]))

    fetch_limit = max(limit * 6, sample_size)
    stmt = stmt.order_by(Quote.created_at.desc()).limit(fetch_limit)
    result = await session.execute(stmt)
    candidates = list(result.scalars().all())

    if not normalized_query:
        logger.debug("Zapytanie puste – zwracam %s najnowszych cytatów", limit)
        return candidates[:limit]

    query_tokens = _tokenize(normalized_query)
    if not query_tokens:
        logger.debug("Nie udało się ztokenizować zapytania – zwracam %s cytatów", limit)
        return candidates[:limit]

    ranked: list[tuple[float, Quote]] = []
    for quote in candidates:
        content = (quote.text_content or "").strip()
        if not content:
            continue
        candidate_tokens = _tokenize(content)
        if not candidate_tokens:
            continue
        score = _score_tokens(query_tokens, candidate_tokens)
        if prepared_languages and quote.language not in {"auto", *prepared_languages}:
            score *= 0.85
        ranked.append((score, quote))

    ranked.sort(key=lambda item: item[0], reverse=True)

    if not ranked:
        logger.debug("Brak dopasowań – zwracam %s kandydatów", limit)
        return candidates[:limit]

    meaningful = [quote for score, quote in ranked if score > 0]
    if meaningful:
        logger.info(
            "Zwracam %s cytatów najbardziej pasujących do zapytania '%s'",
            min(len(meaningful), limit),
            normalized_query,
        )
        return meaningful[:limit]
    logger.debug("Brak cytatów o dodatnim wyniku – zwracam %s najlepszych", limit)
    return [quote for _, quote in ranked[:limit]]


async def select_relevant_quote(
    session: AsyncSession,
    persona: Persona,
    *,
    query: str,
    language_priority: Optional[Sequence[str]] = None,
) -> Optional[Quote]:
    normalized_query = (query or "").strip()
    if not normalized_query:
        random_match = await random_quote(
            session,
            persona,
            language_priority=language_priority,
        )
        if random_match is None and language_priority:
            random_match = await random_quote(
                session,
                persona,
                language_priority=None,
            )
        if random_match is not None:
            logger.info(
                "Wybrano losowy cytat ID=%s w odpowiedzi na puste zapytanie",
                random_match.id,
            )
            return random_match

    candidates = await search_quotes_by_relevance(
        session,
        persona,
        query=query,
        language_priority=language_priority,
        limit=5,
    )

    if candidates:
        if normalized_query:
            selected = candidates[0]
            logger.info(
                "Wybrano cytat ID=%s jako najlepsze dopasowanie do zapytania '%s'",
                selected.id,
                normalized_query,
            )
            return selected

    fallback = await random_quote(session, persona, language_priority=language_priority)
    if fallback is None and language_priority:
        fallback = await random_quote(
            session,
            persona,
            language_priority=None,
        )
    if fallback is not None:
        logger.info(
            "Brak dopasowań – zwracam losowy cytat ID=%s dla persony ID=%s",
            fallback.id,
            persona.id,
        )
    else:
        logger.warning(
            "Brak cytatów do zaprezentowania dla persony ID=%s", persona.id
        )
    return fallback
async def create_quote_from_submission(
    session: AsyncSession,
    submission: Submission,
    *,
    override_language: Optional[str] = None,
) -> Quote:
    """Create a quote from a moderated submission."""

    language = override_language
    persona = submission.__dict__.get("persona")
    if language is None and persona is not None:
        language = persona.language
    if not language:
        language = "auto"

    quote = Quote(
        persona_id=submission.persona_id,
        media_type=(
            submission.media_type.value
            if isinstance(submission.media_type, MediaType)
            else submission.media_type
        ),
        text_content=submission.text_content,
        file_id=submission.file_id,
        file_hash=submission.file_hash,
        language=language,
        created_at=datetime.utcnow(),
        source_submission_id=submission.id,
    )
    session.add(quote)
    await session.flush()
    logger.info(
        "Dodano cytat ID=%s na podstawie zgłoszenia ID=%s",
        quote.id,
        submission.id,
    )
    return quote


async def find_quotes_matching_payload(
    session: AsyncSession,
    *,
    text_content: Optional[str] = None,
    file_id: Optional[str] = None,
    limit: int = 5,
) -> list[tuple[Quote, str]]:
    """Wyszukaj cytaty dopasowane do treści lub identyfikatora pliku."""

    max_results = max(int(limit or 0), 0)
    if max_results <= 0:
        return []

    async def _run_query(condition: Any, match_type: str) -> list[tuple[Quote, str]]:
        stmt = (
            select(Quote)
            .options(selectinload(Quote.persona))
            .where(condition)
            .order_by(Quote.id.asc())
            .limit(max_results)
        )
        result = await session.execute(stmt)
        quotes = list(result.scalars().all())
        return [(quote, match_type) for quote in quotes]

    if file_id:
        cleaned_file_id = file_id.strip()
        if cleaned_file_id:
            file_matches = await _run_query(Quote.file_id == cleaned_file_id, "file_id")
            if file_matches:
                logger.debug(
                    "Znaleziono %s cytatów na podstawie identyfikatora pliku",
                    len(file_matches),
                )
                return file_matches

    if text_content:
        normalized = _normalize_quote_text(text_content)
        if normalized:
            normalized_expression = _normalized_quote_text_expression()
            try:
                text_matches = await _run_query(normalized_expression == normalized, "text")
            except OperationalError:
                logger.debug(
                    "Baza nie obsługuje regexp_replace – filtrujemy dopasowania tekstowe w pamięci."
                )
                stmt = (
                    select(Quote)
                    .options(selectinload(Quote.persona))
                    .where(Quote.text_content.is_not(None))
                )
                result = await session.execute(stmt)
                text_candidates = [
                    quote
                    for quote in result.scalars().all()
                    if _normalize_quote_text(quote.text_content or "") == normalized
                ][:max_results]
                text_matches = [(quote, "text") for quote in text_candidates]
            if text_matches:
                logger.debug(
                    "Znaleziono %s cytatów na podstawie treści tekstowej",
                    len(text_matches),
                )
                return text_matches

    logger.debug("Brak dopasowań cytatów dla przekazanej treści/plików")
    return []


async def aggregate_quote_stats(session: AsyncSession) -> dict[int, PersonaQuoteStats]:
    """Policz cytaty według persony i rodzaju zasobu."""

    stmt = (
        select(Quote.persona_id, Quote.media_type, func.count(Quote.id))
        .group_by(Quote.persona_id, Quote.media_type)
        .order_by(Quote.persona_id.asc())
    )
    result = await session.execute(stmt)

    stats: dict[int, PersonaQuoteStats] = {}
    for persona_id, raw_media_type, count in result.all():
        if persona_id is None:
            continue
        summary = stats.get(persona_id)
        if summary is None:
            summary = PersonaQuoteStats(
                persona_id=persona_id,
                total_quotes=0,
                media_counts={},
            )
            stats[persona_id] = summary

        if isinstance(raw_media_type, MediaType):
            media_type = raw_media_type
        else:
            media_type = MediaType(str(raw_media_type))

        summary.media_counts[media_type] = int(count or 0)
        summary.total_quotes += int(count or 0)

    logger.info("Zebrano statystyki cytatów dla %s person", len(stats))
    return stats


async def list_all_quotes_with_personas(session: AsyncSession) -> list[Quote]:
    """Zwróć wszystkie cytaty wraz z powiązanymi personami."""

    stmt = (
        select(Quote)
        .options(selectinload(Quote.persona))
        .order_by(Quote.persona_id.asc(), Quote.id.asc())
    )
    result = await session.execute(stmt)
    quotes = list(result.scalars().all())
    logger.info("Pobrano %s cytatów z przypisanymi personami", len(quotes))
    return quotes


__all__ = [
    "count_quotes",
    "random_quote",
    "get_quote_by_id",
    "delete_quote",
    "find_exact_duplicate",
    "find_quotes_matching_payload",
    "find_quotes_by_language",
    "search_quotes_by_relevance",
    "select_relevant_quote",
    "create_quote_from_submission",
    "aggregate_quote_stats",
    "list_all_quotes_with_personas",
]
