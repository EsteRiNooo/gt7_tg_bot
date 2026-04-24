from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.user_race_settings import TOGGLE_SOURCE_DEFS

CALLBACK_MENU_RACES = "menu:races"
CALLBACK_MENU_SETTINGS = "menu:settings"
CALLBACK_MENU_ABOUT = "menu:about"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏁 Показать гонки",
                    callback_data=CALLBACK_MENU_RACES,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data=CALLBACK_MENU_SETTINGS,
                ),
                InlineKeyboardButton(
                    text="ℹ️ О боте",
                    callback_data=CALLBACK_MENU_ABOUT,
                ),
            ],
        ],
    )


def settings_sources_keyboard(settings: dict[str, bool]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, label in TOGGLE_SOURCE_DEFS:
        on = settings.get(key, True)
        icon = "✅" if on else "❌"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {label}",
                    callback_data=f"st:{key}",
                ),
            ],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
