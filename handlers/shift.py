from aiogram import Router, F
from aiogram.types import Message
from keyboards.main_menu import request_location_kb, main_menu
from db.mongo import get_db
from db.redis_client import get_redis
from config import SHIFT_TTL, LOC_TTL, LIVE_LOCATION_DURATION
from utils.notifications import notify_manager
from aiogram import Bot
from datetime import datetime, timezone

router = Router()

@router.message(F.text == "🟢 Начать смену")
async def start_shift(message: Message, bot: Bot):
    await message.answer("Отправь геострим на 8 часов, чтобы начать смену", reply_markup=request_location_kb())
    
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    if courier and courier.get("live_location_msg_id"):
        try:
            await bot.stop_message_live_location(message.chat.id, courier["live_location_msg_id"])
        except:
            pass

@router.message(F.location)
async def handle_location(message: Message, bot: Bot):
    import logging
    from bson import ObjectId
    logger = logging.getLogger(__name__)
    logger.info(f"User {message.from_user.id} sent location")
    
    db = await get_db()
    redis = get_redis()
    chat_id = message.chat.id
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        logger.warning(f"User {message.from_user.id} not found in database")
        await message.answer("Сначала отправь /start")
        return

    loc = message.location
    now = datetime.now(timezone.utc)
    date_key = now.strftime("%d-%m-%Y")
    shift_id = str(ObjectId())
    
    last_location = {
        "lat": loc.latitude,
        "lon": loc.longitude,
        "updated_at": now.replace(microsecond=0).isoformat()
    }

    live_msg = await bot.send_location(
        chat_id,
        latitude=loc.latitude,
        longitude=loc.longitude,
        live_period=LIVE_LOCATION_DURATION
    )

    await db.couriers.update_one(
        {"_id": courier["_id"]},
        {"$set": {
            "is_on_shift": True,
            "shift_started_at": last_location["updated_at"],
            "last_location": last_location,
            "live_location_msg_id": live_msg.message_id,
            "current_shift_id": shift_id
        }}
    )

    await redis.setex(f"courier:shift:{chat_id}", SHIFT_TTL, "on")
    await redis.setex(f"courier:loc:{chat_id}", LOC_TTL, f"{last_location['lat']},{last_location['lon']}")

    # Save initial location to locations collection
    location_doc = {
        "chat_id": chat_id,
        "shift_id": shift_id,
        "date": date_key,
        "lat": loc.latitude,
        "lon": loc.longitude,
        "timestamp": now.isoformat(),
        "timestamp_ns": int(now.timestamp() * 1_000_000_000)
    }
    await db.locations.insert_one(location_doc)

    from db.models import Action
    await Action.log(db, message.from_user.id, "shift_start", details={"location": last_location, "shift_id": shift_id})
    logger.info(f"User {message.from_user.id} started shift {shift_id} at {last_location['lat']},{last_location['lon']}")

    await message.answer("✅ Смена начата\nГеопозиция сохранена. Пришли новые заказы — я уведомлю!")
    await message.answer("Главное меню:", reply_markup=main_menu())
    
    # Notify manager
    if courier.get("manager_chat_id"):
        notification_text = f"🟢 Курьер {courier['name']} вышел на линию\nID: {chat_id}"
        try:
            await bot.send_message(courier["manager_chat_id"], notification_text)
            logger.info(f"Notified manager {courier['manager_chat_id']} about shift start")
        except Exception as e:
            logger.warning(f"Failed to notify manager {courier['manager_chat_id']}: {e}")

@router.message(F.text == "🔴 Закончить смену")
async def end_shift(message: Message, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"User {message.from_user.id} ending shift")
    
    db = await get_db()
    redis = get_redis()
    chat_id = message.chat.id
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        logger.warning(f"User {message.from_user.id} not found in database")
        await message.answer("Сначала отправь /start")
        return

    if courier.get("live_location_msg_id"):
        try:
            await bot.stop_message_live_location(chat_id, courier["live_location_msg_id"])
        except:
            pass

    await db.couriers.update_one({"_id": courier["_id"]}, {"$set": {"is_on_shift": False}, "$unset": {"live_location_msg_id": "", "current_shift_id": ""}})
    await redis.delete(f"courier:shift:{chat_id}")
    await redis.delete(f"courier:loc:{chat_id}")

    from db.models import Action
    await Action.log(db, message.from_user.id, "shift_end")
    logger.info(f"User {message.from_user.id} ended shift")

    await message.answer("💤 Смена завершена\nХорошей передышки!")
    await message.answer("Главное меню:", reply_markup=main_menu())

    # notify manager group
    courier = await db.couriers.find_one({"_id": courier["_id"]})
    await notify_manager(bot, courier, f"⚠ Курьер {courier['name']} завершил смену.")
