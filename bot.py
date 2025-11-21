import asyncio
import logging
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import start, shift, orders, photo, errors, admin, location, report
from utils.logger import setup_logging
from db.mongo import init_indexes
from config import BOT_TOKEN, API_HOST, API_PORT
import uvicorn
from api_server import app
from utils.scheduler import run_scheduler

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
    import logging
    logger = logging.getLogger(__name__)
    logger.info("[BOT] Initializing bot...")
    
    bot = Bot(BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(shift.router)
    dp.include_router(location.router)
    dp.include_router(report.router)  # Регистрируем раньше orders, чтобы команда /report обрабатывалась раньше
    dp.include_router(orders.router)
    dp.include_router(photo.router)
    dp.include_router(errors.router)

    try:
        logger.info("[BOT] Starting polling...")
        # Добавляем edited_message в allowed_updates для обработки лайв-локации
        await dp.start_polling(bot, allowed_updates=["message", "edited_message", "callback_query"])
    finally:
        await bot.session.close()
        logger.info("[BOT] Bot stopped")

# Глобальные переменные для управления задачами
_scheduler_task = None
_bot_task = None
_api_task = None
_shutdown_flag = False

def signal_handler(signum, frame):
    """Обработчик сигналов для корректной остановки"""
    global _shutdown_flag
    logger = logging.getLogger(__name__)
    logger.info(f"[BOT] Получен сигнал {signum}, инициируем остановку...")
    _shutdown_flag = True

async def main():
    global _scheduler_task, _bot_task, _api_task, _shutdown_flag
    
    logger = setup_logging(logging.INFO)
    logger.info("[BOT] Starting bot, API server and scheduler...")
    await init_indexes()

    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Запускаем все задачи
        _bot_task = asyncio.create_task(run_bot())
        _api_task = asyncio.create_task(run_api_server())
        _scheduler_task = asyncio.create_task(run_scheduler())
        
        logger.info("[BOT] Все сервисы запущены, ожидание завершения...")
        
        # Создаем задачу для проверки флага остановки
        async def check_shutdown():
            while not _shutdown_flag:
                await asyncio.sleep(1)
        
        shutdown_checker = asyncio.create_task(check_shutdown())
        
        # Ждем сигнала остановки или завершения одной из задач
        done, pending = await asyncio.wait(
            [_bot_task, _api_task, _scheduler_task, shutdown_checker],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Отменяем проверку флага
        shutdown_checker.cancel()
        try:
            await shutdown_checker
        except asyncio.CancelledError:
            pass
        
        # Если получили сигнал остановки, отменяем все задачи
        if _shutdown_flag:
            logger.info("[BOT] Получен сигнал остановки, отменяем все задачи...")
            for task in [_bot_task, _api_task, _scheduler_task]:
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        
        # Ждем завершения всех задач с таймаутом
        logger.info("[BOT] Ожидание завершения задач...")
        for task in [_bot_task, _api_task, _scheduler_task]:
            if task and not task.done():
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    logger.warning(f"[BOT] Задача не завершилась в срок")
        
    except Exception as e:
        logger.error(f"[BOT] Критическая ошибка: {e}", exc_info=True)
        raise
    finally:
        logger.info("[BOT] Все сервисы остановлены")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).info("[BOT] Прервано пользователем")
    except Exception as e:
        logging.getLogger(__name__).error(f"[BOT] Фатальная ошибка: {e}", exc_info=True)
        sys.exit(1)
