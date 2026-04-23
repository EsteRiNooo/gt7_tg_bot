from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

from bot.keyboards import (
    CALLBACK_MENU_ABOUT,
    CALLBACK_MENU_RACES,
    CALLBACK_MENU_SETTINGS,
    main_menu_keyboard,
)
from scheduler import send_weekly_races
from services.formatting import get_week_range
from services.lfm_series_cards import build_lfm_simulation_messages
from services.races import get_all_races
from services.subscribers import add_subscriber
from services.track_images import find_track_image

router = Router()
LMU_MAX_CARDS = 10


def _ordered_races(races: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    race_order = {"Race A": 0, "Race B": 1, "Race C": 2}
    return sorted(races, key=lambda race: race_order.get((race.get("title") or "").strip(), 99))


def _parse_starts_in_minutes(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"now", "0m"}:
        return 0

    total = 0
    number = ""
    had_unit = False
    for ch in text:
        if ch.isdigit():
            number += ch
            continue
        if ch in {"d", "h", "m"} and number:
            amount = int(number)
            if ch == "d":
                total += amount * 1440
            elif ch == "h":
                total += amount * 60
            else:
                total += amount
            had_unit = True
            number = ""
    if had_unit:
        return total
    if text.isdigit():
        return int(text)
    return None


def _group_icon(minutes: int | None) -> str:
    if minutes is not None and minutes <= 15:
        return "🔥"
    if minutes is not None and minutes <= 120:
        return "⚡"
    return "📅"


def _access_line(requirements: dict | None) -> str | None:
    if not isinstance(requirements, dict):
        return None
    license_value = requirements.get("license")
    safety_value = requirements.get("safety")
    license_text = str(license_value).strip() if license_value is not None else ""
    safety_text = str(safety_value).strip() if safety_value is not None else ""
    if not license_text and not safety_text:
        return None

    low = license_text.lower()
    icon = "🟡"
    if "rookie" in low:
        icon = "🟢"
    elif "gold" in low:
        icon = "🟠"
    elif "bronze" in low:
        icon = "🔴"

    if license_text and safety_text:
        return f"{icon} {license_text} (SR {safety_text})"
    if license_text:
        return f"{icon} {license_text}"
    return f"{icon} SR {safety_text}"


def map_lmu_sr(sr: str) -> str | None:
    """LMU-only: tier label from Safety Rank multiplier (safetyRank)."""
    if not sr:
        return None
    s = sr.strip()
    if s.startswith("1.0"):
        return "Bronze"
    if s.startswith("1.3"):
        return "Silver"
    if s.startswith("1.5") or s.startswith("2.0"):
        return "Gold"
    return None


def _lmu_safety_rank_for_display(race: dict[str, object]) -> str | None:
    """Use API safetyRank only (not safetyRating/sr fallbacks)."""
    for key in ("safety_rank", "safetyRank"):
        raw = race.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def get_sr_emoji(tier: str) -> str:
    """LMU Safety Rank line: emoji by tier label (SR-mapped Bronze/Silver/Gold)."""
    if tier == "Bronze":
        return "🟢"
    if tier == "Silver":
        return "🟡"
    if tier == "Gold":
        return "🟠"
    return "⚪"


def _format_lmu_tier(tier: str, sr: str | None = None) -> str:
    clean_tier = tier.strip()
    display_tier = clean_tier.title()
    sr_text = (sr or "").strip()
    if sr_text and not sr_text.lower().startswith("sr"):
        sr_text = f"SR {sr_text}"
    suffix = f" ({sr_text})" if sr_text else ""

    emoji = get_sr_emoji(display_tier)
    return f"{emoji} {display_tier}{suffix}"


def _extract_lmu_tier_line(race: dict[str, object]) -> str | None:
    sr = _lmu_safety_rank_for_display(race)
    if not sr:
        return None

    tier = map_lmu_sr(sr)
    if tier:
        return _format_lmu_tier(tier, sr)
    return f"SR {sr}"


def _group_and_sort_cards(cards: list[dict[str, object]]) -> list[dict[str, object]]:
    now_cards: list[dict[str, object]] = []
    soon_cards: list[dict[str, object]] = []
    later_cards: list[dict[str, object]] = []
    for card in cards:
        starts = card.get("starts_in_minutes")
        starts_minutes = starts if isinstance(starts, int) else None
        if starts_minutes is not None and starts_minutes <= 15:
            now_cards.append(card)
        elif starts_minutes is not None and starts_minutes <= 120:
            soon_cards.append(card)
        else:
            later_cards.append(card)

    def _sort_key(card: dict[str, object]) -> tuple[int, str]:
        starts = card.get("starts_in_minutes")
        starts_minutes = starts if isinstance(starts, int) else 10**9
        title = str(card.get("title") or "").strip().lower()
        return (starts_minutes, title)

    now_cards.sort(key=_sort_key)
    soon_cards.sort(key=_sort_key)
    later_cards.sort(key=_sort_key)
    return now_cards + soon_cards + later_cards


def _gt7_duration(race: dict[str, str | None]) -> str:
    laps = race.get("laps")
    if isinstance(laps, int) and laps > 0:
        return f"{laps}L"
    if isinstance(laps, str) and laps.strip().isdigit() and int(laps.strip()) > 0:
        return f"{int(laps.strip())}L"
    return ""


def _format_gt7_message(races: list[dict[str, str | None]]) -> str:
    cards: list[dict[str, object]] = []
    for race in _ordered_races(races):
        title = (race.get("title") or "Race").strip()
        track = (race.get("track") or "Unknown track").strip()
        class_name = (race.get("class") or "Unknown class").strip()
        duration = _gt7_duration(race)
        car = (race.get("car") or "").strip()
        tires = (race.get("tires") or "").strip()
        parts = [f"🏁 {class_name}"]
        if duration:
            parts.append(duration)
        lines = [
            f"{_group_icon(None)} {title}",
            f"📍 {track}",
            " • ".join(parts),
        ]
        if car and car != class_name:
            lines.append(f"🚗 {car}")
        if tires:
            lines.append(f"🛞 {tires}")
        cards.append({"title": title, "starts_in_minutes": None, "lines": lines})

    cards = _group_and_sort_cards(cards)
    details: list[str] = []
    for index, card in enumerate(cards):
        details.extend(card["lines"])  # type: ignore[arg-type]
        if index < len(cards) - 1:
            details.extend(["", "──────────", ""])

    gt7_header = [
        "#GT7",
        "🏁 GT7 Weekly Races",
        f"📅 {get_week_range()}",
        "",
    ]
    return "\n".join(gt7_header + details).rstrip()


def _format_lmu_message(races: list[dict[str, str | None]]) -> str:
    print(f"[DEBUG] LMU races count BEFORE formatting: {len(races)}")
    lines = ["#LMU", "🏁 Le Mans Ultimate", "📅 Daily & Weekly", ""]
    cards: list[dict[str, object]] = []
    for race in races:
        title = (race.get("title") or "Daily Race").strip()
        track = (race.get("track") or "Unknown track").strip()
        race_class = (race.get("class") or "Unknown class").strip()
        duration = (race.get("duration") or "").strip()
        if duration.isdigit():
            duration = f"{duration}m"
        next_in = race.get("next_start_in")
        starts_in = _parse_starts_in_minutes(next_in)
        class_duration = f"🏁 {race_class} • {duration}" if duration else f"🏁 {race_class}"
        block: list[str] = [
            f"{_group_icon(starts_in)} {title}",
            f"📍 {track}",
            class_duration,
        ]
        req_line = _extract_lmu_tier_line(race)  # type: ignore[arg-type]
        if req_line:
            block.append(req_line)
        if next_in:
            block.append(f"⏱ Starts in {next_in}")
        cards.append(
            {
                "title": title,
                "starts_in_minutes": starts_in,
                "lines": block,
                "tier": race.get("tier"),
            },
        )
        print(f"[LMU PIPELINE] stage=builder tier={race.get('tier')}")

    print(f"[DEBUG] LMU races count AFTER card aggregation: {len(cards)}")
    sorted_cards = _group_and_sort_cards(cards)
    print(f"[DEBUG] LMU races count AFTER grouping/sorting: {len(sorted_cards)}")
    limited_cards = sorted_cards[:LMU_MAX_CARDS]
    print(f"[DEBUG] LMU races count BEFORE final formatting: {len(limited_cards)}")

    for index, card in enumerate(limited_cards):
        lines.extend(card["lines"])  # type: ignore[arg-type]
        if index < len(limited_cards) - 1:
            lines.extend(["", "──────────", ""])

    return "\n".join(lines).rstrip()


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


async def _send_current_races_week(message: Message) -> None:
    results = await get_all_races()
    gt7_source = next((item for item in results if item.get("source") == "gt7"), None)
    lmu_source = next((item for item in results if item.get("source") == "lmu_official"), None)

    gt7_races = gt7_source.get("data") if gt7_source and gt7_source.get("data") else []
    gt7_races = _ordered_races(gt7_races)
    gt7_text = _format_gt7_message(gt7_races)

    image_paths = [find_track_image((race.get("track") or "").strip()) for race in gt7_races]
    valid_image_paths = [path for path in image_paths if path]

    if not valid_image_paths:
        await message.answer(gt7_text)
    else:
        media: list[InputMediaPhoto] = []
        for index, path in enumerate(valid_image_paths):
            photo = FSInputFile(path)
            if index == 0:
                media.append(InputMediaPhoto(media=photo, caption=gt7_text))
            else:
                media.append(InputMediaPhoto(media=photo))

        await message.answer_media_group(media=media)

    lmu_races = lmu_source.get("data") if lmu_source and lmu_source.get("data") else []
    print(f"[DEBUG] LMU races count BEFORE formatting/sending: {len(lmu_races)}")
    if lmu_races:
        lmu_text = _format_lmu_message(lmu_races)
        print("[DEBUG] LMU sending formatted message")
        await message.answer(lmu_text)

    lfm_source = next((item for item in results if item.get("source") == "lfm"), None)
    lfm_flat = lfm_source.get("data") if lfm_source and lfm_source.get("data") else []
    for lfm_block in build_lfm_simulation_messages(lfm_flat):
        await message.answer(lfm_block)


@router.message(Command("current"))
async def current_handler(message: Message) -> None:
    await _send_current_races_week(message)


@router.callback_query(F.data == CALLBACK_MENU_RACES)
async def menu_races_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await _send_current_races_week(callback.message)


@router.callback_query(F.data == CALLBACK_MENU_SETTINGS)
async def menu_settings_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.answer(
        "⚙️ <b>Настройки</b>\n\n"
        "Здесь пока ничего не настраивается. "
        "Подписка на еженедельную рассылку включается автоматически при /start.",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


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
