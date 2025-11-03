from aiogram import Router, F
from aiogram.types import Message
from keyboards.main_menu import request_location_kb, main_menu
from db.mongo import get_db
from db.redis_client import get_redis
from config import SHIFT_TTL, LOC_TTL
from utils.notifications import notify_manager
from aiogram import Bot
from datetime import datetime, timezone

router = Router()

@router.message(F.text == "🟢 Начать смену")
async def start_shift(message: Message):
    await message.answer("Отправь геопозицию, чтобы начать смену", reply_markup=request_location_kb())

@router.message(F.location)
async def handle_location(message: Message, bot: Bot):
    db = await get_db()
    redis = get_redis()
    chat_id = message.chat.id
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        await message.answer("Сначала отправь /start")
        return

    loc = message.location
    last_location = {
        "lat": loc.latitude,
        "lon": loc.longitude,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    }

    await db.couriers.update_one(
        {"_id": courier["_id"]},
        {"$set": {"is_on_shift": True, "shift_started_at": last_location["updated_at"], "last_location": last_location}}
    )

    await redis.setex(f"courier:shift:{chat_id}", SHIFT_TTL, "on")
    await redis.setex(f"courier:loc:{chat_id}", LOC_TTL, f"{last_location['lat']},{last_location['lon']}")

    await message.answer("✅ Смена начата
Геопозиция сохранена. Пришли новые заказы — я уведомлю!", reply_markup=main_menu())

@router.message(F.text == "🔴 Закончить смену")
async def end_shift(message: Message, bot: Bot):
    db = await get_db()
    redis = get_redis()
    chat_id = message.chat.id
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        await message.answer("Сначала отправь /start")
        return

    await db.couriers.update_one({"_id": courier["_id"]}, {"$set": {"is_on_shift": False}})
    await redis.delete(f"courier:shift:{chat_id}")
    await redis.delete(f"courier:loc:{chat_id}")

    await message.answer("💤 Смена завершена
Хорошей передышки!")

    # notify manager group
    courier = await db.couriers.find_one({"_id": courier["_id"]})
    await notify_manager(bot, courier, f"⚠ Курьер {courier['name']} завершил смену.")
