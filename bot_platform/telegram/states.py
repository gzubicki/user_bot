"""FSM states used by Telegram handlers."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddBotStates(StatesGroup):
    waiting_token = State()
    waiting_display_name = State()
    choosing_persona = State()
    waiting_persona_name = State()
    waiting_persona_description = State()
    waiting_persona_language = State()


class EditBotStates(StatesGroup):
    choosing_bot = State()
    waiting_token = State()
    waiting_display_name = State()
    choosing_persona = State()
    waiting_persona_name = State()
    waiting_persona_description = State()
    waiting_persona_language = State()


class ModerationStates(StatesGroup):
    reviewing = State()


class IdentityStates(StatesGroup):
    choosing_persona = State()
    managing_persona = State()
    waiting_identity_payload = State()
    choosing_identity_to_remove = State()
