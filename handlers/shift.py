from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from keyboards.main_menu import main_menu, remove_keyboard
from db.mongo import get_db
from db.redis_client import get_redis
from config import SHIFT_TTL, LOC_TTL, MANAGER_CHAT_ID
from bson import ObjectId
from datetime import datetime, timezone
import logging

router = Router()
logger = logging.getLogger(__name__)

@router.callback_query(F.data == "shift:start")
async def cb_start_shift(call: CallbackQuery):
    await call.message.edit_text(
        "📍 Для начала смены отправь свою геолокацию:\n\n"
        "1️⃣ Нажми на скрепку (📎)\n"
        "2️⃣ Выбери 'Геопозиция'\n"
        "3️⃣ Нажми 'Поделиться текущим местоположением'\n"
        "4️⃣ Установи время минимум 8 часов"
    )
    await call.answer()

@router.message(F.location)
async def handle_location(message: Message, bot: Bot):
    from bson import ObjectId
    
    logger.info(f"User {message.from_user.id} sent location, live_period={message.location.live_period}")
    
    db = await get_db()
    redis = get_redis()
    chat_id = message.chat.id
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        logger.warning(f"User {message.from_user.id} not found in database")
        return

    logger.info(f"Courier found: {courier['name']}, is_on_shift={courier.get('is_on_shift')}")
    
    if courier.get("is_on_shift"):
        logger.info(f"User {message.from_user.id} already on shift, ignoring")
        return
    
    if not message.location.live_period:
        logger.info(f"User {message.from_user.id} sent static location, ignoring")
        return
    
    logger.info(f"Starting shift for user {message.from_user.id}")

    try:
        loc = message.location
        now = datetime.now(timezone.utc)
        date_key = now.strftime("%d-%m-%Y")
        shift_id = str(ObjectId())
        
        last_location = {
            "lat": loc.latitude,
            "lon": loc.longitude,
            "updated_at": now.replace(microsecond=0).isoformat()
        }
        logger.info(f"Updating courier in DB")

        await db.couriers.update_one(
            {"_id": courier["_id"]},
            {"$set": {
                "is_on_shift": True,
                "shift_started_at": last_location["updated_at"],
                "last_location": last_location,
                "current_shift_id": shift_id
            }}
        )
        logger.info(f"Courier updated in DB")

        await redis.setex(f"courier:shift:{chat_id}", SHIFT_TTL, "on")
        await redis.setex(f"courier:loc:{chat_id}", LOC_TTL, f"{last_location['lat']},{last_location['lon']}")
        logger.info(f"Redis updated")

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
        logger.info(f"Location saved to DB")

        from db.models import Action
        await Action.log(db, message.from_user.id, "shift_start", details={"location": last_location, "shift_id": shift_id})
        logger.info(f"Action logged, shift_id={shift_id}")

        await message.answer(
            f"✅ Курьер {courier['name']} на смене\n\n"
            "Геопозиция сохранена. При появлении новых заказов — я уведомлю!",
            reply_markup=main_menu(is_on_shift=True)
        )
        logger.info(f"Message sent to courier")
        
        logger.info(f"MANAGER_CHAT_ID value: {MANAGER_CHAT_ID}")
        if MANAGER_CHAT_ID:
            notification_text = f"🟢 Курьер {courier['name']} вышел на смену\nID: {chat_id}"
            logger.info(f"Sending notification to manager {MANAGER_CHAT_ID}")
            try:
                await bot.send_message(MANAGER_CHAT_ID, notification_text)
                logger.info(f"Successfully notified manager {MANAGER_CHAT_ID}")
            except Exception as e:
                logger.error(f"Failed to notify manager {MANAGER_CHAT_ID}: {e}")
        else:
            logger.warning("MANAGER_CHAT_ID is not set, skipping notification")
    except Exception as e:
        logger.error(f"Error in handle_location: {e}", exc_info=True)

@router.callback_query(F.data == "shift:end")
async def cb_end_shift(call: CallbackQuery, bot: Bot):
    logger.info(f"User {call.from_user.id} ending shift")
    
    db = await get_db()
    redis = get_redis()
    chat_id = call.message.chat.id
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        await call.answer("Пользователь не найден", show_alert=True)
        return

    await db.couriers.update_one({"_id": courier["_id"]}, {"$set": {"is_on_shift": False}, "$unset": {"current_shift_id": ""}})
    await redis.delete(f"courier:shift:{chat_id}")
    await redis.delete(f"courier:loc:{chat_id}")

    from db.models import Action
    await Action.log(db, call.from_user.id, "shift_end")
    logger.info(f"User {call.from_user.id} ended shift")

    await call.message.edit_text(
        "💤 Смена завершена\nХорошей передышки!",
        reply_markup=main_menu(is_on_shift=False)
    )
    
    if MANAGER_CHAT_ID:
        notification_text = f"🔴 Курьер {courier['name']} завершил смену\nID: {chat_id}"
        try:
            await bot.send_message(MANAGER_CHAT_ID, notification_text)
            logger.info(f"Notified manager {MANAGER_CHAT_ID} about shift end")
        except Exception as e:
            logger.warning(f"Failed to notify manager: {e}")
    
    await call.answer()
