"""Send GT7 + LMU Official + LFM blocks to a chat (Telegram bot API)."""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto

from services.formatting import append_source_errors
from services.lfm_series_cards import build_lfm_simulation_messages
from services.track_images import find_track_image
from services.week_races_messages import format_gt7_week_message, format_lmu_official_week_message, ordered_gt7_races


def _pick_source_data(results: list[dict[str, Any]], source: str) -> list[Any]:
    item = next((r for r in results if r.get("source") == source), None)
    if not item:
        return []
    data = item.get("data")
    return list(data) if isinstance(data, list) else []


async def deliver_filtered_week_to_chat(
    bot: Bot,
    chat_id: int,
    *,
    filtered_results: list[dict[str, Any]],
    source_errors: list[dict[str, str]] | None = None,
) -> None:
    """
    Send race week messages for already-filtered ``get_all_races()``-shaped results.
    Skips empty sections (no header-only GT7 message when races list is empty).
    """
    gt7_races = ordered_gt7_races(_pick_source_data(filtered_results, "gt7"))
    lmu_races = _pick_source_data(filtered_results, "lmu_official")
    lfm_flat = _pick_source_data(filtered_results, "lfm")

    if gt7_races:
        gt7_text = format_gt7_week_message(gt7_races)
        image_paths = [find_track_image((race.get("track") or "").strip()) for race in gt7_races]
        valid_image_paths = [path for path in image_paths if path]

        if not valid_image_paths:
            await bot.send_message(chat_id, gt7_text)
        else:
            media: list[InputMediaPhoto] = []
            for index, path in enumerate(valid_image_paths):
                photo = FSInputFile(path)
                if index == 0:
                    media.append(InputMediaPhoto(media=photo, caption=gt7_text))
                else:
                    media.append(InputMediaPhoto(media=photo))

            await bot.send_media_group(chat_id, media=media)

    if lmu_races:
        lmu_text = format_lmu_official_week_message(lmu_races)
        await bot.send_message(chat_id, lmu_text)

    for lfm_block in build_lfm_simulation_messages(lfm_flat):
        await bot.send_message(chat_id, lfm_block)

    if source_errors:
        err_body = append_source_errors("⚠️", source_errors)
        await bot.send_message(chat_id, err_body, parse_mode="HTML")
