"""Aiogram dispatcher factory and admin chat handlers."""
from __future__ import annotations

import re
import html
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramUnauthorizedError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import get_settings
from ..database import get_session
from ..models import MediaType, ModerationStatus, Submission
from ..services import bots as bots_service
from ..models import MediaType, Quote
from ..services import personas as personas_service
from ..services import quotes as quotes_service
from ..services import moderation as moderation_service
from .states import AddBotStates, EditBotStates, ModerationStates


@dataclass(slots=True)
class DispatcherBundle:
    dispatcher: Dispatcher
    bot: Bot
    moderator_chat_id: int
    persona_id: Optional[int]
    bot_id: Optional[int] = None
    display_name: Optional[str] = None


def _main_menu_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Dodaj bota", callback_data="menu:add_bot")
    builder.button(text="📋 Lista botów", callback_data="menu:list_bots")
    builder.button(text="✏️ Edytuj bota", callback_data="menu:edit_bot")
    builder.button(text="🗳 Moderacja", callback_data="menu:moderation")
    builder.button(text="🔁 Odśwież tokeny", callback_data="menu:refresh_tokens")
    builder.adjust(1)
    return builder


def build_dispatcher(
    token: str,
    *,
    bot_id: Optional[int] = None,
    display_name: Optional[str] = None,
    persona_id: Optional[int] = None,
) -> DispatcherBundle:
    """Create a dispatcher bundle for a specific bot token."""

    settings = get_settings()
    admin_chat_id = settings.admin_chat_id
    moderator_chat_id = settings.moderation.moderator_chat_id
    resolved_display_name = display_name or token.split(":", 1)[0]

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()

    def _is_admin_chat_id(chat_id: Optional[int]) -> bool:
        try:
            return int(chat_id) == int(admin_chat_id)
        except (TypeError, ValueError):
            return False

    async def _configure_webhook_for_token(bot_token: Optional[str]) -> tuple[Optional[bool], Optional[str]]:
        if not bot_token:
            return None, "Token bota jest pusty – pominięto konfigurację webhooka."

        settings = get_settings()
        base_url = getattr(settings, "webhook_base_url", None)
        if not base_url:
            return False, "Ustaw zmienną WEBHOOK_BASE_URL, aby automatycznie konfigurować webhooki."

        webhook_url = f"{base_url}/telegram/{bot_token}"
        webhook_bot = Bot(token=bot_token)
        try:
            await webhook_bot.set_webhook(
                webhook_url,
                secret_token=settings.webhook_secret,
                drop_pending_updates=False,
            )
        except (TelegramUnauthorizedError, TelegramBadRequest, TelegramNetworkError) as exc:
            return False, f"Nie udało się ustawić webhooka: {exc}"
        finally:
            await webhook_bot.session.close()

        return True, webhook_url

    current_persona_id = persona_id
    persona_cache: dict[str, Optional[str]] = {"name": None, "language": None}

    async def _ensure_persona_details() -> tuple[Optional[str], Optional[str]]:
        if current_persona_id is None:
            return None, None
        if persona_cache["name"] is None:
            async with get_session() as session:
                persona = await personas_service.get_persona_by_id(session, current_persona_id)
            if persona is not None:
                persona_cache["name"] = persona.name
                persona_cache["language"] = persona.language
        return persona_cache["name"], persona_cache["language"]

    admin_router = Router(name=f"admin-router-{bot_id or 'default'}")
    admin_router.message.filter(lambda message: _is_admin_chat_id(message.chat.id))
    admin_router.callback_query.filter(
        lambda callback: callback.message is not None
        and _is_admin_chat_id(callback.message.chat.id)
    )

    async def _send_menu(
        target: Message | CallbackQuery,
        state: FSMContext,
        *,
        intro: Optional[str] = None,
    ) -> None:
        await state.clear()
        text_lines = []
        if intro:
            text_lines.append(intro)
        text_lines.append("Wybierz akcję z przycisków poniżej.")

        keyboard = _main_menu_keyboard().as_markup()
        if isinstance(target, CallbackQuery):
            await target.answer()
            if target.message:
                await target.message.answer("\n".join(text_lines), reply_markup=keyboard)
        else:
            await target.answer("\n".join(text_lines), reply_markup=keyboard)

    @admin_router.message(CommandStart())
    async def handle_start(message: Message, state: FSMContext) -> None:
        intro_lines = [
            f"Cześć! Jestem bot <b>{resolved_display_name}</b>.",
            "Od teraz możesz zarządzać platformą bezpośrednio z tego czatu.",
        ]
        if moderator_chat_id:
            intro_lines.append(
                f"Ten czat jest administracyjnym centrum dowodzenia (ID: <code>{moderator_chat_id}</code>)."
            )
        await _send_menu(message, state, intro="\n".join(intro_lines))

    @admin_router.message(Command("menu"))
    async def handle_menu(message: Message, state: FSMContext) -> None:
        await _send_menu(message, state, intro="Menu główne")

    @admin_router.message(Command("cancel"))
    @admin_router.message(Command("anuluj"))
    async def handle_cancel(message: Message, state: FSMContext) -> None:
        if await state.get_state() is None:
            await message.answer("Nic nie było w toku. Wybierz akcję z menu.")
            return
        await state.clear()
        await message.answer("Operacja przerwana. Wracam do menu głównego.")
        await _send_menu(message, state)

    @admin_router.callback_query(F.data == "menu:main")
    async def handle_back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
        await _send_menu(callback, state, intro="Menu główne")

    @admin_router.callback_query(F.data == "menu:refresh_tokens")
    async def handle_refresh_tokens(callback: CallbackQuery, state: FSMContext) -> None:
        await bots_service.refresh_bot_token_cache()
        await callback.answer("Cache tokenów został odświeżony.", show_alert=False)

    @admin_router.callback_query(F.data == "menu:list_bots")
    async def handle_list_bots(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        async with get_session() as session:
            bots = await bots_service.list_bots(session)

        if not bots:
            text = "🚫 Brak aktywnych botów. Wybierz „Dodaj bota”, aby rozpocząć."
        else:
            lines = ["<b>Aktywne boty:</b>"]
            for bot_entry in bots:
                persona_name = bot_entry.persona.name if bot_entry.persona else "—"
                lines.append(
                    f"• <b>{bot_entry.display_name}</b> (persona: <i>{persona_name}</i>, ID: <code>{bot_entry.id}</code>)"
                )
            text = "\n".join(lines)

        await callback.answer()
        if callback.message:
            await callback.message.answer(text, reply_markup=_main_menu_keyboard().as_markup())

    def _snapshot_submission(submission: Submission) -> dict[str, Any]:
        return {
            "id": submission.id,
            "persona_id": submission.persona_id,
            "persona_name": submission.persona.name if submission.persona else None,
            "submitted_by_user_id": submission.submitted_by_user_id,
            "submitted_chat_id": submission.submitted_chat_id,
            "media_type": submission.media_type.value if isinstance(submission.media_type, MediaType) else str(submission.media_type),
            "text_content": submission.text_content or "",
            "file_id": submission.file_id,
            "created_at": submission.created_at.isoformat(),
        }

    async def _fetch_pending_snapshots() -> list[dict[str, Any]]:
        persona_filter = current_persona_id if current_persona_id is not None else None
        async with get_session() as session:
            submissions = await moderation_service.list_pending_submissions(
                session, persona_id=persona_filter
            )
        return [_snapshot_submission(item) for item in submissions]

    async def _send_submission_preview(message: Message, snapshot: dict[str, Any]) -> None:
        media_type_value = snapshot.get("media_type", MediaType.TEXT.value)
        file_id = snapshot.get("file_id")
        try:
            media_type_enum = MediaType(media_type_value)
        except ValueError:
            media_type_enum = MediaType.TEXT

        if file_id:
            caption = f"Zgłoszenie #{snapshot['id']} – podgląd"
            try:
                if media_type_enum == MediaType.IMAGE:
                    await message.answer_photo(file_id, caption=caption)
                elif media_type_enum == MediaType.AUDIO:
                    await message.answer_audio(file_id, caption=caption)
            except TelegramBadRequest:
                pass

        try:
            created_at_dt = datetime.fromisoformat(snapshot["created_at"])
            created_at_text = created_at_dt.strftime("%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            created_at_text = snapshot.get("created_at", "")

        persona_name = snapshot.get("persona_name") or (await _ensure_persona_details())[0] or "—"
        lines = [
            f"<b>Moderacja – zgłoszenie #{snapshot['id']}</b>",
            f"Persona: <i>{html.escape(persona_name)}</i>",
            f"Użytkownik: <code>{snapshot.get('submitted_by_user_id')}</code>",
            f"Czat: <code>{snapshot.get('submitted_chat_id')}</code>",
            f"Typ: <code>{media_type_enum.value}</code>",
            f"Zgłoszono: {created_at_text}",
        ]

        text_content = snapshot.get("text_content") or ""
        if text_content.strip():
            lines.append("")
            lines.append(f"<blockquote>{html.escape(text_content.strip())}</blockquote>")

        keyboard = InlineKeyboardBuilder()
        submission_id = snapshot["id"]
        keyboard.button(text="✅ Zatwierdź", callback_data=f"moderation:approve:{submission_id}")
        keyboard.button(text="❌ Odrzuć", callback_data=f"moderation:reject:{submission_id}")
        keyboard.button(text="⏭ Pomiń", callback_data=f"moderation:skip:{submission_id}")
        keyboard.button(text="↩️ Menu", callback_data="menu:main")
        keyboard.adjust(2, 1, 1)

        await message.answer("\n".join(lines), reply_markup=keyboard.as_markup())

    async def _show_next_submission(
        target: Message | CallbackQuery,
        state: FSMContext,
        *,
        reset_skip: bool = False,
    ) -> None:
        message_obj: Optional[Message]
        if isinstance(target, CallbackQuery):
            await target.answer()
            message_obj = target.message
        else:
            message_obj = target

        if message_obj is None:
            return

        data = await state.get_data()
        skipped_ids = set()
        if not reset_skip:
            skipped_ids = set(int(x) for x in data.get("moderation_skipped", []))

        snapshots = await _fetch_pending_snapshots()
        for snapshot in snapshots:
            if snapshot["id"] in skipped_ids:
                continue
            skipped_ids.discard(snapshot["id"])
            await state.update_data(
                moderation_current_submission=snapshot["id"],
                moderation_current_snapshot=snapshot,
                moderation_skipped=list(skipped_ids),
            )
            await _send_submission_preview(message_obj, snapshot)
            return

        await state.update_data(
            moderation_current_submission=None,
            moderation_current_snapshot=None,
            moderation_skipped=[],
        )
        await message_obj.answer(
            "Brak oczekujących zgłoszeń.",
            reply_markup=_main_menu_keyboard().as_markup(),
        )

    @admin_router.callback_query(F.data == "menu:moderation")
    async def handle_moderation_menu(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(ModerationStates.reviewing)
        await state.update_data(moderation_skipped=[])
        await _show_next_submission(callback, state, reset_skip=True)

    @admin_router.callback_query(lambda c: c.data is not None and c.data.startswith("moderation:approve:"))
    async def handle_moderation_approve(callback: CallbackQuery, state: FSMContext) -> None:
        submission_id_raw = (callback.data or "").rsplit(":", 1)[-1]
        try:
            submission_id = int(submission_id_raw)
        except ValueError:
            await callback.answer("Niepoprawne zgłoszenie.", show_alert=True)
            return

        async with get_session() as session:
            submission = await moderation_service.get_submission_by_id(session, submission_id)
            if submission is None or submission.status != ModerationStatus.PENDING:
                await callback.answer("To zgłoszenie zostało już przetworzone.", show_alert=True)
                await state.update_data(moderation_skipped=[])
                await _show_next_submission(callback, state, reset_skip=True)
                return
            moderator_user_id = callback.from_user.id if callback.from_user else None
            moderator_chat_id = callback.message.chat.id if callback.message else None
            await moderation_service.decide_submission(
                session,
                submission,
                moderator_user_id=moderator_user_id,
                moderator_chat_id=moderator_chat_id,
                action=ModerationStatus.APPROVED,
            )
            await quotes_service.create_quote_from_submission(session, submission)
            submitted_chat_id = submission.submitted_chat_id
            await session.commit()

        await callback.answer("Zgłoszenie zatwierdzone.", show_alert=False)

        if (
            submitted_chat_id
            and callback.message is not None
            and submitted_chat_id != callback.message.chat.id
        ):
            try:
                await callback.message.bot.send_message(
                    submitted_chat_id,
                    "✅ Dziękujemy! Twój cytat został zaakceptowany.",
                )
            except TelegramBadRequest:
                pass

        await state.update_data(moderation_skipped=[])
        await _show_next_submission(callback, state, reset_skip=True)

    @admin_router.callback_query(lambda c: c.data is not None and c.data.startswith("moderation:reject:"))
    async def handle_moderation_reject(callback: CallbackQuery, state: FSMContext) -> None:
        submission_id_raw = (callback.data or "").rsplit(":", 1)[-1]
        try:
            submission_id = int(submission_id_raw)
        except ValueError:
            await callback.answer("Niepoprawne zgłoszenie.", show_alert=True)
            return

        await state.update_data(moderation_reject_target=submission_id)
        await state.set_state(ModerationStates.waiting_rejection_reason)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Podaj powód odrzucenia (lub wyślij '-' aby pominąć)."
            )

    @admin_router.callback_query(lambda c: c.data is not None and c.data.startswith("moderation:skip:"))
    async def handle_moderation_skip(callback: CallbackQuery, state: FSMContext) -> None:
        submission_id_raw = (callback.data or "").rsplit(":", 1)[-1]
        try:
            submission_id = int(submission_id_raw)
        except ValueError:
            await callback.answer("Niepoprawne zgłoszenie.", show_alert=True)
            return

        data = await state.get_data()
        skipped = set(int(x) for x in data.get("moderation_skipped", []))
        skipped.add(submission_id)
        await state.update_data(moderation_skipped=list(skipped))
        await callback.answer("Pominięto.")
        await _show_next_submission(callback, state)

    @admin_router.message(ModerationStates.waiting_rejection_reason)
    async def handle_moderation_rejection_reason(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        submission_id = data.get("moderation_reject_target")
        if submission_id is None:
            await message.answer("Nie znaleziono zgłoszenia. Wróć do menu.")
            await state.set_state(ModerationStates.reviewing)
            await _show_next_submission(message, state, reset_skip=True)
            return

        reason_text = (message.text or "").strip()
        if reason_text == "-":
            reason_text = None

        async with get_session() as session:
            submission = await moderation_service.get_submission_by_id(session, int(submission_id))
            if submission is None or submission.status != ModerationStatus.PENDING:
                await message.answer("To zgłoszenie zostało już przetworzone.")
                await state.set_state(ModerationStates.reviewing)
                await state.update_data(moderation_reject_target=None, moderation_skipped=[])
                await _show_next_submission(message, state, reset_skip=True)
                return

            moderator_user_id = message.from_user.id if message.from_user else None
            moderator_chat_id = message.chat.id
            await moderation_service.decide_submission(
                session,
                submission,
                moderator_user_id=moderator_user_id,
                moderator_chat_id=moderator_chat_id,
                action=ModerationStatus.REJECTED,
                notes=reason_text,
            )
            submitted_chat_id = submission.submitted_chat_id
            await session.commit()

        note_suffix = f" Powód: {reason_text}" if reason_text else ""
        if submitted_chat_id and submitted_chat_id != message.chat.id:
            try:
                await message.bot.send_message(
                    submitted_chat_id,
                    f"❌ Twoja propozycja została odrzucona.{note_suffix}",
                )
            except TelegramBadRequest:
                pass

        await message.answer("Zgłoszenie odrzucone.")
        await state.set_state(ModerationStates.reviewing)
        await state.update_data(moderation_reject_target=None, moderation_skipped=[])
        await _show_next_submission(message, state, reset_skip=True)

    @admin_router.callback_query(F.data == "menu:edit_bot")
    async def handle_edit_bot(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        async with get_session() as session:
            bots = await bots_service.list_bots(session)

        if not bots:
            await callback.answer()
            if callback.message:
                await callback.message.answer(
                    "🚫 Brak botów do edycji. Wybierz „Dodaj bota”, aby utworzyć nowy rekord.",
                    reply_markup=_main_menu_keyboard().as_markup(),
                )
            return

        keyboard_builder = InlineKeyboardBuilder()
        for bot_entry in bots:
            keyboard_builder.button(
                text=f"{bot_entry.display_name} (ID: {bot_entry.id})",
                callback_data=f"edit_bot:{bot_entry.id}",
            )
        keyboard_builder.button(text="↩️ Wróć", callback_data="menu:main")
        keyboard_builder.adjust(1)

        await state.set_state(EditBotStates.choosing_bot)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Wybierz bota, którego chcesz edytować.",
                reply_markup=keyboard_builder.as_markup(),
            )

    @admin_router.callback_query(
        EditBotStates.choosing_bot, lambda c: c.data is not None and c.data.startswith("edit_bot:")
    )
    async def handle_edit_bot_choice(callback: CallbackQuery, state: FSMContext) -> None:
        bot_id_raw = (callback.data or "").split(":", 1)[1]
        try:
            bot_id = int(bot_id_raw)
        except ValueError:
            await callback.answer("Niepoprawny identyfikator bota.", show_alert=True)
            return

        async with get_session() as session:
            bot_record = await bots_service.get_bot_by_id(session, bot_id)

        if bot_record is None:
            await callback.answer("Nie znaleziono bota. Odśwież listę i spróbuj ponownie.", show_alert=True)
            return

        persona_name = bot_record.persona.name if bot_record.persona else "—"
        await state.update_data(
            bot_id=bot_record.id,
            current_token=bot_record.api_token,
            current_display_name=bot_record.display_name,
            current_persona_id=bot_record.persona_id,
            current_persona_name=persona_name,
        )
        await state.set_state(EditBotStates.waiting_token)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Wybrano bota <b>{name}</b> (ID: <code>{id}</code>).\n"
                "Wyślij nowy token lub '-' aby pozostawić bez zmian.\n"
                "Możesz przerwać w dowolnym momencie poleceniem /anuluj.".format(
                    name=bot_record.display_name,
                    id=bot_record.id,
                )
            )

    @admin_router.message(EditBotStates.waiting_token)
    async def edit_receive_token(message: Message, state: FSMContext) -> None:
        token_raw = (message.text or "").strip()
        if not token_raw:
            await message.answer("Podaj token lub '-' aby pozostawić dotychczasowy.")
            return

        if token_raw == "-":
            await state.update_data(new_token=None)
        else:
            if not _validate_token(token_raw):
                await message.answer(
                    "To nie wygląda na prawidłowy token bota. Spróbuj ponownie albo wyślij '-' aby pominąć zmianę."
                )
                return
            await state.update_data(new_token=token_raw)

        data = await state.get_data()
        current_display = data.get("current_display_name", "—")

        await state.set_state(EditBotStates.waiting_display_name)
        await message.answer(
            f"Obecna nazwa to <b>{current_display}</b>.\nWyślij nową nazwę lub '-' aby pozostawić bez zmian."
        )

    @admin_router.message(EditBotStates.waiting_display_name)
    async def edit_receive_display_name(message: Message, state: FSMContext) -> None:
        display_name_raw = (message.text or "").strip()
        if not display_name_raw:
            await message.answer("Nazwa nie może być pusta. Podaj nową nazwę lub '-' aby pozostawić bez zmian.")
            return

        if display_name_raw == "-":
            await state.update_data(new_display_name=None)
        else:
            await state.update_data(new_display_name=display_name_raw)

        async with get_session() as session:
            personas = await personas_service.list_personas(session)

        data = await state.get_data()
        current_persona_id = data.get("current_persona_id")
        current_persona_name = data.get("current_persona_name", "—")

        if personas:
            await state.update_data(
                persona_choices=[
                    {"id": persona.id, "name": persona.name, "language": persona.language}
                    for persona in personas
                ]
            )
            keyboard_builder = InlineKeyboardBuilder()
            for persona in personas:
                prefix = "⭐ " if persona.id == current_persona_id else ""
                keyboard_builder.button(
                    text=f"{prefix}{persona.name} ({persona.language})",
                    callback_data=f"edit_persona:{persona.id}",
                )
            keyboard_builder.button(text="➕ Nowa persona", callback_data="edit_persona:new")
            keyboard_builder.button(text="🛑 Bez zmian", callback_data="edit_persona:keep")
            keyboard_builder.button(text="↩️ Wróć", callback_data="menu:main")
            keyboard_builder.adjust(1)

            await state.set_state(EditBotStates.choosing_persona)
            await message.answer(
                f"Obecna persona: <i>{current_persona_name}</i>.\n"
                "Wybierz personę, dodaj nową lub pozostaw obecną.",
                reply_markup=keyboard_builder.as_markup(),
            )
        else:
            await state.set_state(EditBotStates.waiting_persona_name)
            await message.answer(
                "W bazie nie ma jeszcze żadnych person.\nPodaj nazwę nowej persony."
            )

    @admin_router.callback_query(EditBotStates.choosing_persona, F.data == "edit_persona:keep")
    async def handle_edit_persona_keep(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        await _finalize_bot_update(
            callback,
            state,
            persona_id=None,
            persona_name=data.get("current_persona_name"),
        )

    @admin_router.callback_query(EditBotStates.choosing_persona, F.data == "edit_persona:new")
    async def handle_edit_persona_new(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(EditBotStates.waiting_persona_name)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Podaj nazwę dla nowej persony. Upewnij się, że nazwa jest unikalna."
            )

    @admin_router.callback_query(
        EditBotStates.choosing_persona,
        lambda c: c.data is not None
        and c.data.startswith("edit_persona:")
        and c.data not in {"edit_persona:new", "edit_persona:keep"},
    )
    async def handle_edit_persona_choice(callback: CallbackQuery, state: FSMContext) -> None:
        persona_id_raw = (callback.data or "").split(":", 1)[1]
        try:
            persona_id = int(persona_id_raw)
        except ValueError:
            await callback.answer("Niepoprawna persona.", show_alert=True)
            return

        data = await state.get_data()
        persona_choices = data.get("persona_choices", [])
        persona_info = next((item for item in persona_choices if item["id"] == persona_id), None)
        if persona_info is None:
            await callback.answer("Nie znaleziono persony. Spróbuj ponownie.", show_alert=True)
            return

        await _finalize_bot_update(
            callback,
            state,
            persona_id=persona_id,
            persona_name=persona_info["name"],
        )

    @admin_router.message(EditBotStates.waiting_persona_name)
    async def edit_receive_persona_name(message: Message, state: FSMContext) -> None:
        name = (message.text or "").strip()
        if not name:
            await message.answer("Nazwa persony nie może być pusta. Spróbuj ponownie.")
            return

        async with get_session() as session:
            existing = await personas_service.get_persona_by_name(session, name)

        if existing is not None:
            await _finalize_bot_update(
                message,
                state,
                persona_id=existing.id,
                persona_name=existing.name,
            )
            return

        await state.update_data(new_persona={"name": name})
        await state.set_state(EditBotStates.waiting_persona_description)
        await message.answer(
            "Dodaj krótki opis persony (opcjonalnie). Jeśli chcesz pominąć, wyślij pojedynczy znak '-'."
        )

    @admin_router.message(EditBotStates.waiting_persona_description)
    async def edit_receive_persona_description(message: Message, state: FSMContext) -> None:
        description_raw = (message.text or "").strip()
        description = None if description_raw in {"", "-"} else description_raw

        data = await state.get_data()
        new_persona = data.get("new_persona", {})
        new_persona["description"] = description
        await state.update_data(new_persona=new_persona)

        await state.set_state(EditBotStates.waiting_persona_language)
        await message.answer(
            "Podaj kod języka (np. pl, en). Pozostaw puste lub wpisz 'auto', aby platforma wykrywała język automatycznie."
        )

    @admin_router.message(EditBotStates.waiting_persona_language)
    async def edit_receive_persona_language(message: Message, state: FSMContext) -> None:
        language_raw = (message.text or "").strip().lower()
        language = language_raw or "auto"

        data = await state.get_data()
        new_persona = data.get("new_persona", {})
        new_persona["language"] = language
        await state.update_data(new_persona=new_persona)

        async with get_session() as session:
            persona = await personas_service.create_persona(
                session,
                name=new_persona["name"],
                description=new_persona.get("description"),
                language=new_persona.get("language", "auto"),
            )
            await session.commit()

        await _finalize_bot_update(
            message,
            state,
            persona_id=persona.id,
            persona_name=persona.name,
        )

    @admin_router.callback_query(F.data == "menu:add_bot")
    async def handle_add_bot(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(AddBotStates.waiting_token)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Wyślij token bota otrzymany od @BotFather.\n"
                "Możesz przerwać w dowolnym momencie poleceniem /anuluj.",
            )

    def _validate_token(raw: str) -> bool:
        return ":" in raw and len(raw.split(":", 1)[0]) >= 3

    @admin_router.message(AddBotStates.waiting_token)
    async def receive_token(message: Message, state: FSMContext) -> None:
        token = (message.text or "").strip()
        if not _validate_token(token):
            await message.answer(
                "To nie wygląda na prawidłowy token bota. Spróbuj ponownie albo wpisz /anuluj, aby przerwać."
            )
            return
        await state.update_data(token=token)
        await state.set_state(AddBotStates.waiting_display_name)
        await message.answer("Świetnie! Jaką nazwę wyświetlaną nadać temu botowi?")

    @admin_router.message(AddBotStates.waiting_display_name)
    async def receive_display_name(message: Message, state: FSMContext) -> None:
        display_name = (message.text or "").strip()
        if not display_name:
            await message.answer("Nazwa nie może być pusta. Podaj nazwę wyświetlaną (np. „Bot operatorski”).")
            return

        await state.update_data(display_name=display_name)

        async with get_session() as session:
            personas = await personas_service.list_personas(session)

        if personas:
            await state.update_data(
                persona_choices=[
                    {"id": persona.id, "name": persona.name, "language": persona.language}
                    for persona in personas
                ]
            )
            keyboard_builder = InlineKeyboardBuilder()
            for persona in personas:
                keyboard_builder.button(
                    text=f"{persona.name} ({persona.language})",
                    callback_data=f"persona:{persona.id}",
                )
            keyboard_builder.button(text="➕ Nowa persona", callback_data="persona:new")
            keyboard_builder.button(text="↩️ Wróć", callback_data="menu:main")
            keyboard_builder.adjust(1)

            await state.set_state(AddBotStates.choosing_persona)
            await message.answer(
                "Wybierz personę, którą ma reprezentować bot, albo dodaj nową.",
                reply_markup=keyboard_builder.as_markup(),
            )
        else:
            await state.set_state(AddBotStates.waiting_persona_name)
            await message.answer(
                "W bazie nie ma jeszcze żadnych person.\n"
                "Podaj nazwę nowej persony (np. „Persona operatorska”)."
            )

    @admin_router.callback_query(AddBotStates.choosing_persona, F.data == "persona:new")
    async def handle_new_persona(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(AddBotStates.waiting_persona_name)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Podaj nazwę dla nowej persony. Upewnij się, że nazwa jest unikalna."
            )

    @admin_router.callback_query(
        AddBotStates.choosing_persona, lambda c: c.data is not None and c.data.startswith("persona:")
    )
    async def handle_existing_persona(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        persona_choices: Iterable[dict] = data.get("persona_choices", [])

        persona_id_str = (callback.data or "").split(":", 1)[1]
        try:
            persona_id = int(persona_id_str)
        except ValueError:
            await callback.answer("Niepoprawna persona.", show_alert=True)
            return

        persona_info = next((item for item in persona_choices if item["id"] == persona_id), None)
        if persona_info is None:
            await callback.answer("Nie znaleziono persony. Spróbuj ponownie.", show_alert=True)
            return

        await _finalize_bot_creation(
            callback,
            state,
            persona_id=persona_id,
            persona_name=persona_info["name"],
        )

    @admin_router.message(AddBotStates.waiting_persona_name)
    async def receive_persona_name(message: Message, state: FSMContext) -> None:
        name = (message.text or "").strip()
        if not name:
            await message.answer("Nazwa persony nie może być pusta. Spróbuj ponownie.")
            return

        async with get_session() as session:
            existing = await personas_service.get_persona_by_name(session, name)

        if existing is not None:
            await _finalize_bot_creation(
                message,
                state,
                persona_id=existing.id,
                persona_name=existing.name,
            )
            return

        await state.update_data(new_persona={"name": name})
        await state.set_state(AddBotStates.waiting_persona_description)
        await message.answer(
            "Dodaj krótki opis persony (opcjonalnie). Jeśli chcesz pominąć, wyślij pojedynczy znak '-'."
        )

    @admin_router.message(AddBotStates.waiting_persona_description)
    async def receive_persona_description(message: Message, state: FSMContext) -> None:
        description_raw = (message.text or "").strip()
        description = None if description_raw in {"", "-"} else description_raw

        data = await state.get_data()
        new_persona = data.get("new_persona", {})
        new_persona["description"] = description
        await state.update_data(new_persona=new_persona)

        await state.set_state(AddBotStates.waiting_persona_language)
        await message.answer(
            "Podaj kod języka (np. pl, en). Pozostaw puste lub wpisz 'auto', aby platforma wykrywała język automatycznie."
        )

    @admin_router.message(AddBotStates.waiting_persona_language)
    async def receive_persona_language(message: Message, state: FSMContext) -> None:
        language_raw = (message.text or "").strip().lower()
        language = language_raw or "auto"

        data = await state.get_data()
        new_persona = data.get("new_persona", {})
        new_persona["language"] = language
        await state.update_data(new_persona=new_persona)

        async with get_session() as session:
            persona = await personas_service.create_persona(
                session,
                name=new_persona["name"],
                description=new_persona.get("description"),
                language=new_persona.get("language", "auto"),
            )
            await session.commit()

        await _finalize_bot_creation(
            message,
            state,
            persona_id=persona.id,
            persona_name=persona.name,
        )

    async def _finalize_bot_creation(
        target: Message | CallbackQuery,
        state: FSMContext,
        *,
        persona_id: int,
        persona_name: str,
    ) -> None:
        data = await state.get_data()
        token = data.get("token")
        display_name = data.get("display_name")

        if not token or not display_name:
            # brak wymaganych danych – wróć do menu
            await state.clear()
            if isinstance(target, CallbackQuery):
                await target.answer("Brak wymaganych danych – spróbuj ponownie.", show_alert=True)
                return
            await target.answer("Brak wymaganych danych – zacznij od nowa poleceniem /start.")
            return

        async with get_session() as session:
            try:
                bot_record, created = await bots_service.upsert_bot(
                    session, token=token, display_name=display_name, persona_id=persona_id
                )
                await session.commit()
            except bots_service.BotLimitExceededError as exc:
                await session.rollback()
                warning = (
                    "❗️ Nie można dodać kolejnego bota: "
                    f"{exc}. Zaktualizuj limity w .env lub dezaktywuj istniejącego bota."
                )
                if isinstance(target, CallbackQuery):
                    await target.answer(str(exc), show_alert=True)
                    if target.message:
                        await target.message.answer(warning)
                else:
                    await target.answer(warning)
                return

        await bots_service.refresh_bot_token_cache()

        webhook_success, webhook_message = await _configure_webhook_for_token(bot_record.api_token)
        await state.clear()

        status = "✅ Dodano nowego bota" if created else "♻️ Zaktualizowano istniejącego bota"
        summary_lines = [
            f"{status}:",
            f"• Nazwa: <b>{display_name}</b>",
            f"• Persona: <i>{persona_name}</i>",
            f"• ID w bazie: <code>{bot_record.id}</code>",
        ]

        if webhook_success is True and webhook_message:
            summary_lines.append(f"• Webhook ustawiony: <code>{webhook_message}</code>")
        elif webhook_success is False and webhook_message:
            summary_lines.append(f"⚠️ {webhook_message} – ustaw webhook ręcznie, jeśli to konieczne.")
        elif webhook_message:
            summary_lines.append(f"⚠️ {webhook_message}")

        summary = "\n".join(summary_lines)

        if isinstance(target, CallbackQuery):
            await target.answer()
            if target.message:
                await target.message.answer(summary, reply_markup=_main_menu_keyboard().as_markup())
        else:
            await target.answer(summary, reply_markup=_main_menu_keyboard().as_markup())

    async def _finalize_bot_update(
        target: Message | CallbackQuery,
        state: FSMContext,
        *,
        persona_id: Optional[int],
        persona_name: Optional[str],
    ) -> None:
        data = await state.get_data()
        bot_id = data.get("bot_id")
        if bot_id is None:
            await state.clear()
            message_text = (
                "Brak wybranego bota. Wywołaj menu główne i spróbuj jeszcze raz."
            )
            if isinstance(target, CallbackQuery):
                await target.answer("Brak wybranego bota.", show_alert=True)
                if target.message:
                    await target.message.answer(message_text, reply_markup=_main_menu_keyboard().as_markup())
            else:
                await target.answer(message_text, reply_markup=_main_menu_keyboard().as_markup())
            return

        new_token: Optional[str] = data.get("new_token")
        new_display_name: Optional[str] = data.get("new_display_name")
        old_display_name: str = data.get("current_display_name", "—")
        old_persona_name: str = data.get("current_persona_name", "—")
        old_token: Optional[str] = data.get("current_token")
        persona_label = persona_name or old_persona_name

        async with get_session() as session:
            bot_record = await bots_service.get_bot_by_id(session, bot_id)
            if bot_record is None:
                await state.clear()
                message_text = (
                    "Nie znaleziono bota w bazie. Możliwe, że został usunięty w międzyczasie."
                )
                if isinstance(target, CallbackQuery):
                    await target.answer("Nie znaleziono bota.", show_alert=True)
                    if target.message:
                        await target.message.answer(
                            message_text, reply_markup=_main_menu_keyboard().as_markup()
                        )
                else:
                    await target.answer(message_text, reply_markup=_main_menu_keyboard().as_markup())
                return

            try:
                updated_bot = await bots_service.update_bot(
                    session,
                    bot_record,
                    token=new_token,
                    display_name=new_display_name,
                    persona_id=persona_id,
                )
                await session.commit()
            except bots_service.BotTokenInUseError as exc:
                await session.rollback()
                warning = (
                    "❗️ Ten token jest już przypisany do innego bota. "
                    "Podaj inny token lub wyślij '-' aby pozostawić dotychczasowy."
                )
                await state.set_state(EditBotStates.waiting_token)
                if isinstance(target, CallbackQuery):
                    await target.answer(str(exc), show_alert=True)
                    if target.message:
                        await target.message.answer(warning)
                else:
                    await target.answer(warning)
                return

        await bots_service.refresh_bot_token_cache()
        webhook_success, webhook_message = await _configure_webhook_for_token(updated_bot.api_token)
        await state.clear()

        new_token_effective = updated_bot.api_token
        token_changed = old_token and new_token_effective and old_token != new_token_effective

        summary_lines = [
            "💾 Zaktualizowano bota:",
            f"• Nazwa: <b>{updated_bot.display_name or old_display_name}</b>",
            f"• Persona: <i>{persona_label}</i>",
            f"• ID w bazie: <code>{updated_bot.id}</code>",
        ]

        if webhook_success is True and webhook_message:
            summary_lines.append(f"• Webhook ustawiony: <code>{webhook_message}</code>")
            if token_changed:
                summary_lines.append("• Token został zmieniony i webhook przełączono automatycznie.")
        elif webhook_success is False and webhook_message:
            summary_lines.append(f"⚠️ {webhook_message}")
            if token_changed:
                summary_lines.append("⚠️ Token został zmieniony – skonfiguruj webhook ręcznie.")
        elif webhook_message:
            summary_lines.append(f"⚠️ {webhook_message}")

        if old_token and new_token_effective is None:
            summary_lines.append("⚠️ Token został usunięty – webhook przestał działać.")

        summary = "\n".join(summary_lines)

        if isinstance(target, CallbackQuery):
            await target.answer()
            if target.message:
                await target.message.answer(summary, reply_markup=_main_menu_keyboard().as_markup())
        else:
            await target.answer(summary, reply_markup=_main_menu_keyboard().as_markup())

    async def _get_bot_identity() -> tuple[int, Optional[str]]:
        nonlocal bot
        if not hasattr(_get_bot_identity, "_cache"):
            _get_bot_identity._cache = {}

        cache = getattr(_get_bot_identity, "_cache")
        cached = cache.get(bot.token)
        if cached is not None:
            return cached

        profile = await bot.get_me()
        username = profile.username.lower() if profile.username else None
        cached_value = (profile.id, username)
        cache[bot.token] = cached_value
        return cached_value

    def _strip_bot_mentions(text: str, username: Optional[str]) -> str:
        if not text:
            return ""

        cleaned = text
        if username:
            mention_pattern = re.compile(rf"@{re.escape(username)}", re.IGNORECASE)
            cleaned = mention_pattern.sub(" ", cleaned)
        cleaned = re.sub(r"/[-_\w]+(?:@[-_\w]+)?", " ", cleaned)
        return " ".join(cleaned.split())

    def _collect_message_context(message: Message, username: Optional[str]) -> str:
        parts: list[str] = []
        primary_text = message.text or message.caption or ""
        cleaned_primary = _strip_bot_mentions(primary_text, username)
        if cleaned_primary:
            parts.append(cleaned_primary)

        reply = message.reply_to_message
        if reply:
            reply_text = reply.text or reply.caption or ""
            if reply_text:
                parts.append(reply_text)

        combined = "\n".join(part for part in parts if part).strip()
        if not combined and reply:
            combined = (reply.text or reply.caption or "").strip()
        return combined

    async def _is_direct_invocation(message: Message) -> bool:
        content = (message.text or message.caption or "").strip()
        if not content:
            return False

        chat_type = getattr(message.chat, "type", "")
        if chat_type == "private":
            return True

        bot_id, username = await _get_bot_identity()

        reply = message.reply_to_message
        if (
            reply
            and reply.from_user is not None
            and reply.from_user.is_bot
            and reply.from_user.id == bot_id
        ):
            return True

        def _check_entities(entities: Optional[list], text: str) -> bool:
            if not entities or not text:
                return False
            for entity in entities:
                snippet = text[entity.offset : entity.offset + entity.length]
                entity_type = getattr(entity, "type", "")
                if entity_type == "mention" and username and snippet.lower() == f"@{username}":
                    return True
                if entity_type == "text_mention" and getattr(entity, "user", None):
                    if entity.user.id == bot_id:
                        return True
                if entity_type == "bot_command":
                    command = snippet.lower()
                    if username and command.endswith(f"@{username}"):
                        return True
                    if chat_type == "private":
                        return True
            return False

        if _check_entities(message.entities, message.text or ""):
            return True
        if _check_entities(message.caption_entities, message.caption or ""):
            return True

        if username and f"@{username}" in content.lower():
            return True

        return False

    async def _reply_with_quote(message: Message, quote: Quote) -> None:
        text_payload = (quote.text_content or "").strip() or "…"
        try:
            if quote.media_type == MediaType.TEXT or not quote.file_id:
                await message.answer(text_payload)
            elif quote.media_type == MediaType.IMAGE:
                await message.answer_photo(quote.file_id, caption=text_payload if quote.text_content else None)
            elif quote.media_type == MediaType.AUDIO:
                await message.answer_audio(quote.file_id, caption=text_payload if quote.text_content else None)
            else:
                await message.answer(text_payload)
        except TelegramBadRequest:
            await message.answer(text_payload)

    async def _resolve_language_priority(persona_language: Optional[str], message: Message) -> list[str]:
        priority: list[str] = []
        user_language = getattr(message.from_user, "language_code", None)
        if user_language:
            priority.append(user_language)
        if persona_language and persona_language not in {"", "auto"}:
            priority.append(persona_language)

        prepared: list[str] = []
        seen: set[str] = set()
        for lang in priority:
            normalized = lang.lower()
            if "-" in normalized:
                normalized = normalized.split("-", 1)[0]
            if normalized not in seen:
                seen.add(normalized)
                prepared.append(normalized)
        return prepared

    public_router = Router(name=f"public-router-{bot_id or 'default'}")
    public_router.message.filter(lambda message: not _is_admin_chat_id(message.chat.id))

    @public_router.message(F.text | F.caption)
    async def handle_public_invocation(message: Message) -> None:
        if message.from_user and message.from_user.is_bot:
            return

        if not await _is_direct_invocation(message):
            return

        if bot_id is None:
            await message.answer("Ten bot nie jest jeszcze skonfigurowany – brak powiązanej persony.")
            return

        async with get_session() as session:
            bot_record = await bots_service.get_bot_by_id(session, bot_id)
            persona = bot_record.persona if bot_record else None
            if persona is None:
                await message.answer("Nie odnaleziono persony bota ani powiązanych cytatów.")
                return

            bot_identity = await _get_bot_identity()
            _, username = bot_identity
            query = _collect_message_context(message, username)

            language_priority = await _resolve_language_priority(persona.language, message)
            quote = await quotes_service.select_relevant_quote(
                session,
                persona,
                query=query,
                language_priority=language_priority,
            )

        if quote is None:
            await message.answer("Niestety, nie znalazłem odpowiedniego cytatu.")
            return

        await _reply_with_quote(message, quote)

    dispatcher.include_router(admin_router)
    dispatcher.include_router(public_router)
    user_router = Router(name=f"user-router-{bot_id or 'default'}")
    user_router.message.filter(lambda message: not _is_admin_chat_id(message.chat.id))

    @user_router.message()
    async def handle_user_submission(message: Message) -> None:
        if current_persona_id is None:
            await message.answer(
                "Ten bot nie jest jeszcze gotowy do przyjmowania wiadomości. Spróbuj ponownie później."
            )
            return

        if message.from_user is None:
            await message.answer("Nie udało się rozpoznać nadawcy wiadomości.")
            return

        text_content: Optional[str] = None
        file_id: Optional[str] = None
        media_type_enum: Optional[MediaType] = None

        if message.text:
            text_content = message.text.strip()
            if not text_content:
                await message.answer("Wyślij proszę treść cytatu w wiadomości tekstowej.")
                return
            media_type_enum = MediaType.TEXT
        elif message.photo:
            media_type_enum = MediaType.IMAGE
            file_id = message.photo[-1].file_id
            if message.caption:
                text_content = message.caption.strip()
        elif message.voice:
            media_type_enum = MediaType.AUDIO
            file_id = message.voice.file_id
            if message.caption:
                text_content = message.caption.strip()
        elif message.audio:
            media_type_enum = MediaType.AUDIO
            file_id = message.audio.file_id
            if message.caption:
                text_content = message.caption.strip()
        else:
            await message.answer(
                "Obecnie przyjmuję tylko tekst, zdjęcia lub nagrania audio. Wyślij cytat w jednym z tych formatów."
            )
            return

        if media_type_enum is None:
            await message.answer("Nie udało się rozpoznać typu wiadomości.")
            return

        async with get_session() as session:
            submission = await moderation_service.create_submission(
                session,
                persona_id=current_persona_id,
                submitted_by_user_id=message.from_user.id,
                submitted_chat_id=message.chat.id,
                media_type=media_type_enum,
                text_content=text_content,
                file_id=file_id,
            )
            await session.commit()

        await message.answer("Dziękujemy! Twoja propozycja trafiła do kolejki moderacji.")

        if admin_chat_id and message.chat.id != admin_chat_id:
            persona_name, _ = await _ensure_persona_details()
            preview = text_content or ("[obraz]" if media_type_enum == MediaType.IMAGE else "[audio]")
            summary_lines = [
                "📥 <b>Nowe zgłoszenie do moderacji</b>",
                f"ID: <code>{submission.id}</code>",
                f"Persona: <i>{html.escape(persona_name or str(current_persona_id))}</i>",
                f"Użytkownik: <code>{message.from_user.id}</code>",
                f"Czat: <code>{message.chat.id}</code>",
                f"Typ: <code>{media_type_enum.value}</code>",
            ]
            if preview:
                summary_lines.append("")
                summary_lines.append(html.escape(preview[:200]))
            try:
                keyboard_builder = InlineKeyboardBuilder()
                keyboard_builder.button(text="🗳 Moderuj", callback_data="menu:moderation")
                keyboard_builder.adjust(1)
                await message.bot.send_message(
                    admin_chat_id,
                    "\n".join(summary_lines),
                    reply_markup=keyboard_builder.as_markup(),
                )
            except TelegramBadRequest:
                pass

    dispatcher.include_router(user_router)

    return DispatcherBundle(
        dispatcher=dispatcher,
        bot=bot,
        moderator_chat_id=moderator_chat_id,
        persona_id=current_persona_id,
        bot_id=bot_id,
        display_name=resolved_display_name,
    )


__all__ = ["DispatcherBundle", "build_dispatcher"]
