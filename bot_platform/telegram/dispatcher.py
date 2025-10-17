"""Aiogram dispatcher factory and admin chat handlers."""
from __future__ import annotations

import logging
import re
import html
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    SkipHandler,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)
from aiogram.enums import MessageEntityType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramUnauthorizedError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import get_settings
from ..database import get_session
from ..models import MediaType, ModerationStatus, Quote, Submission
from ..services import bots as bots_service
from ..services import identities as identities_service
from ..services import moderation as moderation_service
from ..services import personas as personas_service
from ..services import quotes as quotes_service
from .states import AddBotStates, EditBotStates, IdentityStates, ModerationStates


logger = logging.getLogger(__name__)


def normalize_entity_type(entity_type: Any) -> str:
    """Return a lowercase representation for Telegram message entity types."""

    if isinstance(entity_type, MessageEntityType):
        return entity_type.value
    if isinstance(entity_type, str):
        return entity_type.lower()
    return str(entity_type).lower()


def resolve_reply_target(message: Message) -> Optional[Message]:
    """Return message that should receive the bot reply, if different from the request."""

    reply = getattr(message, "reply_to_message", None)
    if reply is None:
        return None

    try:
        original_chat_id = getattr(message.chat, "id", None)
        reply_chat_id = getattr(reply.chat, "id", None)
    except AttributeError:
        return reply

    if original_chat_id is None or reply_chat_id is None:
        return reply

    if reply_chat_id == original_chat_id:
        return reply

    return None


def _is_expired_callback_query_error(error: TelegramBadRequest) -> bool:
    message = getattr(error, "message", None) or str(error)
    normalized = message.lower()
    return "query is too old" in normalized or "query id is invalid" in normalized


async def _safe_callback_answer(callback: CallbackQuery, *args: Any, **kwargs: Any) -> None:
    try:
        await callback.answer(*args, **kwargs)
    except TelegramBadRequest as exc:
        if _is_expired_callback_query_error(exc):
            logger.debug("Ignoring expired callback query %s: %s", callback.id, exc)
            return
        raise


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
    builder.button(text="🆔 Tożsamości", callback_data="menu:identities")
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

    def _format_identity_summary(active: int, total: int) -> str:
        if total <= 0:
            return "brak tożsamości"
        inactive = max(total - active, 0)
        if inactive == 0:
            return f"{active} aktywnych"
        return f"{active} aktywnych, {inactive} wyłączonych"
    MAX_PENDING_PREVIEW = 20

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

    _IDENTITY_FIELD_LABELS = {
        "id": "ID",
        "alias": "alias",
        "name": "nazwa",
    }

    def _format_identity_fields(fields: Iterable[str]) -> str:
        labels = [_IDENTITY_FIELD_LABELS.get(field, field) for field in fields]
        return ", ".join(label for label in labels if label)

    def _build_identity_snapshot(submission: Submission) -> dict[str, Any]:
        result = identities_service.evaluate_submission_identity(submission)
        available = [
            identities_service.describe_identity(descriptor)
            for descriptor in result.descriptors
        ]
        partial = [
            {
                "identity": identities_service.describe_identity(descriptor),
                "fields": list(fields),
            }
            for descriptor, fields in result.partial_matches
        ]
        return {
            "matched": result.matched,
            "matched_fields": list(result.matched_fields),
            "matched_identity": identities_service.describe_identity(result.matched_identity)
            if result.matched_identity
            else None,
            "available": available,
            "partial": partial,
        }

    def _format_queue_summary_line(snapshot: dict[str, Any]) -> str:
        persona_value = snapshot.get("persona_name") or snapshot.get("persona_id") or "—"
        persona_label = html.escape(str(persona_value))
        media_type_value = snapshot.get("media_type", MediaType.TEXT.value)
        try:
            media_type_enum = MediaType(media_type_value)
        except ValueError:
            media_type_enum = MediaType.TEXT
        created_at_raw = snapshot.get("created_at")
        created_at_text = "?"
        if created_at_raw:
            try:
                created_at_dt = datetime.fromisoformat(created_at_raw)
                created_at_text = created_at_dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                created_at_text = str(created_at_raw)
        return (
            f"• #{snapshot.get('id')} – typ: <code>{html.escape(media_type_enum.value)}</code>, "
            f"persona: <i>{persona_label}</i>, zgłoszono: {created_at_text}"
        )

    def _compose_queue_summary_message(
        snapshots: list[dict[str, Any]], total_pending: int
    ) -> tuple[str, Optional[InlineKeyboardMarkup]]:
        if total_pending == 0:
            return (
                "📭 W kolejce moderacyjnej nie ma żadnych zgłoszeń.",
                _main_menu_keyboard().as_markup(),
            )

        lines = [f"📊 W kolejce moderacyjnej czeka {total_pending} zgłoszeń."]
        if total_pending > MAX_PENDING_PREVIEW:
            lines.append(
                f"Prezentuję {MAX_PENDING_PREVIEW} najstarszych wpisów oczekujących na moderację."
            )
        else:
            lines.append("Prezentuję wszystkie oczekujące wpisy.")

        if snapshots:
            lines.append("")
            lines.append("📝 Najstarsze zgłoszenia:")
            for snapshot in snapshots:
                lines.append(_format_queue_summary_line(snapshot))

        return "\n".join(lines), None

    async def _prompt_identity_persona_choice(
        target: Message | CallbackQuery,
        state: FSMContext,
        *,
        intro: Optional[str] = None,
    ) -> None:
        async with get_session() as session:
            persona_stats = await personas_service.list_personas_with_identity_stats(session)

        if not persona_stats:
            message_text = (
                "Brak dostępnych person. Dodaj nowego bota lub personę, aby móc zarządzać tożsamościami."
            )
            keyboard = _main_menu_keyboard().as_markup()
            await state.clear()
            if isinstance(target, CallbackQuery):
                await _safe_callback_answer(target)
                if target.message:
                    await target.message.answer(message_text, reply_markup=keyboard)
            else:
                await target.answer(message_text, reply_markup=keyboard)
            return

        await state.set_state(IdentityStates.choosing_persona)

        builder = InlineKeyboardBuilder()
        for summary in persona_stats:
            persona = summary.persona
            label = persona.name or f"ID {persona.id}"
            hint = _format_identity_summary(summary.active_identities, summary.total_identities)
            builder.button(
                text=f"{label} · {hint}", callback_data=f"identity:persona:{persona.id}"
            )
        builder.button(text="⬅️ Menu główne", callback_data="identity:cancel")
        builder.adjust(1)

        lines = []
        if intro:
            lines.append(intro)
        lines.append("Wybierz personę, której tożsamości chcesz aktualizować.")

        if isinstance(target, CallbackQuery):
            await _safe_callback_answer(target)
            if target.message:
                await target.message.answer("\n".join(lines), reply_markup=builder.as_markup())
        else:
            await target.answer("\n".join(lines), reply_markup=builder.as_markup())

    def _parse_identity_payload(text: str) -> Optional[dict[str, Optional[str | int]]]:
        content = (text or "").strip()
        if not content:
            return None

        user_id: Optional[int] = None
        username: Optional[str] = None
        display_name: Optional[str] = None

        fragments = [segment.strip() for segment in re.split(r"[;\n]+", content) if segment.strip()]
        if not fragments:
            return None

        for fragment in fragments:
            normalized = fragment
            if "=" not in normalized and ":" in normalized:
                normalized = normalized.replace(":", "=", 1)
            if "=" in normalized:
                key, value = normalized.split("=", 1)
                key = key.strip().lower()
                value = value.strip().strip('"\'')
            else:
                key = None
                value = normalized.strip().strip('"\'')

            if not value:
                continue

            if key in {"id", "user_id", "uid"} or (key is None and value.isdigit() and user_id is None):
                try:
                    user_id = int(value)
                except ValueError:
                    return None
                continue

            if key in {"alias", "username", "user"} or (
                key is None and value.startswith("@") and username is None
            ):
                username = value
                continue

            if key in {"name", "display_name", "display"} or key is None:
                display_name = value

        if not any([user_id, username, display_name]):
            return None

        return {
            "telegram_user_id": user_id,
            "telegram_username": username,
            "display_name": display_name,
        }

    async def _render_identity_overview(
        target: Message | CallbackQuery,
        state: FSMContext,
        persona_id: int,
        *,
        notice: Optional[str] = None,
    ) -> None:
        async with get_session() as session:
            persona = await personas_service.get_persona_by_id(session, persona_id)
            if persona is None:
                await _prompt_identity_persona_choice(
                    target,
                    state,
                    intro="Nie znaleziono wskazanej persony. Wybierz inną z listy.",
                )
                return
            identities = await identities_service.list_persona_identities(
                session, persona, include_removed=True
            )

        active = [identity for identity in identities if identity.removed_at is None]
        removed = [identity for identity in identities if identity.removed_at is not None]

        lines: list[str] = []
        if notice:
            lines.append(notice)
            lines.append("")

        persona_label = html.escape(persona.name or str(persona_id))
        lines.append(
            f"Tożsamości persony <b>{persona_label}</b> (ID: <code>{persona_id}</code>)."
        )
        lines.append(
            f"Powiązane wpisy: {_format_identity_summary(len(active), len(identities))}."
        )

        if active:
            lines.append("")
            lines.append("<b>Aktywne wpisy:</b>")
            for identity in active:
                description = html.escape(identities_service.describe_identity(identity))
                lines.append(f"• #{identity.id}: {description}")
        else:
            lines.append("")
            lines.append("Brak aktywnych wpisów. Dodaj nową tożsamość, aby rozpocząć weryfikację.")

        if removed:
            lines.append("")
            lines.append("<b>Wyłączone wpisy:</b>")
            for identity in removed:
                description = html.escape(identities_service.describe_identity(identity))
                removed_at = identity.removed_at.strftime("%Y-%m-%d %H:%M") if identity.removed_at else "—"
                lines.append(f"• #{identity.id}: {description} (wyłączono {removed_at})")

        lines.append("")
        lines.append(
            "Możesz zdefiniować wiele wpisów, aby obsłużyć alternatywne konta lub zmiany użytkownika."
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Dodaj tożsamość", callback_data="identity:add")
        if active:
            builder.button(text="🗑 Usuń tożsamość", callback_data="identity:remove")
        builder.button(text="👤 Zmień personę", callback_data="identity:change_persona")
        builder.button(text="⬅️ Menu główne", callback_data="identity:cancel")
        builder.adjust(1)

        if isinstance(target, CallbackQuery):
            await _safe_callback_answer(target)
            if target.message:
                await target.message.answer("\n".join(lines), reply_markup=builder.as_markup())
        else:
            await target.answer("\n".join(lines), reply_markup=builder.as_markup())

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
            await _safe_callback_answer(target)
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

    @admin_router.callback_query(F.data == "menu:identities")
    async def handle_identity_menu(callback: CallbackQuery, state: FSMContext) -> None:
        await _prompt_identity_persona_choice(
            callback, state, intro="Zarządzanie tożsamościami persony."
        )

    @admin_router.callback_query(lambda c: c.data == "identity:cancel")
    async def handle_identity_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await _send_menu(callback, state, intro="Menu główne")

    @admin_router.callback_query(
        IdentityStates.choosing_persona,
        lambda c: c.data is not None and c.data.startswith("identity:persona:"),
    )
    async def handle_identity_persona_choice(callback: CallbackQuery, state: FSMContext) -> None:
        data_raw = (callback.data or "").split(":")
        try:
            persona_id = int(data_raw[-1])
        except (ValueError, IndexError):
            await _safe_callback_answer(callback, "Niepoprawna persona.", show_alert=True)
            return

        await state.update_data(identity_persona_id=persona_id)
        await state.set_state(IdentityStates.managing_persona)
        await _render_identity_overview(callback, state, persona_id)

    @admin_router.callback_query(IdentityStates.managing_persona, F.data == "identity:change_persona")
    async def handle_identity_change_persona(
        callback: CallbackQuery, state: FSMContext
    ) -> None:
        await state.update_data(identity_persona_id=None)
        await _prompt_identity_persona_choice(
            callback, state, intro="Wybierz inną personę do aktualizacji tożsamości."
        )

    @admin_router.callback_query(IdentityStates.managing_persona, F.data == "identity:add")
    async def handle_identity_add(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        if data.get("identity_persona_id") is None:
            await _prompt_identity_persona_choice(
                callback, state, intro="Wybierz najpierw personę, a następnie dodaj tożsamość."
            )
            return

        await state.set_state(IdentityStates.waiting_identity_payload)
        await _safe_callback_answer(callback)
        instructions = (
            "Wyślij dane tożsamości w jednej wiadomości. Możesz użyć formatu:\n"
            "<code>id=123456789\nalias=@przyklad\nname=Jan Kowalski</code>\n"
            "Wystarczy podać dowolne z pól <code>id</code>, <code>alias</code> lub <code>name</code>.\n"
            "Aby anulować, wpisz /cancel."
        )
        if callback.message:
            await callback.message.answer(instructions)

    @admin_router.message(IdentityStates.waiting_identity_payload)
    async def handle_identity_payload(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        persona_id_raw = data.get("identity_persona_id")
        if persona_id_raw is None:
            await message.answer("Brak wybranej persony. Wybierz ją ponownie z listy.")
            await _prompt_identity_persona_choice(
                message, state, intro="Wybierz personę, której tożsamość chcesz uzupełnić."
            )
            return

        parsed = _parse_identity_payload(message.text or message.caption or "")
        if not parsed:
            await message.answer(
                "Nie rozumiem tego formatu. Skorzystaj z kluczy <code>id</code>, <code>alias</code> lub "
                "<code>name</code> – każdy w osobnej linii lub oddzielone średnikiem."
            )
            return

        async with get_session() as session:
            persona = await personas_service.get_persona_by_id(session, int(persona_id_raw))
            if persona is None:
                await message.answer("Wybrana persona już nie istnieje. Wybierz inną.")
                await _prompt_identity_persona_choice(
                    message, state, intro="Wybierz personę, której tożsamości chcesz zarządzać."
                )
                return

            identity = await identities_service.add_identity(
                session,
                persona,
                telegram_user_id=parsed.get("telegram_user_id"),
                telegram_username=parsed.get("telegram_username"),
                display_name=parsed.get("display_name"),
                admin_user_id=message.from_user.id if message.from_user else None,
                admin_chat_id=message.chat.id,
            )
            description = identities_service.describe_identity(identity)
            await session.commit()

        await state.set_state(IdentityStates.managing_persona)
        await message.answer(
            f"✅ Zapisano tożsamość: <i>{html.escape(description)}</i>."
        )
        await _render_identity_overview(message, state, int(persona_id_raw))

    @admin_router.callback_query(IdentityStates.managing_persona, F.data == "identity:remove")
    async def handle_identity_remove_start(
        callback: CallbackQuery, state: FSMContext
    ) -> None:
        data = await state.get_data()
        persona_id_raw = data.get("identity_persona_id")
        if persona_id_raw is None:
            await _prompt_identity_persona_choice(
                callback, state, intro="Wybierz personę, dla której chcesz usunąć tożsamość."
            )
            return

        async with get_session() as session:
            persona = await personas_service.get_persona_by_id(session, int(persona_id_raw))
            if persona is None:
                await _prompt_identity_persona_choice(
                    callback, state, intro="Wybrana persona została usunięta. Wybierz inną."
                )
                return
            active_identities = await identities_service.list_persona_identities(
                session, persona, include_removed=False
            )

        if not active_identities:
            await _safe_callback_answer(
                callback,
                "Brak aktywnych wpisów do wyłączenia.",
                show_alert=True,
            )
            return

        builder = InlineKeyboardBuilder()
        for identity in active_identities:
            label = f"#{identity.id}: {identities_service.describe_identity(identity)}"
            if len(label) > 60:
                label = label[:57] + "…"
            builder.button(text=label, callback_data=f"identity:remove:{identity.id}")
        builder.button(text="⬅️ Anuluj", callback_data="identity:remove:cancel")
        builder.adjust(1)

        await state.set_state(IdentityStates.choosing_identity_to_remove)
        await _safe_callback_answer(callback)
        if callback.message:
            await callback.message.answer(
                "Wybierz wpis, który chcesz wyłączyć.", reply_markup=builder.as_markup()
            )

    @admin_router.callback_query(
        IdentityStates.choosing_identity_to_remove,
        F.data == "identity:remove:cancel",
    )
    async def handle_identity_remove_cancel(
        callback: CallbackQuery, state: FSMContext
    ) -> None:
        await state.set_state(IdentityStates.managing_persona)
        data = await state.get_data()
        persona_id_raw = data.get("identity_persona_id")
        if persona_id_raw is None:
            await _prompt_identity_persona_choice(
                callback, state, intro="Wybierz personę, której tożsamości chcesz zobaczyć."
            )
            return
        await _render_identity_overview(
            callback,
            state,
            int(persona_id_raw),
            notice="Anulowano wybór tożsamości do usunięcia.",
        )

    @admin_router.callback_query(
        IdentityStates.choosing_identity_to_remove,
        lambda c: c.data is not None
        and c.data.startswith("identity:remove:")
        and c.data != "identity:remove:cancel",
    )
    async def handle_identity_remove_confirm(
        callback: CallbackQuery, state: FSMContext
    ) -> None:
        try:
            identity_id = int((callback.data or "").rsplit(":", 1)[-1])
        except (ValueError, IndexError):
            await _safe_callback_answer(callback, "Niepoprawny wpis.", show_alert=True)
            return

        data = await state.get_data()
        persona_id_raw = data.get("identity_persona_id")
        if persona_id_raw is None:
            await _prompt_identity_persona_choice(
                callback, state, intro="Wybierz personę, której tożsamości chcesz zarządzać."
            )
            return

        async with get_session() as session:
            identity = await identities_service.get_identity_by_id(session, identity_id)
            if identity is None or identity.persona_id != int(persona_id_raw):
                await _safe_callback_answer(
                    callback, "Nie znaleziono wskazanej tożsamości.", show_alert=True
                )
                await state.set_state(IdentityStates.managing_persona)
                await _render_identity_overview(callback, state, int(persona_id_raw))
                return

            description = identities_service.describe_identity(identity)
            await identities_service.remove_identity(
                session,
                identity,
                admin_user_id=callback.from_user.id if callback.from_user else None,
                admin_chat_id=callback.message.chat.id if callback.message else None,
            )
            await session.commit()

        await state.set_state(IdentityStates.managing_persona)
        await _render_identity_overview(
            callback,
            state,
            int(persona_id_raw),
            notice=(
                f"🗑 Wyłączono wpis #{identity_id}: <i>{html.escape(description)}</i>."
            ),
        )

    @admin_router.message(Command("cancel"))
    @admin_router.message(Command("anuluj"))
    async def handle_cancel(message: Message, state: FSMContext) -> None:
        if await state.get_state() is None:
            await message.answer("Nic nie było w toku. Wybierz akcję z menu.")
            return
        await state.clear()
        await message.answer("Operacja przerwana. Wracam do menu głównego.")
        await _send_menu(message, state)

    @admin_router.message(Command(commands=["clear_queue", "clear-queue", "clear-queque", "panic"]))
    async def handle_clear_queue(message: Message, state: FSMContext) -> None:
        async with get_session() as session:
            removed = await moderation_service.purge_pending_submissions(
                session, persona_id=current_persona_id
            )
            await session.commit()

        await state.clear()

        if removed == 0:
            response = "📭 Kolejka moderacyjna była już pusta."
        elif removed == 1:
            response = "🧹 Usunięto 1 zgłoszenie z kolejki moderacyjnej."
        else:
            response = f"🧹 Usunięto {removed} zgłoszeń z kolejki moderacyjnej."

        await message.answer(response)
        await _send_menu(message, state)

    @admin_router.callback_query(F.data == "menu:main")
    async def handle_back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
        await _send_menu(callback, state, intro="Menu główne")

    @admin_router.callback_query(F.data == "menu:refresh_tokens")
    async def handle_refresh_tokens(callback: CallbackQuery, state: FSMContext) -> None:
        await bots_service.refresh_bot_token_cache()
        await _safe_callback_answer(callback, "Cache tokenów został odświeżony.", show_alert=False)

    @admin_router.callback_query(F.data == "menu:list_bots")
    async def handle_list_bots(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        async with get_session() as session:
            bots = await bots_service.list_bots(session)
            persona_stats = await personas_service.list_personas_with_identity_stats(session)

        stats_by_persona = {
            summary.persona.id: summary for summary in persona_stats
        }

        if not bots:
            text = "🚫 Brak aktywnych botów. Wybierz „Dodaj bota”, aby rozpocząć."
        else:
            lines = ["<b>Aktywne boty:</b>"]
            for bot_entry in bots:
                persona_name = bot_entry.persona.name if bot_entry.persona else "—"
                lines.append(
                    f"• <b>{bot_entry.display_name}</b> (persona: <i>{persona_name}</i>, ID: <code>{bot_entry.id}</code>)"
                )
                if bot_entry.persona_id in stats_by_persona:
                    summary = stats_by_persona[bot_entry.persona_id]
                    identity_note = _format_identity_summary(
                        summary.active_identities, summary.total_identities
                    )
                else:
                    identity_note = "brak tożsamości"
                lines.append(f"    ↳ Tożsamości: {identity_note}")
            text = "\n".join(lines)

        await _safe_callback_answer(callback)
        if callback.message:
            await callback.message.answer(text, reply_markup=_main_menu_keyboard().as_markup())

    def _snapshot_submission(submission: Submission) -> dict[str, Any]:
        return {
            "id": submission.id,
            "persona_id": submission.persona_id,
            "persona_name": submission.persona.name if submission.persona else None,
            "submitted_by_user_id": submission.submitted_by_user_id,
            "submitted_chat_id": submission.submitted_chat_id,
            "submitted_by_username": submission.submitted_by_username,
            "submitted_by_name": submission.submitted_by_name,
            "media_type": submission.media_type.value if isinstance(submission.media_type, MediaType) else str(submission.media_type),
            "text_content": submission.text_content or "",
            "file_id": submission.file_id,
            "created_at": submission.created_at.isoformat(),
            "identity_check": _build_identity_snapshot(submission),
        }

    async def _fetch_pending_snapshots(
        *, exclude_ids: Optional[Iterable[int]] = None
    ) -> tuple[list[dict[str, Any]], int]:
        persona_filter = current_persona_id if current_persona_id is not None else None
        async with get_session() as session:
            total_pending = await moderation_service.count_pending_submissions(
                session, persona_id=persona_filter
            )
            submissions = await moderation_service.list_pending_submissions(
                session,
                persona_id=persona_filter,
                limit=MAX_PENDING_PREVIEW,
                exclude_ids=exclude_ids,
            )
        return [_snapshot_submission(item) for item in submissions], total_pending

    async def _compose_submission_view(
        snapshot: dict[str, Any],
        *,
        queue_size: Optional[int] = None,
        preview_limit: Optional[int] = None,
    ) -> tuple[str, InlineKeyboardMarkup, MediaType]:
        try:
            created_at_dt = datetime.fromisoformat(snapshot["created_at"])
            created_at_text = created_at_dt.strftime("%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            created_at_text = snapshot.get("created_at", "")

        persona_name = snapshot.get("persona_name") or (await _ensure_persona_details())[0]
        persona_label_source = (
            persona_name
            if persona_name
            else snapshot.get("persona_id")
            or current_persona_id
            or "—"
        )
        persona_label = html.escape(str(persona_label_source))

        media_type_value = snapshot.get("media_type", MediaType.TEXT.value)
        try:
            media_type_enum = MediaType(media_type_value)
        except ValueError:
            media_type_enum = MediaType.TEXT

        lines = [
            f"<b>Moderacja – zgłoszenie #{snapshot['id']}</b>",
            f"Persona: <i>{persona_label}</i>",
            f"Użytkownik: <code>{snapshot.get('submitted_by_user_id')}</code>",
            f"Czat: <code>{snapshot.get('submitted_chat_id')}</code>",
            f"Typ: <code>{media_type_enum.value}</code>",
            f"Zgłoszono: {created_at_text}",
        ]

        if queue_size is not None:
            if queue_size == 1:
                queue_line = "W kolejce: 1 zgłoszenie (łącznie z tym wpisem)."
            else:
                queue_line = f"W kolejce: {queue_size} zgłoszeń."
            lines.append(queue_line)
            if preview_limit is not None and queue_size > preview_limit:
                lines.append(
                    f"Wyświetlam {preview_limit} najstarszych wpisów do moderacji."
                )

        username_value = snapshot.get("submitted_by_username")
        if username_value:
            username_clean = username_value[1:] if username_value.startswith("@") else username_value
            if username_clean:
                lines.append(f"Alias: <code>@{html.escape(username_clean)}</code>")

        display_name_value = snapshot.get("submitted_by_name")
        if display_name_value:
            lines.append(f"Nazwa: <i>{html.escape(display_name_value)}</i>")

        identity_info = snapshot.get("identity_check") or {}
        identity_matched = identity_info.get("matched")
        matched_fields = identity_info.get("matched_fields") or []
        if identity_matched:
            field_text = _format_identity_fields(matched_fields)
            suffix = f" ({field_text})" if field_text else ""
            lines.append(f"Tożsamość: ✅ potwierdzono{suffix}.")
            matched_identity_desc = identity_info.get("matched_identity")
            if matched_identity_desc:
                lines.append(f"Źródło dopasowania: <i>{html.escape(matched_identity_desc)}</i>")
        else:
            available = identity_info.get("available") or []
            partial = identity_info.get("partial") or []
            if not available:
                lines.append("Tożsamość: ⚠️ brak zdefiniowanych tożsamości dla tej persony.")
            else:
                lines.append("Tożsamość: ❌ brak zgodności z zapisanymi tożsamościami.")
                details_added = False
                if partial:
                    lines.append("")
                    lines.append("Częściowe dopasowania:")
                    for item in partial:
                        descriptor_text = item.get("identity")
                        fields = item.get("fields") or []
                        field_text = _format_identity_fields(fields)
                        if descriptor_text and field_text:
                            lines.append(
                                f"• {html.escape(descriptor_text)} ({html.escape(field_text)})"
                            )
                        elif descriptor_text:
                            lines.append(f"• {html.escape(descriptor_text)}")
                    details_added = True
                if available:
                    if not details_added:
                        lines.append("")
                    lines.append("Zdefiniowane tożsamości:")
                    for descriptor_text in available:
                        lines.append(f"• {html.escape(descriptor_text)}")

        text_content = snapshot.get("text_content") or ""
        if text_content.strip():
            lines.append("")
            lines.append(f"<blockquote>{html.escape(text_content.strip())}</blockquote>")

        keyboard = InlineKeyboardBuilder()
        submission_id = snapshot["id"]
        keyboard.button(text="✅ Dodaj", callback_data=f"moderation:approve:{submission_id}")
        keyboard.button(text="❌ Odrzuć", callback_data=f"moderation:reject:{submission_id}")
        keyboard.button(text="⏭ Pomiń", callback_data=f"moderation:skip:{submission_id}")
        keyboard.button(text="↩️ Menu", callback_data="menu:main")
        keyboard.adjust(2, 1, 1)

        return "\n".join(lines), keyboard.as_markup(), media_type_enum

    async def _send_submission_preview(
        message: Message,
        snapshot: dict[str, Any],
        *,
        queue_size: Optional[int] = None,
        preview_limit: Optional[int] = None,
    ) -> None:
        text, keyboard_markup, media_type_enum = await _compose_submission_view(
            snapshot, queue_size=queue_size, preview_limit=preview_limit
        )
        file_id = snapshot.get("file_id")

        if file_id:
            caption = f"Zgłoszenie #{snapshot['id']} – podgląd"
            try:
                if media_type_enum == MediaType.IMAGE:
                    await message.answer_photo(file_id, caption=caption)
                elif media_type_enum == MediaType.AUDIO:
                    await message.answer_audio(file_id, caption=caption)
            except TelegramBadRequest:
                pass

        await message.answer(text, reply_markup=keyboard_markup)

    async def _notify_submission(message_bot: Bot, chat_id: int, snapshot: dict[str, Any]) -> None:
        text, keyboard_markup, media_type_enum = await _compose_submission_view(snapshot)
        file_id = snapshot.get("file_id")

        if file_id:
            caption = f"Zgłoszenie #{snapshot['id']} – podgląd"
            try:
                if media_type_enum == MediaType.IMAGE:
                    await message_bot.send_photo(chat_id, file_id, caption=caption)
                elif media_type_enum == MediaType.AUDIO:
                    await message_bot.send_audio(chat_id, file_id, caption=caption)
            except TelegramBadRequest:
                pass

        await message_bot.send_message(chat_id, text, reply_markup=keyboard_markup)

    async def _show_next_submission(
        target: Message | CallbackQuery,
        state: FSMContext,
        *,
        reset_skip: bool = False,
        announce_queue: bool = False,
    ) -> None:
        message_obj: Optional[Message]
        if isinstance(target, CallbackQuery):
            await _safe_callback_answer(target)
            message_obj = target.message
        else:
            message_obj = target

        if message_obj is None:
            return

        data = await state.get_data()
        skipped_ids = set()
        if not reset_skip:
            skipped_ids = set(int(x) for x in data.get("moderation_skipped", []))

        snapshots, total_pending = await _fetch_pending_snapshots(
            exclude_ids=skipped_ids if skipped_ids else None
        )

        if announce_queue:
            summary_text, summary_markup = _compose_queue_summary_message(
                snapshots, total_pending
            )
            await message_obj.answer(summary_text, reply_markup=summary_markup)
            if total_pending == 0:
                await state.update_data(
                    moderation_current_submission=None,
                    moderation_current_snapshot=None,
                    moderation_skipped=[],
                )
                return

        for snapshot in snapshots:
            if snapshot["id"] in skipped_ids:
                continue
            skipped_ids.discard(snapshot["id"])
            await state.update_data(
                moderation_current_submission=snapshot["id"],
                moderation_current_snapshot=snapshot,
                moderation_skipped=list(skipped_ids),
            )
            await _send_submission_preview(
                message_obj,
                snapshot,
                queue_size=total_pending,
                preview_limit=MAX_PENDING_PREVIEW,
            )
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
        await _show_next_submission(
            callback, state, reset_skip=True, announce_queue=True
        )

    @admin_router.callback_query(lambda c: c.data is not None and c.data.startswith("moderation:approve:"))
    async def handle_moderation_approve(callback: CallbackQuery, state: FSMContext) -> None:
        submission_id_raw = (callback.data or "").rsplit(":", 1)[-1]
        try:
            submission_id = int(submission_id_raw)
        except ValueError:
            await _safe_callback_answer(callback, "Niepoprawne zgłoszenie.", show_alert=True)
            return

        async with get_session() as session:
            submission = await moderation_service.get_submission_by_id(session, submission_id)
            if submission is None or submission.status != ModerationStatus.PENDING:
                await _safe_callback_answer(
                    callback,
                    "To zgłoszenie zostało już przetworzone.",
                    show_alert=True,
                )
                await state.update_data(moderation_skipped=[])
                await _show_next_submission(callback, state, reset_skip=True)
                return
            identity_result = identities_service.evaluate_submission_identity(submission)
            if not identity_result.matched:
                if not identity_result.descriptors:
                    reason = "Nie można zatwierdzić – brak zdefiniowanych tożsamości dla tej persony."
                else:
                    reason = "Nie można zatwierdzić – nadawca nie pasuje do zapisanych tożsamości."
                    if identity_result.partial_matches:
                        descriptor, fields = identity_result.partial_matches[0]
                        descriptor_text = identities_service.describe_identity(descriptor)
                        field_text = _format_identity_fields(fields)
                        if descriptor_text and field_text:
                            reason += f" Najbliższe dopasowanie: {descriptor_text} ({field_text})."
                await _safe_callback_answer(callback, reason, show_alert=True)
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

        await _safe_callback_answer(callback, "Zgłoszenie zatwierdzone.", show_alert=False)

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
            await _safe_callback_answer(callback, "Niepoprawne zgłoszenie.", show_alert=True)
            return

        async with get_session() as session:
            submission = await moderation_service.get_submission_by_id(session, submission_id)
            if submission is None or submission.status != ModerationStatus.PENDING:
                await _safe_callback_answer(
                    callback,
                    "To zgłoszenie zostało już przetworzone.",
                    show_alert=True,
                )
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
                action=ModerationStatus.REJECTED,
                notes=None,
            )
            submitted_chat_id = submission.submitted_chat_id
            await session.commit()

        await _safe_callback_answer(callback, "Zgłoszenie odrzucone.", show_alert=False)

        if (
            submitted_chat_id
            and callback.message is not None
            and submitted_chat_id != callback.message.chat.id
        ):
            try:
                await callback.message.bot.send_message(
                    submitted_chat_id,
                    "❌ Twoja propozycja została odrzucona.",
                )
            except TelegramBadRequest:
                pass

        await state.update_data(moderation_skipped=[])
        await _show_next_submission(callback, state, reset_skip=True)

    @admin_router.callback_query(lambda c: c.data is not None and c.data.startswith("moderation:skip:"))
    async def handle_moderation_skip(callback: CallbackQuery, state: FSMContext) -> None:
        submission_id_raw = (callback.data or "").rsplit(":", 1)[-1]
        try:
            submission_id = int(submission_id_raw)
        except ValueError:
            await _safe_callback_answer(callback, "Niepoprawne zgłoszenie.", show_alert=True)
            return

        data = await state.get_data()
        skipped = set(int(x) for x in data.get("moderation_skipped", []))
        skipped.add(submission_id)
        await state.update_data(moderation_skipped=list(skipped))
        await _safe_callback_answer(callback, "Pominięto.")
        await _show_next_submission(callback, state)

    @admin_router.callback_query(F.data == "menu:edit_bot")
    async def handle_edit_bot(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        async with get_session() as session:
            bots = await bots_service.list_bots(session)

        if not bots:
            await _safe_callback_answer(callback)
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
        await _safe_callback_answer(callback)
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
            await _safe_callback_answer(
                callback,
                "Niepoprawny identyfikator bota.",
                show_alert=True,
            )
            return

        async with get_session() as session:
            bot_record = await bots_service.get_bot_by_id(session, bot_id)

        if bot_record is None:
            await _safe_callback_answer(
                callback,
                "Nie znaleziono bota. Odśwież listę i spróbuj ponownie.",
                show_alert=True,
            )
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
        await _safe_callback_answer(callback)
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
            persona_stats = await personas_service.list_personas_with_identity_stats(session)

        data = await state.get_data()
        current_persona_id = data.get("current_persona_id")
        current_persona_name = data.get("current_persona_name", "—")

        if persona_stats:
            await state.update_data(
                persona_choices=[
                    {
                        "id": summary.persona.id,
                        "name": summary.persona.name,
                        "language": summary.persona.language,
                        "active_identities": summary.active_identities,
                        "total_identities": summary.total_identities,
                    }
                    for summary in persona_stats
                ]
            )
            keyboard_builder = InlineKeyboardBuilder()
            for summary in persona_stats:
                persona = summary.persona
                prefix = "⭐ " if persona.id == current_persona_id else ""
                hint = _format_identity_summary(summary.active_identities, summary.total_identities)
                keyboard_builder.button(
                    text=f"{prefix}{persona.name} ({persona.language}) · {hint}",
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
        await _safe_callback_answer(callback)
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
            await _safe_callback_answer(callback, "Niepoprawna persona.", show_alert=True)
            return

        data = await state.get_data()
        persona_choices = data.get("persona_choices", [])
        persona_info = next((item for item in persona_choices if item["id"] == persona_id), None)
        if persona_info is None:
            await _safe_callback_answer(
                callback,
                "Nie znaleziono persony. Spróbuj ponownie.",
                show_alert=True,
            )
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
        await _safe_callback_answer(callback)
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
            persona_stats = await personas_service.list_personas_with_identity_stats(session)

        if persona_stats:
            await state.update_data(
                persona_choices=[
                    {
                        "id": summary.persona.id,
                        "name": summary.persona.name,
                        "language": summary.persona.language,
                        "active_identities": summary.active_identities,
                        "total_identities": summary.total_identities,
                    }
                    for summary in persona_stats
                ]
            )
            keyboard_builder = InlineKeyboardBuilder()
            for summary in persona_stats:
                persona = summary.persona
                hint = _format_identity_summary(summary.active_identities, summary.total_identities)
                keyboard_builder.button(
                    text=f"{persona.name} ({persona.language}) · {hint}",
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
        await _safe_callback_answer(callback)
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
            await _safe_callback_answer(callback, "Niepoprawna persona.", show_alert=True)
            return

        persona_info = next((item for item in persona_choices if item["id"] == persona_id), None)
        if persona_info is None:
            await _safe_callback_answer(
                callback,
                "Nie znaleziono persony. Spróbuj ponownie.",
                show_alert=True,
            )
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
                await _safe_callback_answer(
                    target,
                    "Brak wymaganych danych – spróbuj ponownie.",
                    show_alert=True,
                )
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
                    await _safe_callback_answer(target, str(exc), show_alert=True)
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
            await _safe_callback_answer(target)
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
                await _safe_callback_answer(
                    target,
                    "Brak wybranego bota.",
                    show_alert=True,
                )
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
                    await _safe_callback_answer(
                        target,
                        "Nie znaleziono bota.",
                        show_alert=True,
                    )
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
                    await _safe_callback_answer(target, str(exc), show_alert=True)
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
            await _safe_callback_answer(target)
            if target.message:
                await target.message.answer(summary, reply_markup=_main_menu_keyboard().as_markup())
        else:
            await target.answer(summary, reply_markup=_main_menu_keyboard().as_markup())

    async def _get_bot_identity(bot_instance: Optional[Bot] = None) -> tuple[int, Optional[str]]:
        nonlocal bot
        if bot_instance is None:
            bot_instance = bot

        cache: dict[Any, tuple[int, Optional[str]]]
        if not hasattr(_get_bot_identity, "_cache"):
            cache = {}
            setattr(_get_bot_identity, "_cache", cache)
        else:
            cache = getattr(_get_bot_identity, "_cache")

        cache_key: Any
        token = getattr(bot_instance, "token", None)
        cache_key = token or id(bot_instance)

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        profile = await bot_instance.get_me()
        username = profile.username.lower() if profile.username else None
        cached_value = (profile.id, username)
        cache[cache_key] = cached_value
        return cached_value

    async def _is_message_from_current_bot(message: Message) -> bool:
        user = message.from_user
        if user is None or not user.is_bot:
            return False
        bot_id, _ = await _get_bot_identity(message.bot)
        return user.id == bot_id

    def _strip_bot_mentions(text: str, username: Optional[str]) -> str:
        if not text:
            return ""

        cleaned = text
        if username:
            mention_pattern = re.compile(rf"@{re.escape(username)}", re.IGNORECASE)
            cleaned = mention_pattern.sub(" ", cleaned)
        cleaned = re.sub(r"/[-_\w]+(?:@[-_\w]+)?", " ", cleaned)
        return " ".join(cleaned.split())

    def _has_forward_metadata(message: Message) -> bool:
        if getattr(message, "forward_date", None):
            return True

        forward_related_attributes = (
            "forward_origin",
            "forward_from",
            "forward_from_chat",
            "forward_sender_name",
            "forward_signature",
            "forward_from_message_id",
        )
        for attribute in forward_related_attributes:
            if getattr(message, attribute, None) is not None:
                return True
        return False

    def _describe_message(message: Message) -> str:
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
        chat_type = getattr(chat, "type", None)
        user = getattr(message, "from_user", None)
        user_id = getattr(user, "id", None)
        username = getattr(user, "username", None)
        full_name = getattr(user, "full_name", None)
        forward_flag = _has_forward_metadata(message)
        return (
            "message_id=%s chat_id=%s chat_type=%s from_id=%s username=%s name=%s forward=%s"
            % (
                getattr(message, "message_id", None),
                chat_id,
                chat_type,
                user_id,
                username,
                full_name,
                forward_flag,
            )
        )

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

        bot_id, username = await _get_bot_identity()

        reply = message.reply_to_message
        if (
            reply
            and reply.from_user is not None
            and reply.from_user.is_bot
            and reply.from_user.id == bot_id
        ):
            return True

        normalized_username = username.lower() if username else None

        def _check_entities(entities: Optional[list], text: str) -> bool:
            if not entities or not text:
                return False
            for entity in entities:
                snippet = text[entity.offset : entity.offset + entity.length]
                entity_type = normalize_entity_type(getattr(entity, "type", ""))
                if (
                    entity_type.endswith("mention")
                    and normalized_username
                    and snippet.lower() == f"@{normalized_username}"
                ):
                    return True
                if entity_type.endswith("text_mention") and getattr(entity, "user", None):
                    if entity.user.id == bot_id:
                        return True
                if entity_type.endswith("bot_command"):
                    command = snippet.lower()
                    if normalized_username and command.endswith(f"@{normalized_username}"):
                        return True
                    if chat_type == "private":
                        return True
            return False

        if _has_forward_metadata(message):
            logger.debug(
                "Wiadomość %s zawiera metadane przekazania – nie traktujemy jej jako wywołania bota.",
                _describe_message(message),
            )
            # Przekazane wiadomości traktujemy jak zgłoszenia do moderacji,
            # niezależnie od ich treści lub oznaczeń w tekście.
            return False

        if _check_entities(message.entities, message.text or ""):
            return True
        if _check_entities(message.caption_entities, message.caption or ""):
            return True

        if normalized_username and f"@{normalized_username}" in content.lower():
            return True

        if chat_type == "private":
            # W prywatnych wiadomościach brak wyraźnej komendy traktujemy jako zgłoszenie cytatu.
            return False

        return False

    async def _reply_with_quote(message: Message, quote: Quote) -> None:
        text_payload = (quote.text_content or "").strip() or "…"
        reply_target = resolve_reply_target(message)

        async def _send_text() -> None:
            if reply_target is not None:
                await reply_target.reply(text_payload)
            else:
                await message.answer(text_payload)

        async def _send_photo() -> None:
            if reply_target is not None:
                await reply_target.reply_photo(
                    quote.file_id,
                    caption=text_payload if quote.text_content else None,
                )
            else:
                await message.answer_photo(
                    quote.file_id,
                    caption=text_payload if quote.text_content else None,
                )

        async def _send_audio() -> None:
            if reply_target is not None:
                await reply_target.reply_audio(
                    quote.file_id,
                    caption=text_payload if quote.text_content else None,
                )
            else:
                await message.answer_audio(
                    quote.file_id,
                    caption=text_payload if quote.text_content else None,
                )

        try:
            if quote.media_type == MediaType.TEXT or not quote.file_id:
                await _send_text()
            elif quote.media_type == MediaType.IMAGE:
                await _send_photo()
            elif quote.media_type == MediaType.AUDIO:
                await _send_audio()
            else:
                await _send_text()
        except TelegramBadRequest:
            if reply_target is not None:
                await reply_target.reply(text_payload)
            else:
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
        if await _is_message_from_current_bot(message):
            return

        logger.debug("Odebrano potencjalne wywołanie publiczne: %s", _describe_message(message))

        if not await _is_direct_invocation(message):
            logger.debug(
                "Wiadomość %s nie została zakwalifikowana jako wywołanie bota – przekazujemy dalej.",
                _describe_message(message),
            )
            raise SkipHandler()

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

        logger.debug("Odebrano wiadomość od użytkownika: %s", _describe_message(message))

        if await _is_message_from_current_bot(message):
            logger.debug(
                "Pomijamy wiadomość %s, ponieważ pochodzi od bieżącego bota.",
                _describe_message(message),
            )
            return

        text_content: Optional[str] = None
        file_id: Optional[str] = None
        media_type_enum: Optional[MediaType] = None
        submitted_by_username: Optional[str] = message.from_user.username
        submitted_by_name: Optional[str] = message.from_user.full_name

        if message.text:
            text_content = message.text.strip()
            if not text_content:
                await message.answer("Wyślij proszę treść cytatu w wiadomości tekstowej.")
                logger.debug(
                    "Wiadomość %s została odrzucona – pusta treść tekstowa.",
                    _describe_message(message),
                )
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
            logger.debug(
                "Wiadomość %s została odrzucona – nieobsługiwany typ treści.",
                _describe_message(message),
            )
            return

        if media_type_enum is None:
            await message.answer("Nie udało się rozpoznać typu wiadomości.")
            logger.debug(
                "Wiadomość %s została odrzucona – nie rozpoznano typu wiadomości.",
                _describe_message(message),
            )
            return

        async with get_session() as session:
            submission = await moderation_service.create_submission(
                session,
                persona_id=current_persona_id,
                submitted_by_user_id=message.from_user.id,
                submitted_chat_id=message.chat.id,
                submitted_by_username=submitted_by_username,
                submitted_by_name=submitted_by_name,
                media_type=media_type_enum,
                text_content=text_content,
                file_id=file_id,
            )
            await session.commit()
            submission_snapshot = _snapshot_submission(submission)

        logger.info(
            "Przekazano wiadomość %s do kolejki moderacyjnej jako zgłoszenie #%s.",
            _describe_message(message),
            submission.id,
        )

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
            if submitted_by_username:
                username_clean = submitted_by_username[1:] if submitted_by_username.startswith("@") else submitted_by_username
                if username_clean:
                    summary_lines.append(f"Alias: <code>@{html.escape(username_clean)}</code>")
            if submitted_by_name:
                summary_lines.append(f"Nazwa: <i>{html.escape(submitted_by_name)}</i>")
            if preview:
                summary_lines.append("")
                summary_lines.append(html.escape(preview[:200]))
            snapshot = submission_snapshot
            if persona_name:
                snapshot["persona_name"] = persona_name
            try:
                await _notify_submission(message.bot, admin_chat_id, snapshot)
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
