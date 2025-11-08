import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import start, shift, orders, photo, errors, admin, location
from utils.logger import setup_logging
from utils.location_tracker import LocationTracker
from db.mongo import init_indexes
from config import BOT_TOKEN

async def main():
    setup_logging(logging.INFO)
    await init_indexes()

    bot = Bot(BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(shift.router)
    dp.include_router(location.router)
    dp.include_router(orders.router)
    dp.include_router(photo.router)
    dp.include_router(errors.router)

    # Запускаем отслеживание локации
    location_tracker = LocationTracker(bot)
    await location_tracker.start()

    try:
        await dp.start_polling(bot)
    finally:
        # Останавливаем отслеживание локации при остановке бота
        await location_tracker.stop()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
