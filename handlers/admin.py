from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from db.mongo import get_db
from keyboards.admin_kb import admin_main_kb, back_to_admin_kb, user_list_kb, confirm_delete_kb, broadcast_kb, request_user_kb

router = Router()

class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_broadcast_text = State()

async def is_super_admin(user_id: int) -> bool:
    import logging
    logger = logging.getLogger(__name__)
    db = await get_db()
    
    doc = await db.bot_super_admins.find_one()
    logger.info(f"First doc in bot_super_admins: {doc}")
    
    if not doc:
        logger.warning("No documents found in bot_super_admin collection")
        return False
    
    admins = doc.get("adminsType", {})
    logger.info(f"adminsType: {admins}")
    user_type = admins.get(str(user_id))
    logger.info(f"User {user_id} type: {user_type}")
    return user_type == "SUPER_ADMIN"

@router.message(F.text == "/admin")
async def cmd_admin(message: Message):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Admin panel access attempt by user {message.from_user.id}")
    if not await is_super_admin(message.from_user.id):
        logger.warning(f"Access denied for user {message.from_user.id}")
        await message.answer("❌ Доступ запрещен")
        return
    logger.info(f"Admin panel opened by user {message.from_user.id}")
    await message.answer("🔧 Админ-панель", reply_markup=admin_main_kb())

@router.callback_query(F.data == "admin:back")
async def cb_admin_back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🔧 Админ-панель", reply_markup=admin_main_kb())
    await call.answer()

@router.callback_query(F.data == "admin:add_user")
async def cb_add_user(call: CallbackQuery, state: FSMContext):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Admin add user callback from {call.from_user.id}")
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_user_id)
    logger.info(f"State set to waiting_user_id for {call.from_user.id}")
    
    await call.message.edit_text("➕ Добавление пользователя", reply_markup=back_to_admin_kb())
    await call.message.answer("Выбери пользователя из контактов:", reply_markup=request_user_kb())
    await call.answer()

@router.message(F.user_shared)
async def process_add_user(message: Message, state: FSMContext, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Received user_shared from {message.from_user.id}: {message.user_shared}")
    
    current_state = await state.get_state()
    logger.info(f"Current state: {current_state}")
    
    if current_state != AdminStates.waiting_user_id:
        logger.warning(f"user_shared received but state is {current_state}")
        return
    
    if not await is_super_admin(message.from_user.id):
        logger.warning(f"Non-admin tried to add user: {message.from_user.id}")
        return
    
    user_id = message.user_shared.user_id
    logger.info(f"Admin {message.from_user.id} selected user {user_id}")
    
    db = await get_db()
    existing = await db.couriers.find_one({"tg_chat_id": user_id})
    if existing:
        logger.info(f"User {user_id} already exists, skipping add")
        await message.answer(f"ℹ️ Пользователь {user_id} уже существует")
        await state.clear()
        return
    
    try:
        chat = await bot.get_chat(user_id)
        full_name = chat.full_name or f"user_{user_id}"
        username = chat.username
        logger.info(f"Fetched user info: full_name={full_name}, username={username}")
    except Exception as e:
        logger.warning(f"Failed to fetch user info for {user_id}: {e}")
        full_name = f"user_{user_id}"
        username = None
    
    from db.models import Action
    await Action.log(db, message.from_user.id, "admin_add_user", details={"added_user_id": user_id, "name": full_name})
    
    courier = {
        "name": full_name,
        "username": username,
        "tg_chat_id": user_id,
        "is_on_shift": False,
        "shift_started_at": None,
        "last_location": None,
    }
    await db.couriers.insert_one(courier)
    logger.info(f"Admin {message.from_user.id} added user {user_id} ({full_name})")
    
    await message.answer(
        f"✅ Пользователь добавлен\n"
        f"ID: {user_id}\n"
        f"Имя: {full_name}\n"
        f"Username: @{username}" if username else ""
    )
    await state.clear()

@router.callback_query(F.data == "admin:del_user")
async def cb_del_user(call: CallbackQuery):
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    db = await get_db()
    couriers = await db.couriers.find().sort("name", 1).to_list(100)
    
    if not couriers:
        await call.message.edit_text("ℹ️ Нет пользователей", reply_markup=back_to_admin_kb())
        await call.answer()
        return
    
    await call.message.edit_text(
        "➖ Удаление пользователя\n\nВыбери пользователя для удаления:",
        reply_markup=user_list_kb(couriers)
    )
    await call.answer()

@router.callback_query(F.data.startswith("admin:confirm_del:"))
async def cb_confirm_del(call: CallbackQuery):
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    chat_id = int(call.data.split(":", 2)[2])
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    
    if not courier:
        await call.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    await call.message.edit_text(
        f"⚠️ Подтверди удаление\n\n"
        f"Пользователь: {courier.get('name', 'Unknown')}\n"
        f"ID: {chat_id}",
        reply_markup=confirm_delete_kb(chat_id)
    )
    await call.answer()

@router.callback_query(F.data.startswith("admin:delete:"))
async def cb_delete_user(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    chat_id = int(call.data.split(":", 2)[2])
    db = await get_db()
    result = await db.couriers.delete_one({"tg_chat_id": chat_id})
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "admin_del_user", details={"deleted_user_id": chat_id})
    
    if result.deleted_count > 0:
        logger.info(f"Admin {call.from_user.id} deleted user {chat_id}")
        await call.message.edit_text(
            f"✅ Пользователь {chat_id} удален",
            reply_markup=admin_main_kb()
        )
    else:
        logger.warning(f"Failed to delete user {chat_id} by admin {call.from_user.id}")
        await call.message.edit_text(
            "❌ Не удалось удалить пользователя",
            reply_markup=admin_main_kb()
        )
    await call.answer()

@router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast(call: CallbackQuery):
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    await call.message.edit_text(
        "📢 Рассылка\n\nВыбери группу получателей:",
        reply_markup=broadcast_kb()
    )
    await call.answer()

@router.callback_query(F.data.startswith("admin:bc:"))
async def cb_broadcast_group(call: CallbackQuery, state: FSMContext):
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    group = call.data.split(":", 2)[2]
    await state.update_data(broadcast_group=group)
    await state.set_state(AdminStates.waiting_broadcast_text)
    
    group_name = {
        "all": "всем курьерам",
        "on_shift": "курьерам на смене",
        "off_shift": "курьерам не на смене"
    }.get(group, "выбранной группе")
    
    await call.message.edit_text(
        f"📢 Рассылка {group_name}\n\n"
        "Отправь текст сообщения для рассылки:",
        reply_markup=back_to_admin_kb()
    )
    await call.answer()

@router.message(AdminStates.waiting_broadcast_text)
async def process_broadcast(message: Message, state: FSMContext, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    if not await is_super_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    group = data.get("broadcast_group", "all")
    
    db = await get_db()
    query = {}
    if group == "on_shift":
        query["is_on_shift"] = True
    elif group == "off_shift":
        query["is_on_shift"] = False
    
    couriers = await db.couriers.find(query).to_list(1000)
    logger.info(f"Admin {message.from_user.id} starting broadcast to {len(couriers)} couriers (group: {group})")
    
    sent = 0
    failed = 0
    
    from db.models import Action
    await Action.log(db, message.from_user.id, "admin_broadcast", details={"group": group, "text": message.text})
    
    for courier in couriers:
        try:
            await bot.send_message(courier["tg_chat_id"], f"📢 {message.text}")
            sent += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast to {courier['tg_chat_id']}: {e}")
            failed += 1
    
    logger.info(f"Broadcast completed: sent={sent}, failed={failed}")
    await message.answer(
        f"✅ Рассылка завершена\n\n"
        f"Отправлено: {sent}\n"
        f"Ошибок: {failed}",
        reply_markup=admin_main_kb()
    )
    await state.clear()
