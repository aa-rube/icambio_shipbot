import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import start, shift, orders, photo, errors, admin, location
from utils.logger import setup_logging
from db.mongo import init_indexes
from config import BOT_TOKEN, API_HOST, API_PORT
import uvicorn
from api_server import app

async def run_api_server():
    """Запускает FastAPI сервер"""
    config = uvicorn.Config(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    await server.serve()

async def run_bot():
    """Запускает Telegram бота"""
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

    try:
        # Добавляем edited_message в allowed_updates для обработки лайв-локации
        await dp.start_polling(bot, allowed_updates=["message", "edited_message", "callback_query"])
    finally:
        await bot.session.close()

async def main():
    setup_logging(logging.INFO)
    await init_indexes()

    # Запускаем бота и API сервер параллельно
    await asyncio.gather(
        run_bot(),
        run_api_server()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
