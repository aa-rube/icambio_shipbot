from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from db.mongo import get_db
from keyboards.admin_kb import admin_main_kb, back_to_admin_kb, user_list_kb, confirm_delete_kb, broadcast_kb, request_user_kb, courier_location_kb, courier_location_with_back_kb, location_back_kb, route_back_kb
from db.redis_client import get_redis
from utils.url_shortener import shorten_url

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

@router.callback_query(F.data.startswith("admin:back_from_couriers:"))
async def cb_back_from_couriers(call: CallbackQuery, state: FSMContext):
    await state.clear()
    # Извлекаем chat_id курьера из callback_data
    chat_id = int(call.data.split(":", 2)[2])
    # Сохраняем текст сообщения
    message_text = call.message.text or call.message.caption or ""
    
    # Проверяем, есть ли маршрут для этого курьера
    try:
        from datetime import datetime, timezone, timedelta
        db = await get_db()
        now = datetime.now(timezone.utc)
        time_72h_ago = now - timedelta(hours=72)
        
        # Проверяем наличие локаций за последние 72 часа
        has_route = await db.locations.find_one({
            "chat_id": chat_id,
            "timestamp_ns": {"$gte": int(time_72h_ago.timestamp() * 1e9)}
        }) is not None
        
        # Редактируем сообщение, изменяя клавиатуру: убираем "Назад", оставляем callback кнопки
        await call.message.edit_text(message_text, reply_markup=courier_location_kb(chat_id, has_route))
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to update location redirect for courier {chat_id}: {e}")
        # Если не удалось обновить редирект, просто убираем кнопку "Назад"
        await call.message.edit_text(message_text, reply_markup=None)
    
    # Отправляем новое сообщение с главным меню
    await call.message.answer("🔧 Админ-панель", reply_markup=admin_main_kb())
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
    
    await call.message.edit_text("➕ Добавление курьера", reply_markup=back_to_admin_kb())
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
        await message.answer(f"ℹ️ Курьер {user_id} уже существует")
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
    
    # Создание курьера в Odoo
    odoo_created = False
    try:
        from utils.odoo import create_courier
        # create_courier использует courier_tg_chat_id как основной идентификатор
        # Автоматически обновляет существующего курьера или создает нового
        odoo_result = await create_courier(
            name=full_name,
            courier_tg_chat_id=str(user_id),
            phone=None,  # Телефон можно добавить позже
            is_online=False
        )
        if odoo_result:
            logger.info(f"Courier created/updated in Odoo for user {user_id} (courier_tg_chat_id: {user_id})")
            odoo_created = True
        else:
            logger.warning(f"Failed to create courier in Odoo for user {user_id}")
    except Exception as e:
        logger.error(f"Error creating courier in Odoo: {e}", exc_info=True)
    
    courier = {
        "name": full_name,
        "username": username,
        "tg_chat_id": user_id,
        "is_on_shift": False,
        "shift_started_at": None,
        "last_location": None,
        "odoo_id": str(user_id),  # odoo_id = courier_tg_chat_id (основной идентификатор)
    }
    await db.couriers.insert_one(courier)
    logger.info(f"Admin {message.from_user.id} added user {user_id} ({full_name}), Odoo: {'created' if odoo_created else 'failed'}")
    
    odoo_status = "\n✅ Odoo: создан/обновлен" if odoo_created else "\n⚠️ Odoo: не создан"
    username_text = f"Username: @{username}\n" if username else ""
    await message.answer(
        f"✅ Курьер добавлен\n"
        f"ID: {user_id}\n"
        f"Имя: {full_name}\n"
        f"{username_text}"
        f"{odoo_status}",
        reply_markup=admin_main_kb()
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

@router.callback_query(F.data == "admin:on_shift")
async def cb_on_shift_couriers(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    db = await get_db()
    from datetime import datetime, timezone
    
    # Получаем всех курьеров на смене
    couriers = await db.couriers.find({"is_on_shift": True}).to_list(1000)
    
    if not couriers:
        await call.message.edit_text(
            "🚚 Курьеры на смене\n\nНет курьеров на смене",
            reply_markup=back_to_admin_kb()
        )
        await call.answer()
        return
    
    # Если есть курьеры, удаляем сообщение с кнопкой
    admin_chat_id = call.message.chat.id
    bot = call.message.bot
    await call.message.delete()
    
    # Для каждого курьера формируем отдельное сообщение
    now = datetime.now(timezone.utc)
    start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    
    for idx, courier in enumerate(couriers):
        chat_id = courier.get("tg_chat_id")
        name = courier.get("name", "Unknown")
        username = courier.get("username")
        username_text = f"@{username}" if username else ""
        
        # Статистика заказов за сегодня
        total_today = await db.couriers_deliveries.count_documents({
            "courier_tg_chat_id": chat_id,
            "created_at": {"$gte": start_today.isoformat()}
        })
        
        delivered_today = await db.couriers_deliveries.count_documents({
            "courier_tg_chat_id": chat_id,
            "status": "done",
            "created_at": {"$gte": start_today.isoformat()}
        })
        
        waiting_orders = await db.couriers_deliveries.count_documents({
            "courier_tg_chat_id": chat_id,
            "status": {"$in": ["waiting", "in_transit"]}
        })
        
        # Определяем статус курьера
        in_transit_order = await db.couriers_deliveries.find_one({
            "courier_tg_chat_id": chat_id,
            "status": "in_transit"
        })
        
        if in_transit_order:
            status_text = f"В пути ({in_transit_order.get('external_id', 'N/A')})"
        elif waiting_orders > 0:
            status_text = "Есть заказы"
        else:
            status_text = "Нет заказов"
        
        # Время начала смены
        shift_started_at = courier.get("shift_started_at")
        shift_time_text = "Не указано"
        if shift_started_at:
            try:
                shift_dt = datetime.fromisoformat(shift_started_at.replace('Z', '+00:00'))
                shift_time_text = shift_dt.strftime("%H:%M")
            except:
                shift_time_text = shift_started_at
        
        text = (
            f"👤 {name} {username_text}\n\n"
            f"Статус: {status_text}\n\n"
            f"Заказы:\n"
            f"Всего: {total_today}\n"
            f"Доставлено: {delivered_today}\n"
            f"Ожидают: {waiting_orders}\n\n"
            f"Вышел на смену: {shift_time_text}"
        )
        
        # Генерируем ключи редиректа и URL для кнопок
        try:
            # Отправляем сообщение сначала, чтобы получить msg_id
            temp_msg = await bot.send_message(admin_chat_id, text)
            msg_id = temp_msg.message_id
            
            # Проверяем наличие маршрута для этого курьера
            from datetime import timedelta
            time_72h_ago = now - timedelta(hours=72)
            has_route = await db.locations.find_one({
                "chat_id": chat_id,
                "timestamp_ns": {"$gte": int(time_72h_ago.timestamp() * 1e9)}
            }) is not None
            
            # Редактируем сообщение с правильной клавиатурой
            if idx == len(couriers) - 1:
                # Для последнего сообщения добавляем кнопку "Назад"
                await bot.edit_message_reply_markup(
                    chat_id=admin_chat_id,
                    message_id=msg_id,
                    reply_markup=courier_location_with_back_kb(chat_id, has_route)
                )
            else:
                # Для остальных сообщений кнопки "Где курьер?" и "Маршрут сегодня" (если доступен)
                await bot.edit_message_reply_markup(
                    chat_id=admin_chat_id,
                    message_id=msg_id,
                    reply_markup=courier_location_kb(chat_id, has_route)
                )
        except Exception as e:
            logger.error(f"Failed to create courier message for {chat_id}: {e}", exc_info=True)
            # Если не удалось создать сообщение, отправляем без кнопок
            await bot.send_message(admin_chat_id, text)
    
    await call.answer()

@router.callback_query(F.data.startswith("admin:show_location:"))
async def cb_show_location(call: CallbackQuery):
    """Обработчик кнопки 'Где курьер?' - показывает сообщение с прямой ссылкой на Google Maps"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    chat_id = int(call.data.split(":", 2)[2])
    
    try:
        # Получаем последнюю локацию курьера
        redis = get_redis()
        loc_str = await redis.get(f"courier:loc:{chat_id}")
        
        lat = None
        lon = None
        
        if loc_str:
            # Парсим координаты из Redis: "lat,lon"
            try:
                parts = loc_str.split(",")
                if len(parts) == 2:
                    lat = float(parts[0])
                    lon = float(parts[1])
            except (ValueError, IndexError):
                pass
        
        # Если не нашли в Redis, ищем в БД
        if lat is None or lon is None:
            db = await get_db()
            last_location = await db.locations.find_one(
                {"chat_id": chat_id},
                sort=[("timestamp_ns", -1)]
            )
            
            if not last_location:
                await call.answer("❌ Локация не найдена", show_alert=True)
                return
            
            lat = last_location.get("lat")
            lon = last_location.get("lon")
            
            if not lat or not lon:
                await call.answer("❌ Координаты не найдены", show_alert=True)
                return
        
        # Валидация координат
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            await call.answer("❌ Некорректные координаты", show_alert=True)
            return
        
        # Формируем прямую ссылку на Google Maps
        maps_url = f"https://maps.google.com/?q={lat},{lon}"
        
        # Формируем текст с гиперссылкой
        text = f'Посмотреть местоположение по <a href="{maps_url}">ссылке</a>'
        
        # Изменяем сообщение
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=location_back_kb(chat_id))
        await call.answer()
    except Exception as e:
        logger.error(f"Failed to show location for courier {chat_id}: {e}", exc_info=True)
        await call.answer("❌ Не удалось получить местоположение", show_alert=True)

@router.callback_query(F.data.startswith("admin:show_route:"))
async def cb_show_route(call: CallbackQuery):
    """Обработчик кнопки 'Маршрут сегодня' - показывает сообщение с прямой ссылкой на маршрут в Google Maps"""
    import logging
    from datetime import datetime, timezone, timedelta
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    chat_id = int(call.data.split(":", 2)[2])
    
    try:
        db = await get_db()
        now = datetime.now(timezone.utc)
        time_72h_ago = now - timedelta(hours=72)
        time_24h_ago = now - timedelta(hours=24)
        
        # Получаем все локации за последние 72 часа, отсортированные по timestamp
        locations = await db.locations.find(
            {
                "chat_id": chat_id,
                "timestamp_ns": {"$gte": int(time_72h_ago.timestamp() * 1e9)}
            }
        ).sort("timestamp_ns", 1).to_list(10000)  # Сортируем от меньшего к большему
        
        if not locations:
            await call.answer("❌ Локации не найдены", show_alert=True)
            return
        
        # Проверяем последнюю локацию - она должна быть не старше 24 часов
        last_location = locations[-1]
        last_location_time = datetime.fromtimestamp(last_location.get("timestamp_ns", 0) / 1e9, tz=timezone.utc)
        
        if last_location_time < time_24h_ago:
            # Если последняя локация старше 24 часов, ищем последнюю локацию за 24 часа
            recent_location = await db.locations.find_one(
                {
                    "chat_id": chat_id,
                    "timestamp_ns": {"$gte": int(time_24h_ago.timestamp() * 1e9)}
                },
                sort=[("timestamp_ns", -1)]
            )
            
            if recent_location:
                # Используем последнюю локацию за 24 часа как финальную точку
                locations = [loc for loc in locations if loc.get("timestamp_ns") <= recent_location.get("timestamp_ns")]
                locations.append(recent_location)
        
        if len(locations) < 2:
            # Если только одна точка, просто показываем её
            loc = locations[0]
            maps_url = f"https://maps.google.com/?q={loc['lat']},{loc['lon']}"
        else:
            # Формируем waypoints
            waypoints = []
            for loc in locations:
                lat = loc.get("lat")
                lon = loc.get("lon")
                if lat is not None and lon is not None:
                    # Валидация координат
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        waypoints.append(f"{lat},{lon}")
            
            if len(waypoints) < 2:
                # Если после валидации осталось меньше 2 точек
                loc = locations[0]
                maps_url = f"https://maps.google.com/?q={loc['lat']},{loc['lon']}"
            else:
                # Создаем URL с маршрутом (со всеми точками)
                waypoints_str = "/".join(waypoints)
                maps_url = f"https://www.google.com/maps/dir/{waypoints_str}"
                
                # Сокращаем URL через сервис сокращения ссылок
                # Это необходимо, так как Telegram имеет ограничение на длину HTML-сущностей (ссылок)
                maps_url = await shorten_url(maps_url)
        
        # Формируем текст с гиперссылкой
        text = f'Посмотреть маршрут по <a href="{maps_url}">ссылке</a>'
        
        # Изменяем сообщение
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=route_back_kb(chat_id))
        await call.answer()
    except Exception as e:
        logger.error(f"Failed to show route for courier {chat_id}: {e}", exc_info=True)
        await call.answer("❌ Не удалось получить маршрут", show_alert=True)

@router.callback_query(F.data.startswith("admin:back_to_courier:"))
async def cb_back_to_courier(call: CallbackQuery):
    """Обработчик кнопки 'Назад' - возвращает к исходному сообщению курьера"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    chat_id = int(call.data.split(":", 2)[2])
    
    try:
        # Перестраиваем текст сообщения из актуальных данных базы
        db = await get_db()
        from datetime import datetime, timezone
        
        courier = await db.couriers.find_one({"tg_chat_id": chat_id})
        if not courier:
            await call.answer("❌ Курьер не найден", show_alert=True)
            return
        
        name = courier.get("name", "Unknown")
        username = courier.get("username")
        username_text = f"@{username}" if username else ""
        
        now = datetime.now(timezone.utc)
        start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        
        total_today = await db.couriers_deliveries.count_documents({
            "courier_tg_chat_id": chat_id,
            "created_at": {"$gte": start_today.isoformat()}
        })
        
        delivered_today = await db.couriers_deliveries.count_documents({
            "courier_tg_chat_id": chat_id,
            "status": "done",
            "created_at": {"$gte": start_today.isoformat()}
        })
        
        waiting_orders = await db.couriers_deliveries.count_documents({
            "courier_tg_chat_id": chat_id,
            "status": {"$in": ["waiting", "in_transit"]}
        })
        
        in_transit_order = await db.couriers_deliveries.find_one({
            "courier_tg_chat_id": chat_id,
            "status": "in_transit"
        })
        
        if in_transit_order:
            status_text = f"В пути ({in_transit_order.get('external_id', 'N/A')})"
        elif waiting_orders > 0:
            status_text = "Есть заказы"
        else:
            status_text = "Нет заказов"
        
        shift_started_at = courier.get("shift_started_at")
        shift_time_text = "Не указано"
        if shift_started_at:
            try:
                shift_dt = datetime.fromisoformat(shift_started_at.replace('Z', '+00:00'))
                shift_time_text = shift_dt.strftime("%H:%M")
            except:
                shift_time_text = shift_started_at
        
        text = (
            f"👤 {name} {username_text}\n\n"
            f"Статус: {status_text}\n\n"
            f"Заказы:\n"
            f"Всего: {total_today}\n"
            f"Доставлено: {delivered_today}\n"
            f"Ожидают: {waiting_orders}\n\n"
            f"Вышел на смену: {shift_time_text}"
        )
        
        # Проверяем наличие маршрута для этого курьера
        from datetime import timedelta
        time_72h_ago = now - timedelta(hours=72)
        has_route = await db.locations.find_one({
            "chat_id": chat_id,
            "timestamp_ns": {"$gte": int(time_72h_ago.timestamp() * 1e9)}
        }) is not None
        
        # Восстанавливаем исходное сообщение с кнопками
        await call.message.edit_text(text, reply_markup=courier_location_kb(chat_id, has_route))
        await call.answer()
    except Exception as e:
        logger.error(f"Failed to restore courier message for {chat_id}: {e}", exc_info=True)
        await call.answer("❌ Не удалось восстановить сообщение", show_alert=True)


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
