import asyncio
import logging
from aiogram import Bot
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from db.mongo import get_db
from db.redis_client import get_redis
from config import LOCATION_REQUEST_INTERVAL

logger = logging.getLogger(__name__)

class LocationTracker:
    """Отслеживание местоположения курьеров на смене"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.running = False
        self.task = None
    
    async def start(self):
        """Запуск отслеживания локации"""
        if self.running:
            logger.warning("Location tracker is already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._track_locations())
        logger.info(f"Location tracker started (interval: {LOCATION_REQUEST_INTERVAL}s)")
    
    async def stop(self):
        """Остановка отслеживания локации"""
        if not self.running:
            return
        
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Location tracker stopped")
    
    async def _track_locations(self):
        """Основной цикл отслеживания локации"""
        while self.running:
            try:
                await self._request_locations_from_active_couriers()
                await asyncio.sleep(LOCATION_REQUEST_INTERVAL)
            except asyncio.CancelledError:
                logger.info("Location tracker cancelled")
                break
            except Exception as e:
                logger.error(f"Error in location tracker: {e}", exc_info=True)
                await asyncio.sleep(LOCATION_REQUEST_INTERVAL)
    
    async def _request_locations_from_active_couriers(self):
        """Запрашивает локацию у всех курьеров на смене"""
        try:
            db = await get_db()
            redis = get_redis()
            
            # Получаем всех курьеров на смене
            couriers = await db.couriers.find({"is_on_shift": True}).to_list(1000)
            
            if not couriers:
                return
            
            logger.debug(f"Requesting locations from {len(couriers)} active couriers")
            
            # Создаем клавиатуру для запроса локации
            location_keyboard = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]],
                resize_keyboard=True,
                one_time_keyboard=False
            )
            
            # Запрашиваем локацию у каждого курьера
            for courier in couriers:
                try:
                    chat_id = courier.get("tg_chat_id")
                    if not chat_id:
                        continue
                    
                    # Проверяем, что курьер действительно на смене (через Redis)
                    is_on = await redis.get(f"courier:shift:{chat_id}")
                    if is_on != "on":
                        continue
                    
                    # Отправляем запрос на локацию
                    await self.bot.send_message(
                        chat_id,
                        "📍 Пожалуйста, отправьте вашу текущую локацию",
                        reply_markup=location_keyboard
                    )
                    
                    logger.debug(f"Location request sent to courier {chat_id}")
                    
                except Exception as e:
                    logger.warning(f"Failed to request location from courier {courier.get('tg_chat_id')}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error requesting locations: {e}", exc_info=True)

