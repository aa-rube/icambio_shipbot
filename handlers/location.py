from aiogram import Router, F
from aiogram.types import Message
from db.mongo import get_db
from datetime import datetime, timezone
from bson import ObjectId
import logging

router = Router()

@router.message(F.location)
async def handle_location_update(message: Message):
    logger = logging.getLogger(__name__)
    
    if not message.location.live_period:
        return
    
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    
    if not courier or not courier.get("is_on_shift"):
        return
    
    shift_id = courier.get("current_shift_id")
    if not shift_id:
        logger.warning(f"No shift_id for courier {message.chat.id}")
        return
    
    now = datetime.now(timezone.utc)
    date_key = now.strftime("%d-%m-%Y")
    
    location_doc = {
        "chat_id": message.chat.id,
        "shift_id": shift_id,
        "date": date_key,
        "lat": message.location.latitude,
        "lon": message.location.longitude,
        "timestamp": now.isoformat(),
        "timestamp_ns": now.timestamp() * 1_000_000_000
    }
    
    await db.locations.insert_one(location_doc)
    logger.info(f"Location saved for courier {message.chat.id}, shift {shift_id}")
