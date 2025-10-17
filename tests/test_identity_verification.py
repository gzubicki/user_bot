"""Testy sprawdzające weryfikację tożsamości cytatów."""

from bot_platform.models import MediaType, Persona, PersonaIdentity, Submission
from bot_platform.services.identities import (
    describe_identity,
    evaluate_submission_identity,
)


def _build_persona_with_identity(**identity_kwargs) -> tuple[Persona, PersonaIdentity]:
    persona = Persona(id=identity_kwargs.get("persona_id", 1), name="Test", language="pl")
    identity = PersonaIdentity(persona_id=persona.id, **identity_kwargs)
    identity.persona = persona
    persona.identities = [identity]
    return persona, identity


def _build_submission(persona: Persona, **submission_kwargs) -> Submission:
    base_kwargs = {
        "persona_id": persona.id,
        "persona": persona,
        "submitted_by_user_id": 111,
        "submitted_chat_id": 222,
        "media_type": MediaType.TEXT,
    }
    base_kwargs.update(submission_kwargs)
    return Submission(**base_kwargs)


def test_identity_matched_by_user_id() -> None:
    persona, _ = _build_persona_with_identity(telegram_user_id=111)
    submission = _build_submission(persona)

    result = evaluate_submission_identity(submission)

    assert result.matched is True
    assert set(result.matched_fields) == {"id"}


def test_identity_matched_by_username_case_insensitive() -> None:
    persona, _ = _build_persona_with_identity(telegram_username="@ExampleUser")
    submission = _build_submission(
        persona,
        submitted_by_username="exampleuser",
    )

    result = evaluate_submission_identity(submission)

    assert result.matched is True
    assert set(result.matched_fields) == {"alias"}


def test_identity_matched_by_display_name_trimmed() -> None:
    persona, _ = _build_persona_with_identity(display_name="Jan   Kowalski")
    submission = _build_submission(
        persona,
        submitted_by_name="  jan kowalski  ",
    )

    result = evaluate_submission_identity(submission)

    assert result.matched is True
    assert set(result.matched_fields) == {"name"}


def test_identity_partial_match_reported() -> None:
    persona, identity = _build_persona_with_identity(telegram_user_id=111, telegram_username="persona")
    submission = _build_submission(
        persona,
        submitted_by_username="inna",
    )

    result = evaluate_submission_identity(submission)

    assert result.matched is False
    assert result.descriptors
    assert result.partial_matches
    partial_descriptor, partial_fields = result.partial_matches[0]
    assert partial_descriptor.id == identity.id
    assert set(partial_fields) == {"id"}


def test_describe_identity_includes_all_fields() -> None:
    persona, identity = _build_persona_with_identity(
        telegram_user_id=555,
        telegram_username="alias",
        display_name="Persona Testowa",
    )

    descriptor_text = describe_identity(
        evaluate_submission_identity(
            _build_submission(persona, submitted_by_user_id=999)
        ).descriptors[0]
    )

    assert "ID 555" in descriptor_text
    assert "@alias" in descriptor_text
    assert "Persona Testowa" in descriptor_text


def test_identity_uses_quoted_author_metadata() -> None:
    persona, _ = _build_persona_with_identity(telegram_user_id=999)
    submission = _build_submission(
        persona,
        submitted_by_user_id=123,
        submitted_by_username="forwarder",
        quoted_user_id=999,
        quoted_username="OriginalUser",
        quoted_name="Jan Cytowany",
    )

    result = evaluate_submission_identity(submission)

    assert result.matched is True
    assert set(result.matched_fields) == {"id"}
    assert result.candidate_user_id == 999
    assert result.candidate_username == "originaluser"
    assert result.candidate_display_name == "jan cytowany"
