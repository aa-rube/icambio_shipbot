from aiogram import Router, F
from aiogram.types import Message
from db.mongo import get_db
from db.redis_client import get_redis
from config import TIMEZONE
from datetime import datetime
from bson import ObjectId
import logging

router = Router()
logger = logging.getLogger(__name__)

@router.edited_message(F.location)
async def handle_edited_location(edited_message: Message):
    """
    Обрабатывает edited_message с location для лайв-локации.
    Telegram переотправляет то же сообщение с новой координатой как edited_message.
    """
    db = await get_db()
    redis = get_redis()
    chat_id = edited_message.chat.id
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    
    if not courier:
        return
    
    # Проверяем, что курьер на смене
    is_on = await redis.get(f"courier:shift:{chat_id}")
    if is_on != "on":
        return
    
    # Проверяем, что это live location (edited_message приходит только для live location)
    if not edited_message.location or not edited_message.location.live_period:
        return
    
    shift_id = courier.get("current_shift_id")
    if not shift_id:
        logger.warning(f"No shift_id for courier {chat_id}")
        return
    
    now = datetime.now(TIMEZONE)
    date_key = now.strftime("%d-%m-%Y")
    
    location_doc = {
        "chat_id": chat_id,
        "shift_id": shift_id,
        "date": date_key,
        "lat": edited_message.location.latitude,
        "lon": edited_message.location.longitude,
        "timestamp": now.isoformat(),
        "timestamp_ns": int(now.timestamp() * 1_000_000_000)
    }
    
    await db.locations.insert_one(location_doc)
    
    # Обновляем last_location в профиле курьера
    last_location = {
        "lat": edited_message.location.latitude,
        "lon": edited_message.location.longitude,
        "updated_at": now.replace(microsecond=0).isoformat()
    }
    
    await db.couriers.update_one(
        {"_id": courier["_id"]},
        {"$set": {"last_location": last_location}}
    )
    
    # Обновляем Redis
    await redis.setex(
        f"courier:loc:{chat_id}",
        12 * 60 * 60,  # LOC_TTL
        f"{last_location['lat']},{last_location['lon']}"
    )

@router.message(F.location)
async def handle_location_update(message: Message):
    """Обрабатывает обновления локации от курьеров (live location и запрошенные локации)"""
    
    db = await get_db()
    redis = get_redis()
    chat_id = message.chat.id
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    
    if not courier:
        return
    
    # Проверяем, что курьер на смене
    is_on = await redis.get(f"courier:shift:{chat_id}")
    if is_on != "on":
        # Если курьер не на смене, игнорируем локацию (кроме начала смены)
        return
    
    # Если это live location, обрабатываем как обычно
    if message.location.live_period:
        shift_id = courier.get("current_shift_id")
        if not shift_id:
            logger.warning(f"No shift_id for courier {chat_id}")
            return
        
        now = datetime.now(TIMEZONE)
        date_key = now.strftime("%d-%m-%Y")
        
        location_doc = {
            "chat_id": chat_id,
            "shift_id": shift_id,
            "date": date_key,
            "lat": message.location.latitude,
            "lon": message.location.longitude,
            "timestamp": now.isoformat(),
            "timestamp_ns": int(now.timestamp() * 1_000_000_000)
        }
        
        await db.locations.insert_one(location_doc)
        
        # Обновляем last_location в профиле курьера
        last_location = {
            "lat": message.location.latitude,
            "lon": message.location.longitude,
            "updated_at": now.replace(microsecond=0).isoformat()
        }
        
        await db.couriers.update_one(
            {"_id": courier["_id"]},
            {"$set": {"last_location": last_location}}
        )
        
        # Обновляем Redis
        await redis.setex(
            f"courier:loc:{chat_id}",
            12 * 60 * 60,  # LOC_TTL
            f"{last_location['lat']},{last_location['lon']}"
        )
        
        logger.debug(f"Live location saved for courier {chat_id}, shift {shift_id}")
    
    else:
        # Это запрошенная локация (не live location)
        shift_id = courier.get("current_shift_id")
        if not shift_id:
            logger.warning(f"No shift_id for courier {chat_id}")
            return
        
        now = datetime.now(TIMEZONE)
        date_key = now.strftime("%d-%m-%Y")
        
        location_doc = {
            "chat_id": chat_id,
            "shift_id": shift_id,
            "date": date_key,
            "lat": message.location.latitude,
            "lon": message.location.longitude,
            "timestamp": now.isoformat(),
            "timestamp_ns": int(now.timestamp() * 1_000_000_000),
            "requested": True  # Помечаем как запрошенную локацию
        }
        
        await db.locations.insert_one(location_doc)
        
        # Обновляем last_location в профиле курьера
        last_location = {
            "lat": message.location.latitude,
            "lon": message.location.longitude,
            "updated_at": now.replace(microsecond=0).isoformat()
        }
        
        await db.couriers.update_one(
            {"_id": courier["_id"]},
            {"$set": {"last_location": last_location}}
        )
        
        # Обновляем Redis
        await redis.setex(
            f"courier:loc:{chat_id}",
            12 * 60 * 60,  # LOC_TTL
            f"{last_location['lat']},{last_location['lon']}"
        )
        
        logger.info(f"Requested location saved for courier {chat_id}, shift {shift_id}")
        
        # Убираем клавиатуру после получения локации
        from aiogram.types import ReplyKeyboardRemove
        await message.answer("✅ Локация получена", reply_markup=ReplyKeyboardRemove())
