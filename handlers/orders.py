from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from db.mongo import get_db
from db.redis_client import get_redis
from keyboards.orders_kb import new_order_kb, in_transit_kb
from utils.notifications import notify_manager
from config import ORDER_LOCK_TTL, PHOTO_WAIT_TTL
from db.models import utcnow_iso

router = Router()

def format_order_text(order: dict) -> str:
    lines = [
        "📦 Новый заказ" if order["status"] == "waiting" else "🚗 В пути",
        f"Номер: {order.get('external_id','—')}",
        f"Клиент: {order.get('client',{}).get('name','—')}",
        f"Телефон: {order.get('client',{}).get('phone','—')}",
        f"Адрес: {order.get('address','—')}",
    ]
    if order.get("map_url"):
        lines.append(f"Карта: {order['map_url']}")
    if order.get("notes"):
        lines.append(f"Примечание: {order['notes']}")
    return "\n".join(lines)

@router.message(F.text == "📋 Мои заказы")
async def my_orders(message: Message):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"User {message.from_user.id} viewing orders")
    
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    if not courier:
        await message.answer("Сначала отправь /start")
        return
    
    from db.models import Action
    await Action.log(db, message.from_user.id, "order_viewed")
    
    cursor = db.orders.find({
        "assigned_to": courier["_id"],
        "status": {"$in": ["waiting", "in_transit"]}
    }).sort("created_at", 1)
    found = False
    async for order in cursor:
        found = True
        text = format_order_text(order)
        if order["status"] == "waiting":
            await message.answer(text, reply_markup=new_order_kb(order["external_id"]))
        elif order["status"] == "in_transit":
            await message.answer(text, reply_markup=in_transit_kb(order["external_id"]))
    if not found:
        await message.answer("Нет активных заказов.")

@router.callback_query(F.data.startswith("order:go:"))
async def cb_order_go(call: CallbackQuery, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"User {call.from_user.id} accepting order {external_id}")
    
    db = await get_db()
    redis = get_redis()
    order = await db.orders.find_one({"external_id": external_id})
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

    await db.orders.update_one({"_id": order["_id"]}, {"$set": {"status": "in_transit", "updated_at": utcnow_iso()}})
    order = await db.orders.find_one({"_id": order["_id"]})
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_accepted", order_id=external_id)
    logger.info(f"User {call.from_user.id} accepted order {external_id}")
    
    await call.message.edit_text(format_order_text(order), reply_markup=in_transit_kb(external_id))
    await call.answer("Статус: в пути")

@router.callback_query(F.data.startswith("order:later:"))
async def cb_order_later(call: CallbackQuery):
    external_id = call.data.split(":", 2)[2]
    db = await get_db()
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_postponed", order_id=external_id)
    await call.answer("Ок, напомню позже")

@router.callback_query(F.data.startswith("order:done:"))
async def cb_order_done(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"User {call.from_user.id} completing order {external_id}")
    
    redis = get_redis()
    await redis.setex(f"courier:photo_wait:{call.message.chat.id}", PHOTO_WAIT_TTL, external_id)
    
    db = await get_db()
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
    
    db = await get_db()
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_problem", order_id=external_id)
    
    await call.message.answer(f"⚠ Опиши коротко проблему по заказу {external_id}, чтобы менеджер помог")
    await call.answer()

@router.message(F.text & ~F.via_bot & ~F.forward_from_chat)
async def catch_problem_text(message: Message, bot: Bot):
    # if message is plain text right after "Проблема", forward to manager
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    if not courier:
        return
    # Heuristic: if there's any active in_transit order, treat text as a problem (better UX would use FSM)
    order = await db.orders.find_one({"assigned_to": courier["_id"], "status": "in_transit"}, sort=[("updated_at", -1)])
    if order:
        msg = (
            f"🚨 Проблема с заказом {order['external_id']}\n"
            f"Курьер: {courier['name']}\n"
            f"Сообщение: \"{message.text}\""
        )
        await notify_manager(bot, courier, msg)