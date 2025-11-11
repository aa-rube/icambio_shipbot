from aiogram import Router, F
from aiogram.types import Message
from keyboards.main_menu import main_menu
from db.mongo import get_db
from datetime import datetime, timezone

router = Router()

@router.message(F.text == "/start")
@router.message(F.text == "start")
@router.message(F.text == "/main")
@router.message(F.text == "main")
async def cmd_start(message: Message):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"User {message.from_user.id} started bot")
    
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    
    if not courier:
        logger.warning(f"User {message.from_user.id} not found in couriers, ignoring /start")
        return
    
    from db.models import Action
    await Action.log(db, message.from_user.id, "user_start")

    # stats
    now = datetime.now(timezone.utc)
    start_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    monthly = await db.orders.count_documents({
        "assigned_to": courier["_id"],
        "created_at": {"$gte": start_month.isoformat()}
    })
    today = await db.orders.count_documents({
        "assigned_to": courier["_id"],
        "created_at": {"$gte": start_today.isoformat()}
    })
    active = await db.orders.count_documents({
        "assigned_to": courier["_id"],
        "status": {"$in": ["waiting", "in_transit"]}
    })

    text = (
        f"Привет, {courier['name']}!\n\n"
        f"🚚 Заказов в этом месяце: {monthly}\n"
        f"📅 Сегодня: {today}\n"
        f"📦 Активные: {active}"
    )
    is_on_shift = courier.get("is_on_shift", False)
    await message.answer(text, reply_markup=main_menu(is_on_shift))
