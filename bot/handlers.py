from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards import (
    CALLBACK_MENU_ABOUT,
    CALLBACK_MENU_RACES,
    CALLBACK_MENU_SETTINGS,
    main_menu_keyboard,
    settings_sources_keyboard,
)
from scheduler import send_weekly_races
from services.races import get_all_races
from services.subscribers import add_subscriber
from services.user_race_settings import (
    EMPTY_FILTERED_RACES_MESSAGE,
    SETTINGS_SCREEN_HTML,
    aggregated_results_have_any_races,
    filter_races_by_user_settings,
    get_merged_settings,
    KNOWN_TOGGLE_KEYS,
    toggle_source,
)
from services.week_races_delivery import deliver_filtered_week_to_chat

router = Router()


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    if message.from_user:
        add_subscriber(message.from_user.id)

    text = (
        "Привет! Я бот с расписанием гонок.\n\n"
        "Показываю актуальные гонки текущей недели в "
        "<b>GT7</b>, <b>LMU</b> и <b>LFM</b>.\n\n"
        "Выбери действие в меню ниже или используй команду /current."
    )
    await message.answer(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")


async def _send_current_races_week(message: Message, *, user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else (message.from_user.id if message.from_user else None)

    results = await get_all_races()
    filtered = filter_races_by_user_settings(results, uid)
    if not aggregated_results_have_any_races(filtered):
        await message.answer(EMPTY_FILTERED_RACES_MESSAGE)
        return

    await deliver_filtered_week_to_chat(
        message.bot,
        message.chat.id,
        filtered_results=filtered,
        source_errors=None,
    )


@router.message(Command("current"))
async def current_handler(message: Message) -> None:
    await _send_current_races_week(message)


@router.callback_query(F.data == CALLBACK_MENU_RACES)
async def menu_races_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        uid = callback.from_user.id if callback.from_user else None
        await _send_current_races_week(callback.message, user_id=uid)


@router.callback_query(F.data == CALLBACK_MENU_SETTINGS)
async def menu_settings_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message or not callback.from_user:
        return
    merged = get_merged_settings(callback.from_user.id)
    await callback.message.answer(
        SETTINGS_SCREEN_HTML,
        reply_markup=settings_sources_keyboard(merged),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("st:"))
async def settings_toggle_callback(callback: CallbackQuery) -> None:
    key = callback.data.removeprefix("st:") if callback.data else ""
    if key not in KNOWN_TOGGLE_KEYS:
        await callback.answer("Откройте настройки заново через /start.", show_alert=True)
        return
    if not callback.from_user or not callback.message:
        await callback.answer()
        return

    merged = toggle_source(callback.from_user.id, key)
    await callback.answer()

    try:
        await callback.message.edit_text(
            SETTINGS_SCREEN_HTML,
            reply_markup=settings_sources_keyboard(merged),
            parse_mode="HTML",
        )
    except TelegramBadRequest as err:
        if "message is not modified" in str(err).lower():
            await callback.message.edit_reply_markup(
                reply_markup=settings_sources_keyboard(merged),
            )
        else:
            raise


@router.callback_query(F.data == CALLBACK_MENU_ABOUT)
async def menu_about_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.answer(
        "ℹ️ <b>О боте</b>\n\n"
        "Показываю актуальные гонки недели в Gran Turismo 7 (GT7), "
        "Le Mans Ultimate (LMU) и Low Fuel Motorsport (LFM).\n\n"
        "Команда /current — то же самое, что кнопка «Показать гонки».",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("force_send"))
async def force_send_handler(message: Message) -> None:
    if message.from_user:
        add_subscriber(message.from_user.id)
    await send_weekly_races(bot=message.bot, force=True)
    await message.answer("Weekly update sent.", parse_mode="HTML")
