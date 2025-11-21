import asyncio
import logging
from datetime import datetime
from aiogram import Bot
from config import TIMEZONE, BOT_TOKEN
from handlers.shift import auto_end_all_shifts

logger = logging.getLogger(__name__)

# Флаг для предотвращения повторных запусков
_last_run_date = None

async def run_scheduler():
    """
    Планировщик, который проверяет время каждую минуту
    и запускает завершение всех смен в 23:00
    """
    global _last_run_date
    
    logger.info("[SCHEDULER] Планировщик запущен")
    bot = Bot(BOT_TOKEN)
    
    try:
        while True:
            # Получаем текущее время в указанной timezone
            now = datetime.now(TIMEZONE)
            current_hour = now.hour
            current_minute = now.minute
            current_date = now.date()
            
            # Проверяем, наступило ли 23:00
            if current_hour == 23 and current_minute == 0:
                # Проверяем, не запускали ли мы уже сегодня
                if _last_run_date != current_date:
                    logger.info(f"[SCHEDULER] 🕐 Наступило 23:00 ({TIMEZONE}), запускаем завершение всех смен")
                    _last_run_date = current_date
                    
                    try:
                        await auto_end_all_shifts(bot)
                        logger.info("[SCHEDULER] ✅ Завершение всех смен выполнено")
                    except Exception as e:
                        logger.error(f"[SCHEDULER] ❌ Ошибка при завершении смен: {e}", exc_info=True)
                else:
                    logger.debug(f"[SCHEDULER] Завершение смен уже было запущено сегодня ({current_date})")
            
            # Ждем 60 секунд до следующей проверки
            # Используем asyncio.wait_for для возможности прерывания
            try:
                await asyncio.wait_for(asyncio.sleep(60), timeout=60.0)
            except asyncio.TimeoutError:
                # Это нормально, просто продолжаем цикл
                pass
            
    except asyncio.CancelledError:
        logger.info("[SCHEDULER] Планировщик остановлен (отменен)")
        raise
    except Exception as e:
        logger.error(f"[SCHEDULER] ❌ Критическая ошибка в планировщике: {e}", exc_info=True)
        raise
    finally:
        try:
            await bot.session.close()
            logger.debug("[SCHEDULER] Сессия бота закрыта")
        except Exception as e:
            logger.warning(f"[SCHEDULER] Ошибка при закрытии сессии бота: {e}")

