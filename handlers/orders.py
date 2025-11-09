from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from db.mongo import get_db
from db.redis_client import get_redis
from keyboards.orders_kb import new_order_kb, in_transit_kb
from keyboards.main_menu import main_menu
from utils.notifications import notify_manager
from config import ORDER_LOCK_TTL, PHOTO_WAIT_TTL
from db.models import utcnow_iso
from datetime import datetime, timezone
import re

router = Router()

def clean_html_notes(notes: str) -> str:
    """
    Очищает HTML-теги из notes, оставляя только поддерживаемые Telegram теги.
    Telegram поддерживает: <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <tg-spoiler>
    Удаляет все остальные теги, включая <p>, <div>, <span> и т.д.
    """
    if not notes:
        return ""
    
    # Удаляем неподдерживаемые HTML-теги, но сохраняем их содержимое
    # Сначала заменяем <p> и </p> на переносы строк
    notes = re.sub(r'<p[^>]*>', '\n', notes, flags=re.IGNORECASE)
    notes = re.sub(r'</p>', '\n', notes, flags=re.IGNORECASE)
    
    # Удаляем другие неподдерживаемые теги, но сохраняем содержимое
    # Разрешаем только поддерживаемые Telegram теги
    allowed_tags = ['b', 'i', 'u', 's', 'code', 'pre', 'a', 'tg-spoiler']
    
    # Удаляем все теги, кроме разрешенных
    pattern = r'<(?!\/?(?:' + '|'.join(allowed_tags) + r')\b)[^>]+>'
    notes = re.sub(pattern, '', notes, flags=re.IGNORECASE)
    
    # Очищаем множественные переносы строк
    notes = re.sub(r'\n{3,}', '\n\n', notes)
    
    # Убираем пробелы в начале и конце
    notes = notes.strip()
    
    return notes

def format_order_text(order: dict) -> str:
    """Unified order formatting for all messages"""
    status_emoji = {"waiting": "⏳", "in_transit": "🚗", "done": "✅", "cancelled": "❌"}
    status_text = {"waiting": "Ожидает", "in_transit": "В пути", "done": "Выполнен", "cancelled": "Отменен"}
    priority_emoji = "🔴" if order.get("priority", 0) >= 5 else "🟡" if order.get("priority", 0) >= 3 else "⚪"
    
    text = f"{status_emoji.get(order['status'], '⏳')} Статус: {status_text.get(order['status'], 'Ожидает')}\n\n"
    text += f"<code>{order.get('address', '—')}</code>\n\n"
    
    if order.get("map_url"):
        text += f"🗺 <a href='{order['map_url']}'>Карта</a>\n\n"
    
    text += f"💳 {order.get('payment_status', 'NOT_PAID')} | {priority_emoji} Приоритет: {order.get('priority', 0)}\n"
    
    if order.get("delivery_time"):
        text += f"⏰ {order['delivery_time']}\n"
    
    client = order.get('client', {})
    text += f"👤 {client.get('name', '—')} | 📞 {client.get('phone', '—')}\n"
    
    if client.get('tg'):
        text += f"@{client['tg'].lstrip('@')}\n"
    
    if order.get("notes"):
        cleaned_notes = clean_html_notes(order['notes'])
        if cleaned_notes:
            text += f"\n📝 {cleaned_notes}\n"
    
    if order.get("brand") or order.get("source"):
        text += "\n"
        if order.get("brand"):
            text += f"🏷 {order['brand']}"
        if order.get("source"):
            text += f" | 📊 {order['source']}"
    
    return text

@router.message(F.text == "/orders")
async def cmd_orders(message: Message):
    import logging
    logger = logging.getLogger(__name__)
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    logger.info(f"[ORDERS] User {user_id} (chat_id: {chat_id}) executed /orders command")
    
    try:
        await show_active_orders(chat_id, message)
    except Exception as e:
        logger.error(f"[ORDERS] Error in cmd_orders for user {user_id} (chat_id: {chat_id}): {e}", exc_info=True)
        await message.answer("Произошла ошибка при загрузке заказов")

@router.callback_query(F.data == "orders:list")
async def cb_my_orders(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    logger.info(f"[ORDERS] User {user_id} (chat_id: {chat_id}) clicked 'Мои заказы' button")
    
    try:
        await show_active_orders(chat_id, call.message)
        await call.answer()
    except Exception as e:
        logger.error(f"[ORDERS] Error in cb_my_orders for user {user_id} (chat_id: {chat_id}): {e}", exc_info=True)
        await call.answer("Произошла ошибка при загрузке заказов", show_alert=True)

async def show_waiting_orders(chat_id: int, message: Message):
    """Показывает только заказы со статусом waiting для курьера"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[ORDERS] show_waiting_orders called for chat_id: {chat_id}")
    
    db = await get_db()
    
    # Проверяем заказы с разными типами данных
    orders_as_int = await db.couriers_deliveries.count_documents({"courier_tg_chat_id": int(chat_id), "status": "waiting"})
    
    # Определяем правильный тип для запроса
    search_chat_id = int(chat_id) if orders_as_int > 0 else chat_id
    
    # Логируем запрос к БД
    query = {
        "courier_tg_chat_id": search_chat_id,
        "status": "waiting"
    }
    logger.debug(f"[ORDERS] MongoDB query for waiting orders: {query}")
    
    cursor = db.couriers_deliveries.find(query).sort("priority", -1).sort("created_at", 1)
    
    found = False
    order_count = 0
    async for order in cursor:
        found = True
        order_count += 1
        logger.info(f"[ORDERS] Found waiting order #{order_count}: external_id={order.get('external_id')}, priority={order.get('priority')}")
        
        text = format_order_text(order)
        await message.answer(text, parse_mode="HTML", reply_markup=new_order_kb(order["external_id"]))
        logger.debug(f"[ORDERS] Sent waiting order {order.get('external_id')} to chat_id {chat_id}")
    
    if not found:
        logger.info(f"[ORDERS] No waiting orders found for chat_id {chat_id}")
        await message.answer("Нет активных заказов.")
    else:
        logger.info(f"[ORDERS] Successfully sent {order_count} waiting order(s) to chat_id {chat_id}")

async def show_active_orders(chat_id: int, message: Message):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[ORDERS] show_active_orders called for chat_id: {chat_id} (type: {type(chat_id).__name__})")
    
    db = await get_db()
    
    # Проверяем, есть ли заказы с таким courier_tg_chat_id (без фильтра по статусу)
    all_orders_count = await db.couriers_deliveries.count_documents({"courier_tg_chat_id": chat_id})
    logger.info(f"[ORDERS] Total orders for chat_id {chat_id}: {all_orders_count}")
    
    # Проверяем заказы с разными типами данных
    # Пробуем найти заказы как с числом, так и со строкой
    orders_as_int = await db.couriers_deliveries.count_documents({"courier_tg_chat_id": int(chat_id)})
    logger.info(f"[ORDERS] Orders with courier_tg_chat_id as int({chat_id}): {orders_as_int}")
    
    # Определяем правильный тип для запроса
    # Если заказы найдены с int, используем int, иначе используем исходный тип
    search_chat_id = int(chat_id) if orders_as_int > 0 else chat_id
    
    # Получаем пример заказа для отладки
    sample_order = await db.couriers_deliveries.find_one({"courier_tg_chat_id": search_chat_id})
    if sample_order:
        logger.debug(f"[ORDERS] Sample order found: courier_tg_chat_id={sample_order.get('courier_tg_chat_id')} (type: {type(sample_order.get('courier_tg_chat_id')).__name__}), status={sample_order.get('status')}, external_id={sample_order.get('external_id')}")
    else:
        logger.warning(f"[ORDERS] No orders found for chat_id {chat_id} (tried as {type(search_chat_id).__name__})")
    
    # Логируем запрос к БД
    query = {
        "courier_tg_chat_id": search_chat_id,
        "status": {"$in": ["waiting", "in_transit"]}
    }
    logger.debug(f"[ORDERS] MongoDB query: {query}")
    
    cursor = db.couriers_deliveries.find(query).sort("priority", -1).sort("created_at", 1)
    
    found = False
    order_count = 0
    async for order in cursor:
        found = True
        order_count += 1
        logger.info(f"[ORDERS] Found order #{order_count}: external_id={order.get('external_id')}, status={order.get('status')}, priority={order.get('priority')}")
        
        text = format_order_text(order)
        if order["status"] == "waiting":
            await message.answer(text, parse_mode="HTML", reply_markup=new_order_kb(order["external_id"]))
            logger.debug(f"[ORDERS] Sent waiting order {order.get('external_id')} to chat_id {chat_id}")
        elif order["status"] == "in_transit":
            await message.answer(text, parse_mode="HTML", reply_markup=in_transit_kb(order["external_id"], order))
            logger.debug(f"[ORDERS] Sent in_transit order {order.get('external_id')} to chat_id {chat_id}")
    
    if not found:
        logger.warning(f"[ORDERS] No active orders found for chat_id {chat_id}. Total orders: {all_orders_count}, Orders as int: {orders_as_int}")
        await message.answer("Нет активных заказов.")
    else:
        logger.info(f"[ORDERS] Successfully sent {order_count} active order(s) to chat_id {chat_id}")

@router.callback_query(F.data.startswith("order:go:"))
async def cb_order_go(call: CallbackQuery, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"User {call.from_user.id} accepting order {external_id}")
    
    db = await get_db()
    redis = get_redis()
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    if not order:
        logger.warning(f"Order {external_id} not found")
        await call.answer("Заказ не найден", show_alert=True)
        return

    # lock to avoid double accept
    lock_key = f"order:lock:{external_id}"
    ok = await redis.set(lock_key, "1", ex=ORDER_LOCK_TTL, nx=True)
    if not ok:
        await call.answer("Кто-то уже обрабатывает этот заказ", show_alert=True)
        return

    await db.couriers_deliveries.update_one({"_id": order["_id"]}, {"$set": {"status": "in_transit", "updated_at": utcnow_iso()}})
    order = await db.couriers_deliveries.find_one({"_id": order["_id"]})
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_accepted", order_id=external_id)
    logger.info(f"User {call.from_user.id} accepted order {external_id}")
    
    # Отправка webhook
    from utils.webhooks import send_webhook, prepare_order_data
    order_data = await prepare_order_data(db, order)
    webhook_data = {
        **order_data,
        "timestamp": utcnow_iso()
    }
    await send_webhook("order_accepted", webhook_data)
    
    await call.message.edit_text(format_order_text(order), parse_mode="HTML", reply_markup=in_transit_kb(external_id, order))
    await call.answer("Статус: в пути")

@router.callback_query(F.data.startswith("order:later:"))
async def cb_order_later(call: CallbackQuery):
    external_id = call.data.split(":", 2)[2]
    db = await get_db()
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_postponed", order_id=external_id)
    await call.message.delete()
    await call.answer()

@router.callback_query(F.data.startswith("order:accept_payment:"))
async def cb_order_accept_payment(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"User {call.from_user.id} accepting payment for order {external_id}")
    
    redis = get_redis()
    # Устанавливаем флаг ожидания фотографий оплаты
    await redis.setex(f"courier:payment_photo_wait:{call.message.chat.id}", PHOTO_WAIT_TTL, external_id)
    
    db = await get_db()
    from db.models import Action
    await Action.log(db, call.from_user.id, "payment_accepted", order_id=external_id)
    
    await call.message.answer("💰 Отфотографируйте купюры и отправьте фото в бот")
    await call.answer()

@router.callback_query(F.data.startswith("order:finish_after_payment:"))
async def cb_order_finish_after_payment(call: CallbackQuery, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"User {call.from_user.id} finishing order {external_id} after payment")
    
    db = await get_db()
    redis = get_redis()
    
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    if not order:
        await call.answer("Заказ не найден", show_alert=True)
        return
    
    # Обновляем статус оплаты и статус заказа
    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {
            "$set": {
                "status": "done",
                "payment_status": "PAID",
                "updated_at": utcnow_iso()
            }
        }
    )
    
    # Удаляем флаг ожидания фотографий оплаты
    await redis.delete(f"courier:payment_photo_wait:{call.message.chat.id}")
    
    # Получаем обновленный заказ для webhook
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_completed", order_id=external_id, details={"after_payment": True})
    logger.info(f"User {call.from_user.id} completed order {external_id} after payment")
    
    # Отправка webhook
    from utils.webhooks import send_webhook, prepare_order_data
    order_data = await prepare_order_data(db, order)
    webhook_data = {
        **order_data,
        "timestamp": utcnow_iso()
    }
    await send_webhook("order_completed", webhook_data)
    
    await call.message.answer("✅ Заказ выполнен. Оплата принята.")
    await call.answer()
    
    # notify manager
    courier = await db.couriers.find_one({"tg_chat_id": call.message.chat.id})
    if courier:
        await notify_manager(bot, courier, f"📦 Курьер {courier['name']} завершил заказ {external_id} (оплата наличными)")
    
    # Показываем список активных заказов со статусом waiting
    await show_waiting_orders(call.message.chat.id, call.message)

@router.callback_query(F.data.startswith("order:done:"))
async def cb_order_done(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"User {call.from_user.id} completing order {external_id}")
    
    db = await get_db()
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    if not order:
        await call.answer("Заказ не найден", show_alert=True)
        return
    
    # Если оплата наличными и статус оплаты "не оплачен", не позволяем завершить заказ
    if order.get("is_cash_payment") and order.get("payment_status") == "NOT_PAID":
        await call.answer("Сначала примите оплату", show_alert=True)
        return
    
    redis = get_redis()
    await redis.setex(f"courier:photo_wait:{call.message.chat.id}", PHOTO_WAIT_TTL, external_id)
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_completed", order_id=external_id)
    
    await call.message.answer("📸 Пришли фото подтверждение (чек или доставка)")
    await call.answer()

@router.callback_query(F.data.startswith("order:problem:"))
async def cb_order_problem(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"User {call.from_user.id} reported problem with order {external_id}")
    
    redis = get_redis()
    await redis.setex(f"courier:problem_wait:{call.message.chat.id}", PHOTO_WAIT_TTL, external_id)
    
    db = await get_db()
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_problem", order_id=external_id)
    
    await call.message.answer(f"⚠ Опиши коротко проблему по заказу {external_id}, чтобы менеджер помог")
    await call.answer()

@router.message(F.text == "/history_today")
async def cmd_history_today(message: Message):
    db = await get_db()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
    
    cursor = db.couriers_deliveries.find({
        "courier_tg_chat_id": message.chat.id,
        "created_at": {"$gte": today_start}
    }).sort("created_at", -1)
    
    found = False
    async for order in cursor:
        found = True
        text = format_order_text(order)
        if order["status"] in ["waiting", "in_transit"]:
            kb = new_order_kb(order["external_id"]) if order["status"] == "waiting" else in_transit_kb(order["external_id"], order)
            await message.answer(text, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(text, parse_mode="HTML")
    
    if not found:
        await message.answer("Сегодня заказов не было.")

@router.message(F.text == "/history_all")
async def cmd_history_all(message: Message):
    await show_history_page(message, 0)

@router.callback_query(F.data.startswith("history:page:"))
async def cb_history_page(call: CallbackQuery):
    page = int(call.data.split(":")[2])
    await show_history_page(call.message, page)
    await call.answer()

async def show_history_page(message: Message, page: int):
    db = await get_db()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
    
    skip = page * 30
    cursor = db.couriers_deliveries.find({
        "courier_tg_chat_id": message.chat.id,
        "created_at": {"$lt": today_start}
    }).sort("created_at", -1).skip(skip).limit(30)
    
    orders = await cursor.to_list(length=30)
    
    if not orders:
        if page == 0:
            await message.answer("История заказов пуста.")
        else:
            await message.answer("Больше заказов нет.")
        return
    
    for order in orders:
        text = format_order_text(order)
        await message.answer(text, parse_mode="HTML")
    
    # Last message with buttons
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Еще", callback_data=f"history:page:{page + 1}")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])
    await message.answer(f"Показано {len(orders)} заказов (страница {page + 1})", reply_markup=kb)

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery):
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": call.message.chat.id})
    is_on_shift = courier.get("is_on_shift", False) if courier else False
    await call.message.answer("Главное меню:", reply_markup=main_menu(is_on_shift))
    await call.answer()

@router.message(F.text & ~F.via_bot & ~F.forward_from_chat)
async def catch_problem_text(message: Message, bot: Bot):
    redis = get_redis()
    external_id = await redis.get(f"courier:problem_wait:{message.chat.id}")
    
    if not external_id:
        return
    
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    if not courier:
        return
    
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    if not order:
        await message.answer("Заказ не найден")
        return
    
    # Save message to order history
    timestamp = utcnow_iso()
    problem_entry = {
        f"courier-{timestamp}": message.text
    }
    
    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {
            "$push": {"problem_messages": problem_entry},
            "$set": {"updated_at": timestamp}
        }
    )
    
    await redis.delete(f"courier:problem_wait:{message.chat.id}")
    
    # Notify manager with full info
    client = order.get('client', {})
    msg = (
        f"💬 ПРОБЛЕМА:\n\"{message.text}\"\n\n"
        f"📝 Заказ: {external_id}\n"
        f"🚚 Курьер: {courier['name']}\n\n"
        f"👤 Клиент: {client.get('name', '—')}\n"
        f"📞 Телефон: {client.get('phone', '—')}\n"
    )
    
    if client.get('tg'):
        msg += f"👤 Telegram: {client['tg']}\n"
    
    msg += f"\n📍 Адрес: {order.get('address', '—')}\n"
    
    if order.get('map_url'):
        msg += f"🗺 Карта: {order['map_url']}\n"
    
    if order.get('notes'):
        msg += f"\n📝 Примечания: {order['notes']}\n"
    
    if order.get('brand'):
        msg += f"\n🏷 Бренд: {order['brand']}\n"
    
    if order.get('source'):
        msg += f"📊 Источник: {order['source']}\n"
    
    await notify_manager(bot, courier, msg)
    
    await message.answer("✅ Сообщение отправлено менеджеру")