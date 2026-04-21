import asyncio

from aiogram import Bot, Dispatcher

from services.races_logging import ensure_races_logging_configured

from bot.handlers import router
from config import BOT_TOKEN
from scheduler import create_scheduler


async def main() -> None:
    ensure_races_logging_configured()
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise ValueError("Set your Telegram bot token in config.py")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    scheduler = create_scheduler(bot)
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
