import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot
from config import TIMEZONE, BOT_TOKEN
from handlers.shift import auto_end_all_shifts
from db.mongo import get_db

logger = logging.getLogger(__name__)

# Флаг для предотвращения повторных запусков
_last_run_date = None

async def cleanup_old_locations():
    """
    Удаляет все записи из коллекции location старше 7 дней
    Вызывается планировщиком в 23:00
    """
    logger.info("[SCHEDULER] 🗑️ Начало очистки старых записей из коллекции location")
    
    try:
        db = await get_db()
        
        # Вычисляем дату 7 дней назад
        now = datetime.now(TIMEZONE)
        date_7_days_ago = now - timedelta(days=7)
        date_7_days_ago_iso = date_7_days_ago.isoformat()
        
        logger.debug(f"[SCHEDULER] Удаление записей старше {date_7_days_ago_iso}")
        
        # Удаляем все записи где timestamp < date_7_days_ago
        result = await db.locations.delete_many({
            "timestamp": {"$lt": date_7_days_ago_iso}
        })
        
        deleted_count = result.deleted_count
        logger.info(f"[SCHEDULER] ✅ Очистка завершена: удалено {deleted_count} записей старше 7 дней")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"[SCHEDULER] ❌ Ошибка при очистке старых записей location: {e}", exc_info=True)
        raise

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
                    logger.info(f"[SCHEDULER] 🕐 Наступило 23:00 ({TIMEZONE}), запускаем завершение всех смен и очистку location")
                    _last_run_date = current_date
                    
                    # Завершение всех смен
                    try:
                        await auto_end_all_shifts(bot)
                        logger.info("[SCHEDULER] ✅ Завершение всех смен выполнено")
                    except Exception as e:
                        logger.error(f"[SCHEDULER] ❌ Ошибка при завершении смен: {e}", exc_info=True)
                    
                    # Очистка старых записей location
                    try:
                        await cleanup_old_locations()
                    except Exception as e:
                        logger.error(f"[SCHEDULER] ❌ Ошибка при очистке location: {e}", exc_info=True)
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

