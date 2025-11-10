from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from keyboards.main_menu import main_menu, remove_keyboard
from db.mongo import get_db
from db.redis_client import get_redis
from config import SHIFT_TTL, LOC_TTL, MANAGER_CHAT_ID
from bson import ObjectId
from datetime import datetime, timezone
from typing import Tuple, Optional
import logging

router = Router()
logger = logging.getLogger(__name__)

def get_shift_start_instruction() -> str:
    """Возвращает инструкцию для начала смены"""
    return (
        "📍 Для начала смены отправь свою геолокацию:\n\n"
        "1️⃣ Нажми на скрепку (📎)\n"
        "2️⃣ Выбери 'Геопозиция'\n"
        "3️⃣ Нажми 'Транслировать геопозицию'\n"
        "4️⃣ Установи время минимум 8 часов\n"
        "5️⃣ Нажми 'Отправить'"
    )

def format_shift_start_time(shift_started_at: str) -> str:
    """Форматирует дату и время начала смены для отображения"""
    try:
        # Парсим ISO формат даты
        dt = datetime.fromisoformat(shift_started_at.replace('Z', '+00:00'))
        # Форматируем в читаемый формат: ДД.ММ.ГГГГ ЧЧ:ММ
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception as e:
        logger.warning(f"[SHIFT] ⚠️ Ошибка форматирования даты {shift_started_at}: {e}")
        return shift_started_at

async def check_shift_status(chat_id: int) -> Tuple[bool, Optional[str]]:
    """
    Проверяет статус смены курьера
    
    Returns:
        Tuple[bool, Optional[str]]: (is_on_shift, shift_started_at)
    """
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        return False, None
    
    is_on_shift = courier.get("is_on_shift", False)
    shift_started_at = courier.get("shift_started_at")
    
    return is_on_shift, shift_started_at

@router.message(F.text == "/online")
@router.message(F.text == "online")
async def cmd_online(message: Message):
    """Команда для начала смены"""
    logger.info(f"[SHIFT] 📍 Пользователь {message.from_user.id} использует команду /online")
    
    is_on_shift, shift_started_at = await check_shift_status(message.chat.id)
    
    if is_on_shift and shift_started_at:
        formatted_time = format_shift_start_time(shift_started_at)
        await message.answer(
            f"✅ Вы уже на смене\n\n"
            f"🕐 Начало смены: {formatted_time}"
        )
    else:
        await message.answer(get_shift_start_instruction())

@router.callback_query(F.data == "shift:start")
async def cb_start_shift(call: CallbackQuery):
    is_on_shift, shift_started_at = await check_shift_status(call.message.chat.id)
    
    if is_on_shift and shift_started_at:
        formatted_time = format_shift_start_time(shift_started_at)
        await call.message.edit_text(
            f"✅ Вы уже на смене\n\n"
            f"🕐 Начало смены: {formatted_time}"
        )
    else:
        await call.message.edit_text(get_shift_start_instruction())
    await call.answer()

@router.message(F.location)
async def handle_location(message: Message, bot: Bot):
    from bson import ObjectId
    
    logger.info(f"[SHIFT] 📍 Пользователь {message.from_user.id} отправил локацию, live_period={message.location.live_period}")
    logger.debug(f"[SHIFT] 📊 Координаты: lat={message.location.latitude}, lon={message.location.longitude}")
    
    db = await get_db()
    redis = get_redis()
    chat_id = message.chat.id
    logger.debug(f"[SHIFT] 🔍 Поиск курьера по chat_id: {chat_id}")
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        logger.warning(f"[SHIFT] ⚠️ Пользователь {message.from_user.id} не найден в базе данных")
        return

    logger.info(f"[SHIFT] ✅ Курьер найден: {courier['name']}, is_on_shift={courier.get('is_on_shift')}")
    
    if courier.get("is_on_shift"):
        logger.info(f"[SHIFT] ⏸️ Пользователь {message.from_user.id} уже на смене, игнорируем")
        return
    
    if not message.location.live_period:
        logger.info(f"[SHIFT] ⏸️ Пользователь {message.from_user.id} отправил статичную локацию, игнорируем")
        return
    
    logger.info(f"[SHIFT] 🚚 Начало смены для пользователя {message.from_user.id}")

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
        logger.debug(f"[SHIFT] 💾 Обновление курьера в БД: shift_id={shift_id}")

        await db.couriers.update_one(
            {"_id": courier["_id"]},
            {"$set": {
                "is_on_shift": True,
                "shift_started_at": last_location["updated_at"],
                "last_location": last_location,
                "current_shift_id": shift_id
            }}
        )
        logger.info(f"[SHIFT] ✅ Курьер обновлен в БД: is_on_shift=True, shift_id={shift_id}")

        logger.debug(f"[SHIFT] 💾 Обновление Redis: shift и location для chat_id={chat_id}")
        await redis.setex(f"courier:shift:{chat_id}", SHIFT_TTL, "on")
        await redis.setex(f"courier:loc:{chat_id}", LOC_TTL, f"{last_location['lat']},{last_location['lon']}")
        logger.debug(f"[SHIFT] ✅ Redis обновлен")

        location_doc = {
            "chat_id": chat_id,
            "shift_id": shift_id,
            "date": date_key,
            "lat": loc.latitude,
            "lon": loc.longitude,
            "timestamp": now.isoformat(),
            "timestamp_ns": int(now.timestamp() * 1_000_000_000)
        }
        logger.debug(f"[SHIFT] 💾 Сохранение локации в БД: lat={loc.latitude}, lon={loc.longitude}")
        await db.locations.insert_one(location_doc)
        logger.info(f"[SHIFT] ✅ Локация сохранена в БД")

        from db.models import Action
        await Action.log(db, message.from_user.id, "shift_start", details={"location": last_location, "shift_id": shift_id})
        logger.debug(f"[SHIFT] 📝 Действие 'shift_start' залогировано, shift_id={shift_id}")

        # Обновляем данные курьера после всех изменений
        courier = await db.couriers.find_one({"_id": courier["_id"]})
        
        # Обновление статуса в Odoo
        try:
            from utils.odoo import update_courier_status
            # courier_tg_chat_id используется как основной идентификатор
            logger.debug(f"[SHIFT] 🔌 Обновление статуса курьера {chat_id} в Odoo: is_online=True")
            success = await update_courier_status(str(chat_id), is_online=True)
            if success:
                logger.info(f"[SHIFT] ✅ Статус курьера {chat_id} обновлен в Odoo: online")
            else:
                logger.warning(f"[SHIFT] ⚠️ Не удалось обновить статус курьера {chat_id} в Odoo")
        except Exception as e:
            logger.error(f"[SHIFT] ❌ Ошибка обновления статуса курьера в Odoo: {e}", exc_info=True)
        
        # Отправка webhook
        from utils.webhooks import send_webhook, prepare_courier_data
        from db.models import utcnow_iso
        courier_data = await prepare_courier_data(db, courier)
        webhook_data = {
            **courier_data,
            "location": last_location,
            "shift_id": shift_id,
            "timestamp": utcnow_iso()
        }
        await send_webhook("shift_start", webhook_data)

        logger.debug(f"[SHIFT] 📤 Отправка сообщения курьеру {courier['name']}")
        await message.answer(
            f"✅ Курьер {courier['name']} на смене\n\n"
            "Геопозиция сохранена. При появлении новых заказов — я уведомлю!",
            reply_markup=main_menu(is_on_shift=True)
        )
        logger.info(f"[SHIFT] ✅ Сообщение отправлено курьеру {courier['name']}")
        
        logger.debug(f"[SHIFT] 📊 MANAGER_CHAT_ID: {MANAGER_CHAT_ID}")
        if MANAGER_CHAT_ID:
            notification_text = f"🟢 Курьер {courier['name']} вышел на смену\nID: {chat_id}"
            logger.info(f"[SHIFT] 📤 Отправка уведомления менеджеру {MANAGER_CHAT_ID}")
            try:
                await bot.send_message(MANAGER_CHAT_ID, notification_text)
                logger.info(f"[SHIFT] ✅ Менеджер {MANAGER_CHAT_ID} уведомлен")
            except Exception as e:
                logger.error(f"[SHIFT] ❌ Ошибка уведомления менеджера {MANAGER_CHAT_ID}: {e}", exc_info=True)
        else:
            logger.warning(f"[SHIFT] ⚠️ MANAGER_CHAT_ID не установлен, уведомление пропущено")
    except Exception as e:
        logger.error(f"[SHIFT] ❌ Ошибка в handle_location: {e}", exc_info=True)

async def end_shift_logic(chat_id: int, user_id: int, bot: Bot, message_or_call=None):
    """
    Общая логика завершения смены
    Может быть вызвана как из callback, так и из message handler
    
    Args:
        chat_id: ID чата курьера
        user_id: ID пользователя
        bot: Bot instance
        message_or_call: Message или CallbackQuery объект (для отправки ответа)
    """
    db = await get_db()
    redis = get_redis()
    
    logger.debug(f"[SHIFT] 🔍 Поиск курьера по chat_id: {chat_id}")
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        logger.warning(f"[SHIFT] ⚠️ Курьер не найден: chat_id={chat_id}")
        if message_or_call:
            if hasattr(message_or_call, 'answer'):  # CallbackQuery
                await message_or_call.answer("Пользователь не найден", show_alert=True)
            else:  # Message
                await message_or_call.answer("❌ Пользователь не найден")
        return False
    
    # Сохраняем время начала смены для подсчета заказов
    shift_started_at = courier.get("shift_started_at")
    
    # Check for unfinished orders
    logger.debug(f"[SHIFT] 🔍 Проверка незавершенных заказов для chat_id: {chat_id}")
    unfinished = await db.couriers_deliveries.count_documents({
        "courier_tg_chat_id": chat_id,
        "status": {"$in": ["waiting", "in_transit"]}
    })
    if unfinished > 0:
        logger.warning(f"[SHIFT] ⚠️ Попытка завершить смену с {unfinished} незавершенными заказами")
        if message_or_call:
            if hasattr(message_or_call, 'answer'):  # CallbackQuery
                await message_or_call.answer(f"Нельзя завершить смену! У вас {unfinished} незавершенных заказов", show_alert=True)
            else:  # Message
                await message_or_call.answer(f"❌ Нельзя завершить смену! У вас {unfinished} незавершенных заказов")
        return False

    # Подсчет заказов за смену
    orders_count = 0
    if shift_started_at:
        try:
            logger.debug(f"[SHIFT] 📊 Подсчет заказов за смену с {shift_started_at}")
            orders_count = await db.couriers_deliveries.count_documents({
                "courier_tg_chat_id": chat_id,
                "created_at": {"$gte": shift_started_at}
            })
            logger.info(f"[SHIFT] 📊 Заказов за смену: {orders_count}")
        except Exception as e:
            logger.warning(f"[SHIFT] ⚠️ Ошибка подсчета заказов за смену: {e}", exc_info=True)

    logger.debug(f"[SHIFT] 💾 Обновление статуса курьера: is_on_shift=False")
    await db.couriers.update_one({"_id": courier["_id"]}, {"$set": {"is_on_shift": False}, "$unset": {"current_shift_id": ""}})
    logger.debug(f"[SHIFT] 🗑️ Удаление данных из Redis: shift и location")
    await redis.delete(f"courier:shift:{chat_id}")
    await redis.delete(f"courier:loc:{chat_id}")

    from db.models import Action
    await Action.log(db, user_id, "shift_end")
    logger.info(f"[SHIFT] ✅ Пользователь {user_id} завершил смену")

    # Обновляем данные курьера после всех изменений
    courier = await db.couriers.find_one({"_id": courier["_id"]})
    
    # Обновление статуса в Odoo
    try:
        from utils.odoo import update_courier_status
        logger.debug(f"[SHIFT] 🔌 Обновление статуса курьера {chat_id} в Odoo: is_online=False")
        success = await update_courier_status(str(chat_id), is_online=False)
        if success:
            logger.info(f"[SHIFT] ✅ Статус курьера {chat_id} обновлен в Odoo: offline")
        else:
            logger.warning(f"[SHIFT] ⚠️ Не удалось обновить статус курьера {chat_id} в Odoo")
    except Exception as e:
        logger.error(f"[SHIFT] ❌ Ошибка обновления статуса курьера в Odoo: {e}", exc_info=True)
    
    # Отправка webhook
    from utils.webhooks import send_webhook, prepare_courier_data
    from db.models import utcnow_iso
    logger.debug(f"[SHIFT] 🔗 Отправка webhook 'shift_end'")
    courier_data = await prepare_courier_data(db, courier)
    webhook_data = {
        **courier_data,
        "timestamp": utcnow_iso()
    }
    await send_webhook("shift_end", webhook_data)
    logger.debug(f"[SHIFT] ✅ Webhook 'shift_end' отправлен")

    # Формируем сообщение о завершении смены
    shift_message = (
        f"💤 Смена завершена\n\n"
        f"📦 Заказов за смену: {orders_count}\n\n"
        f"Хорошей передышки!"
    )
    
    # Отправка сообщения курьеру
    if message_or_call:
        # Проверяем, является ли это CallbackQuery (имеет атрибут message)
        if hasattr(message_or_call, 'message') and hasattr(message_or_call, 'answer'):  # CallbackQuery
            # Убираем кнопки, чтобы сообщение не удалялось при клике на другие кнопки
            await message_or_call.message.edit_text(
                shift_message,
                reply_markup=None
            )
            await message_or_call.answer()
        else:  # Message
            await message_or_call.answer(
                shift_message,
                reply_markup=main_menu(is_on_shift=False)
            )
    
    if MANAGER_CHAT_ID:
        notification_text = f"🔴 Курьер {courier['name']} завершил смену\nID: {chat_id}"
        logger.info(f"[SHIFT] 📤 Отправка уведомления менеджеру {MANAGER_CHAT_ID} о завершении смены")
        try:
            await bot.send_message(MANAGER_CHAT_ID, notification_text)
            logger.info(f"[SHIFT] ✅ Менеджер {MANAGER_CHAT_ID} уведомлен о завершении смены")
        except Exception as e:
            logger.warning(f"[SHIFT] ⚠️ Ошибка уведомления менеджера: {e}", exc_info=True)
    
    return True

@router.message(F.text == "/offline")
@router.message(F.text == "offline")
async def cmd_offline(message: Message, bot: Bot):
    """Команда для завершения смены"""
    logger.info(f"[SHIFT] 🛑 Пользователь {message.from_user.id} использует команду /offline")
    await end_shift_logic(message.chat.id, message.from_user.id, bot, message)

@router.callback_query(F.data == "shift:end")
async def cb_end_shift(call: CallbackQuery, bot: Bot):
    logger.info(f"[SHIFT] 🛑 Пользователь {call.from_user.id} завершает смену")
    await end_shift_logic(call.message.chat.id, call.from_user.id, bot, call)
