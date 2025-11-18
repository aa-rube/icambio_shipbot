from aiogram import Router, F
from aiogram.types import Message
from keyboards.main_menu import main_menu
from db.mongo import get_db
from datetime import datetime, timezone

router = Router()

@router.message(F.text == "/start")
@router.message(F.text == "start")
async def cmd_start(message: Message):
    """Обработчик /start - определяет админ или курьер и вызывает соответствующий обработчик"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"User {message.from_user.id} started bot")
    
    db = await get_db()
    
    # Проверяем, является ли пользователь админом
    from handlers.admin import is_super_admin
    if await is_super_admin(message.from_user.id):
        # Если админ - вызываем логику /admin
        logger.info(f"[START] Пользователь {message.from_user.id} - админ, вызываем /admin")
        from keyboards.admin_kb import admin_main_kb
        await message.answer("🔧 Админ-панель", reply_markup=admin_main_kb())
        return
    
    # Проверяем, является ли пользователь курьером
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    if not courier:
        logger.warning(f"[START] User {message.from_user.id} не найден ни как админ, ни как курьер, игнорируем /start")
        return
    
    # Если курьер - вызываем логику /main
    logger.info(f"[START] Пользователь {message.from_user.id} - курьер, вызываем /main")
    await cmd_main(message)

@router.message(F.text == "/main")
@router.message(F.text == "main")
async def cmd_main(message: Message):
    """Обработчик /main - главное меню для курьера"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"User {message.from_user.id} использует команду /main")
    
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    
    if not courier:
        logger.warning(f"User {message.from_user.id} not found in couriers, ignoring /main")
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
