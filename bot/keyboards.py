from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
