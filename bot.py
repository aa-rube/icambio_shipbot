import asyncio
import logging
from aiogram import Bot, Dispatcher
from handlers import start, shift, orders, photo, errors
from utils.logger import setup_logging
from db.mongo import init_indexes
from config import BOT_TOKEN

async def main():
    setup_logging(logging.INFO)
    await init_indexes()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(shift.router)
    dp.include_router(orders.router)
    dp.include_router(photo.router)
    dp.include_router(errors.router)

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
