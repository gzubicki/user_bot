"""Aiogram dispatcher factory and admin chat handlers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

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
from ..services import bots as bots_service
from ..services import personas as personas_service
from .states import AddBotStates, EditBotStates


@dataclass(slots=True)
class DispatcherBundle:
    dispatcher: Dispatcher
    bot: Bot
    moderator_chat_id: int
    bot_id: Optional[int] = None
    display_name: Optional[str] = None


def _main_menu_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Dodaj bota", callback_data="menu:add_bot")
    builder.button(text="📋 Lista botów", callback_data="menu:list_bots")
    builder.button(text="✏️ Edytuj bota", callback_data="menu:edit_bot")
    builder.button(text="🔁 Odśwież tokeny", callback_data="menu:refresh_tokens")
    builder.adjust(1)
    return builder


def build_dispatcher(
    token: str,
    *,
    bot_id: Optional[int] = None,
    display_name: Optional[str] = None,
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

    admin_router = Router(name=f"admin-router-{bot_id or 'default'}")
    admin_router.message.filter(lambda message: _is_admin_chat_id(message.chat.id))
    admin_router.callback_query.filter(
        lambda callback: callback.message is not None and _is_admin_chat_id(callback.message.chat.id)
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

    dispatcher.include_router(admin_router)

    fallback_router = Router(name="fallback-router")
    fallback_router.message.filter(lambda message: not _is_admin_chat_id(message.chat.id))

    @fallback_router.message()
    async def reject_non_admin(message: Message) -> None:
        await message.answer(
            "Ten bot jest przeznaczony wyłącznie do czatu administracyjnego.\n"
            f"Otrzymano wiadomość z czatu <code>{message.chat.id}</code>, "
            f"ale oczekiwany jest <code>{admin_chat_id}</code>."
        )

    dispatcher.include_router(fallback_router)

    return DispatcherBundle(
        dispatcher=dispatcher,
        bot=bot,
        bot_id=bot_id,
        display_name=resolved_display_name,
        moderator_chat_id=moderator_chat_id,
    )


__all__ = ["DispatcherBundle", "build_dispatcher"]
