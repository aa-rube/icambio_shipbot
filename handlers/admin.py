from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from db.mongo import get_db
from keyboards.admin_kb import admin_main_kb, back_to_admin_kb, user_list_kb, confirm_delete_kb, broadcast_kb, request_user_kb, courier_location_kb, courier_location_with_back_kb, location_back_kb, route_back_kb, active_orders_kb, order_edit_kb, courier_list_kb, all_deliveries_kb, all_orders_list_kb, courier_transfer_kb
from db.redis_client import get_redis
from utils.url_shortener import shorten_url
from utils.test_orders import is_test_order
from utils.webhooks import send_webhook, prepare_order_data
from config import TIMEZONE

router = Router()

class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_broadcast_text = State()

async def _create_courier_in_odoo(name: str, tg_id: str, username: Optional[str], is_on_shift: bool) -> bool:
    """
    Общая функция для создания курьера в Odoo.
    Используется как при добавлении курьера через админку, так и при синхронизации.
    
    Args:
        name: Имя курьера
        tg_id: Telegram Chat ID курьера (строка)
        username: Username курьера (опционально, не сохраняется в Odoo)
        is_on_shift: Статус онлайн/оффлайн
        
    Returns:
        True если успешно создан, False в противном случае
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        from utils.odoo import create_courier
        logger.debug(f"[ADMIN] 🔌 Создание курьера в Odoo: tg_id={tg_id}, name={name}")
        odoo_result = await create_courier(
            name=name,
            courier_tg_chat_id=tg_id,
            phone=None,
            username=username,
            is_online=is_on_shift
        )
        if odoo_result:
            logger.info(f"[ADMIN] ✅ Курьер создан в Odoo: tg_id={tg_id}, name={name}")
            return True
        else:
            logger.warning(f"[ADMIN] ⚠️ Не удалось создать курьера в Odoo: tg_id={tg_id}, name={name}")
            return False
    except Exception as e:
        logger.error(f"[ADMIN] ❌ Ошибка создания курьера в Odoo: {e}", exc_info=True)
        return False

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

# --- Reusable helper functions for API ---

async def get_courier_statistics(chat_id: int, db) -> Dict[str, Any]:
    """
    Получает статистику курьера: заказы за сегодня, доставленные, ожидающие, статус.
    
    Returns:
        dict с ключами: total_today, delivered_today, waiting_orders, status, status_text
    """
    now = datetime.now(TIMEZONE)
    start_today = datetime(now.year, now.month, now.day, tzinfo=TIMEZONE)
    
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
        status = "in_transit"
    elif waiting_orders > 0:
        status_text = "Есть заказы"
        status = "has_orders"
    else:
        status_text = "Нет заказов"
        status = "no_orders"
    
    return {
        "total_today": total_today,
        "delivered_today": delivered_today,
        "waiting_orders": waiting_orders,
        "status": status,
        "status_text": status_text,
        "in_transit_order": in_transit_order
    }

def format_shift_time(shift_started_at: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Форматирует время начала смены в читаемый формат.
    
    Returns:
        tuple: (readable_text, iso_string)
    """
    if not shift_started_at:
        return "Не указано", None
    
    try:
        if shift_started_at.endswith('Z'):
            shift_dt = datetime.fromisoformat(shift_started_at.replace('Z', '+00:00'))
        else:
            shift_dt = datetime.fromisoformat(shift_started_at)
        if shift_dt.tzinfo is None:
            shift_dt = shift_dt.replace(tzinfo=TIMEZONE)
        elif shift_dt.tzinfo != TIMEZONE:
            shift_dt = shift_dt.astimezone(TIMEZONE)
        months_ru = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
        month_ru = months_ru[shift_dt.month - 1]
        shift_time_text = f"{shift_dt.day} {month_ru}. {shift_dt.strftime('%H:%M')}"
        return shift_time_text, shift_started_at
    except:
        return shift_started_at, shift_started_at

async def get_courier_location(chat_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает последнюю известную локацию курьера из Redis или БД.
    
    Returns:
        dict с ключами: lat, lon, timestamp или None если не найдено
    """
    redis = get_redis()
    loc_str = await redis.get(f"courier:loc:{chat_id}")
    
    lat = None
    lon = None
    
    if loc_str:
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
            return None
        
        lat = last_location.get("lat")
        lon = last_location.get("lon")
        
        if not lat or not lon:
            return None
    
    # Валидация координат
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    
    # Получаем timestamp из БД если есть
    db = await get_db()
    last_location = await db.locations.find_one(
        {"chat_id": chat_id},
        sort=[("timestamp_ns", -1)]
    )
    timestamp = None
    if last_location and last_location.get("timestamp_ns"):
        timestamp = datetime.fromtimestamp(last_location.get("timestamp_ns", 0) / 1e9, tz=TIMEZONE).isoformat()
    
    return {
        "lat": lat,
        "lon": lon,
        "timestamp": timestamp
    }

async def get_courier_route(chat_id: int, max_waypoints: int = 50) -> Optional[Dict[str, Any]]:
    """
    Получает маршрут курьера за последние 72 часа.
    
    Returns:
        dict с ключами: maps_url, points_count, time_range или None если недостаточно данных
    """
    db = await get_db()
    now = datetime.now(TIMEZONE)
    time_72h_ago = now - timedelta(hours=72)
    time_24h_ago = now - timedelta(hours=24)
    
    # Получаем все локации за последние 72 часа
    locations = await db.locations.find(
        {
            "chat_id": chat_id,
            "timestamp_ns": {"$gte": int(time_72h_ago.timestamp() * 1e9)}
        }
    ).sort("timestamp_ns", 1).to_list(10000)
    
    if not locations:
        return None
    
    # Проверяем последнюю локацию - она должна быть не старше 24 часов
    last_location = locations[-1]
    last_location_time = datetime.fromtimestamp(last_location.get("timestamp_ns", 0) / 1e9, tz=TIMEZONE)
    
    if last_location_time < time_24h_ago:
        recent_location = await db.locations.find_one(
            {
                "chat_id": chat_id,
                "timestamp_ns": {"$gte": int(time_24h_ago.timestamp() * 1e9)}
            },
            sort=[("timestamp_ns", -1)]
        )
        
        if recent_location:
            locations = [loc for loc in locations if loc.get("timestamp_ns") <= recent_location.get("timestamp_ns")]
            locations.append(recent_location)
    
    if len(locations) < 2:
        # Если только одна точка
        loc = locations[0]
        maps_url = f"https://maps.google.com/?q={loc['lat']},{loc['lon']}"
        return {
            "maps_url": maps_url,
            "points_count": 1,
            "time_range": {
                "start": datetime.fromtimestamp(loc.get("timestamp_ns", 0) / 1e9, tz=TIMEZONE).isoformat(),
                "end": datetime.fromtimestamp(loc.get("timestamp_ns", 0) / 1e9, tz=TIMEZONE).isoformat()
            }
        }
    
    # Формируем waypoints
    waypoints = []
    for loc in locations:
        lat = loc.get("lat")
        lon = loc.get("lon")
        if lat is not None and lon is not None:
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                waypoints.append(f"{lat},{lon}")
    
    if len(waypoints) < 2:
        loc = locations[0]
        maps_url = f"https://maps.google.com/?q={loc['lat']},{loc['lon']}"
        return {
            "maps_url": maps_url,
            "points_count": 1,
            "time_range": {
                "start": datetime.fromtimestamp(loc.get("timestamp_ns", 0) / 1e9, tz=TIMEZONE).isoformat(),
                "end": datetime.fromtimestamp(loc.get("timestamp_ns", 0) / 1e9, tz=TIMEZONE).isoformat()
            }
        }
    
    # Ограничиваем количество точек
    if len(waypoints) > max_waypoints:
        selected_waypoints = [waypoints[0]]
        step = len(waypoints) / (max_waypoints - 1)
        for i in range(1, max_waypoints - 1):
            idx = int(i * step)
            if idx < len(waypoints):
                selected_waypoints.append(waypoints[idx])
        selected_waypoints.append(waypoints[-1])
        waypoints = selected_waypoints
    
    # Создаем URL с маршрутом
    waypoints_str = "/".join(waypoints)
    maps_url = f"https://www.google.com/maps/dir/{waypoints_str}"
    
    # Сокращаем URL
    maps_url = await shorten_url(maps_url)
    
    return {
        "maps_url": maps_url,
        "points_count": len(waypoints),
        "time_range": {
            "start": datetime.fromtimestamp(locations[0].get("timestamp_ns", 0) / 1e9, tz=TIMEZONE).isoformat(),
            "end": datetime.fromtimestamp(locations[-1].get("timestamp_ns", 0) / 1e9, tz=TIMEZONE).isoformat()
        }
    }

@router.message(F.text == "/admin")
async def cmd_admin(message: Message):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[ADMIN] 🔧 Попытка доступа к админ-панели пользователем {message.from_user.id}")
    if not await is_super_admin(message.from_user.id):
        logger.warning(f"[ADMIN] ⚠️ Доступ запрещен для пользователя {message.from_user.id}")
        await message.answer("❌ Доступ запрещен")
        return
    logger.info(f"[ADMIN] ✅ Админ-панель открыта пользователем {message.from_user.id}")
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
        from datetime import datetime, timedelta
        db = await get_db()
        now = datetime.now(TIMEZONE)
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
    logger.info(f"[ADMIN] ➕ Админ {call.from_user.id} добавляет пользователя")
    
    if not await is_super_admin(call.from_user.id):
        logger.warning(f"[ADMIN] ⚠️ Доступ запрещен для пользователя {call.from_user.id}")
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_user_id)
    logger.debug(f"[ADMIN] 📊 Состояние установлено: waiting_user_id для {call.from_user.id}")
    
    await call.message.edit_text("➕ Добавление курьера", reply_markup=back_to_admin_kb())
    await call.message.answer("Выбери пользователя из контактов:", reply_markup=request_user_kb())
    await call.answer()

@router.message(F.user_shared)
async def process_add_user(message: Message, state: FSMContext, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[ADMIN] 👤 Получен user_shared от {message.from_user.id}: user_id={message.user_shared.user_id}")
    
    current_state = await state.get_state()
    logger.debug(f"[ADMIN] 📊 Текущее состояние: {current_state}")
    
    if current_state != AdminStates.waiting_user_id:
        logger.warning(f"[ADMIN] ⚠️ user_shared получен, но состояние {current_state}, игнорируем")
        return
    
    if not await is_super_admin(message.from_user.id):
        logger.warning(f"[ADMIN] ⚠️ Не-админ пытается добавить пользователя: {message.from_user.id}")
        return
    
    user_id = message.user_shared.user_id
    logger.info(f"[ADMIN] ✅ Админ {message.from_user.id} выбрал пользователя {user_id}")
    
    db = await get_db()
    logger.debug(f"[ADMIN] 🔍 Проверка существования курьера {user_id}")
    existing = await db.couriers.find_one({"tg_chat_id": user_id})
    if existing:
        logger.info(f"[ADMIN] ⚠️ Курьер {user_id} уже существует, пропускаем добавление")
        await message.answer(f"ℹ️ Курьер {user_id} уже существует")
        await state.clear()
        return
    
    try:
        logger.debug(f"[ADMIN] 🔍 Получение информации о пользователе {user_id} из Telegram")
        chat = await bot.get_chat(user_id)
        full_name = chat.full_name or f"user_{user_id}"
        username = chat.username
        logger.info(f"[ADMIN] ✅ Информация о пользователе получена: full_name={full_name}, username={username}")
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Не удалось получить информацию о пользователе {user_id}: {e}")
        full_name = f"user_{user_id}"
        username = None
    
    from db.models import Action
    await Action.log(db, message.from_user.id, "admin_add_user", details={"added_user_id": user_id, "name": full_name})
    
    # Создание курьера в Odoo - используем общий метод
    odoo_created = await _create_courier_in_odoo(full_name, str(user_id), username, False)
    
    logger.debug(f"[ADMIN] 💾 Сохранение курьера в БД: user_id={user_id}, name={full_name}")
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
    logger.info(f"[ADMIN] ✅ Админ {message.from_user.id} добавил пользователя {user_id} ({full_name}), Odoo: {'создан' if odoo_created else 'ошибка'}")
    
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

@router.callback_query(F.data == "admin:no_action")
async def cb_no_action(call: CallbackQuery):
    """Обработчик для пустых кнопок (когда нет username)"""
    await call.answer()

@router.callback_query(F.data == "admin:del_user")
async def cb_del_user(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        if not await is_super_admin(call.from_user.id):
            await call.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        db = await get_db()
        couriers = await db.couriers.find().sort("name", 1).to_list(100)
        
        if not couriers:
            await call.message.edit_text("ℹ️ Нет пользователей", reply_markup=back_to_admin_kb())
            await call.answer()
            return
        
        try:
            await call.message.edit_text(
                "➖ Удаление пользователя\n\nВыбери пользователя для удаления:",
                reply_markup=user_list_kb(couriers)
            )
        except Exception as edit_error:
            logger.warning(f"[ADMIN] ⚠️ Не удалось отредактировать сообщение, отправляем новое: {edit_error}")
            await call.message.answer(
                "➖ Удаление пользователя\n\nВыбери пользователя для удаления:",
                reply_markup=user_list_kb(couriers)
            )
        await call.answer()
    except Exception as e:
        logger.error(f"[ADMIN] ❌ Ошибка в cb_del_user: {e}", exc_info=True)
        try:
            await call.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass

@router.callback_query(F.data.startswith("admin:confirm_del:"))
async def cb_confirm_del(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        if not await is_super_admin(call.from_user.id):
            await call.answer("❌ Доступ запрещен", show_alert=True)
            return
        
        chat_id = int(call.data.split(":", 2)[2])
        db = await get_db()
        courier = await db.couriers.find_one({"tg_chat_id": chat_id})
        
        if not courier:
            await call.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        try:
            await call.message.edit_text(
                f"⚠️ Подтверди удаление\n\n"
                f"Пользователь: {courier.get('name', 'Unknown')}\n"
                f"ID: {chat_id}",
                reply_markup=confirm_delete_kb(chat_id)
            )
        except Exception as edit_error:
            logger.warning(f"[ADMIN] ⚠️ Не удалось отредактировать сообщение, отправляем новое: {edit_error}")
            await call.message.answer(
                f"⚠️ Подтверди удаление\n\n"
                f"Пользователь: {courier.get('name', 'Unknown')}\n"
                f"ID: {chat_id}",
                reply_markup=confirm_delete_kb(chat_id)
            )
        await call.answer()
    except Exception as e:
        logger.error(f"[ADMIN] ❌ Ошибка в cb_confirm_del: {e}", exc_info=True)
        try:
            await call.answer("❌ Произошла ошибка", show_alert=True)
        except:
            pass

@router.callback_query(F.data.startswith("admin:delete:"))
async def cb_delete_user(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    
    # Сразу убираем индикатор загрузки
    await call.answer()
    
    if not await is_super_admin(call.from_user.id):
        logger.warning(f"[ADMIN] ⚠️ Доступ запрещен для пользователя {call.from_user.id}")
        try:
            await call.message.answer("❌ Доступ запрещен")
        except:
            pass
        return
    
    chat_id = int(call.data.split(":", 2)[2])
    logger.info(f"[ADMIN] 🗑️ Админ {call.from_user.id} удаляет пользователя {chat_id}")
    db = await get_db()
    
    # Получаем данные курьера перед удалением для логирования
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    courier_name = courier.get("name", "Unknown") if courier else "Unknown"
    
    # Удаление курьера из Odoo
    odoo_deleted = False
    try:
        from utils.odoo import delete_courier
        logger.debug(f"[ADMIN] 🔌 Удаление курьера из Odoo для пользователя {chat_id}")
        odoo_result = await delete_courier(str(chat_id))
        if odoo_result:
            logger.info(f"[ADMIN] ✅ Курьер удален из Odoo для пользователя {chat_id}")
            odoo_deleted = True
        else:
            logger.warning(f"[ADMIN] ⚠️ Не удалось удалить курьера из Odoo для пользователя {chat_id} (возможно, не был создан)")
    except Exception as e:
        logger.error(f"[ADMIN] ❌ Ошибка удаления курьера из Odoo: {e}", exc_info=True)
    
    logger.debug(f"[ADMIN] 💾 Удаление курьера {chat_id} из БД")
    result = await db.couriers.delete_one({"tg_chat_id": chat_id})
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "admin_del_user", details={"deleted_user_id": chat_id, "name": courier_name})
    logger.debug(f"[ADMIN] 📝 Действие 'admin_del_user' залогировано")
    
    if result.deleted_count > 0:
        logger.info(f"[ADMIN] ✅ Админ {call.from_user.id} удалил пользователя {chat_id} ({courier_name}), Odoo: {'удален' if odoo_deleted else 'не найден/ошибка'}")
        odoo_status = "\n✅ Odoo: удален" if odoo_deleted else "\n⚠️ Odoo: не найден или ошибка"
        try:
            await call.message.edit_text(
                f"✅ Пользователь {chat_id} удален{odoo_status}",
                reply_markup=admin_main_kb()
            )
        except Exception as edit_error:
            logger.warning(f"[ADMIN] ⚠️ Не удалось отредактировать сообщение, отправляем новое: {edit_error}")
            try:
                await call.message.answer(
                    f"✅ Пользователь {chat_id} удален{odoo_status}",
                    reply_markup=admin_main_kb()
                )
            except:
                pass
    else:
        logger.warning(f"[ADMIN] ⚠️ Не удалось удалить пользователя {chat_id} админом {call.from_user.id}")
        try:
            await call.message.edit_text(
                "❌ Не удалось удалить пользователя",
                reply_markup=admin_main_kb()
            )
        except Exception as edit_error:
            logger.warning(f"[ADMIN] ⚠️ Не удалось отредактировать сообщение: {edit_error}")
            try:
                await call.message.answer(
                    "❌ Не удалось удалить пользователя",
                    reply_markup=admin_main_kb()
                )
            except:
                pass

@router.callback_query(F.data == "admin:sync_odoo")
async def cb_sync_odoo(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        logger.warning(f"[ADMIN] ⚠️ Доступ запрещен для пользователя {call.from_user.id}")
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    logger.info(f"[ADMIN] 🔄 Админ {call.from_user.id} запускает синхронизацию с Odoo")
    
    # Показываем сообщение о начале синхронизации
    await call.message.edit_text("🔄 Синхронизация с Odoo...\n\nПожалуйста, подождите...")
    await call.answer()
    
    db = await get_db()
    
    try:
        # Получаем всех курьеров из Odoo
        from utils.odoo import get_all_couriers_from_odoo, delete_courier
        logger.debug(f"[ADMIN] 🔍 Получение всех курьеров из Odoo...")
        odoo_couriers = await get_all_couriers_from_odoo()
        
        # Получаем всех курьеров из бота (MongoDB)
        logger.debug(f"[ADMIN] 🔍 Получение всех курьеров из бота...")
        bot_couriers = await db.couriers.find({}).to_list(length=None)
        
        # Создаем словари для быстрого поиска по courier_tg_chat_id
        odoo_couriers_dict = {}
        for courier in odoo_couriers:
            tg_id = courier.get("courier_tg_chat_id")
            if tg_id:
                odoo_couriers_dict[str(tg_id)] = courier
        
        bot_couriers_dict = {}
        for courier in bot_couriers:
            tg_id = courier.get("tg_chat_id")
            if tg_id:
                bot_couriers_dict[str(tg_id)] = courier
        
        odoo_tg_ids = set(odoo_couriers_dict.keys())
        bot_tg_ids = set(bot_couriers_dict.keys())
        
        logger.info(f"[ADMIN] 📊 Статистика: Odoo={len(odoo_tg_ids)}, Бот={len(bot_tg_ids)}")
        
        # Находим курьеров, которые есть в Odoo, но нет в боте - удаляем из Odoo
        to_delete_from_odoo = odoo_tg_ids - bot_tg_ids
        deleted_count = 0
        for tg_id in to_delete_from_odoo:
            logger.debug(f"[ADMIN] 🗑️ Удаление курьера {tg_id} из Odoo (нет в боте)")
            if await delete_courier(tg_id):
                deleted_count += 1
        
        # Находим курьеров, которые есть в боте, но нет в Odoo - добавляем в Odoo
        to_add_to_odoo = bot_tg_ids - odoo_tg_ids
        added_count = 0
        for tg_id in to_add_to_odoo:
            # Находим курьера в боте
            courier = bot_couriers_dict[tg_id]
            name = courier.get("name", f"courier_{tg_id}")
            username = courier.get("username")
            is_on_shift = courier.get("is_on_shift", False)
            logger.debug(f"[ADMIN] ➕ Добавление курьера {tg_id} ({name}) в Odoo")
            
            # Используем тот же метод создания курьера, что и при добавлении через админку
            if await _create_courier_in_odoo(name, tg_id, username, is_on_shift):
                added_count += 1
            else:
                logger.error(f"[ADMIN] ❌ Не удалось создать курьера {tg_id} ({name}) в Odoo")
        
        # Находим курьеров, которые есть и в боте, и в Odoo - удаляем и создаем заново если данные отличаются
        to_update = bot_tg_ids & odoo_tg_ids
        updated_count = 0
        for tg_id in to_update:
            bot_courier = bot_couriers_dict[tg_id]
            odoo_courier = odoo_couriers_dict[tg_id]
            
            bot_name = bot_courier.get("name", "")
            bot_username = bot_courier.get("username")
            bot_is_on_shift = bot_courier.get("is_on_shift", False)
            
            odoo_name = odoo_courier.get("name", "")
            # Поле username не существует в модели Odoo, поэтому не проверяем его
            odoo_is_online = odoo_courier.get("is_online", False)
            
            # Проверяем, нужно ли обновление (username не проверяем, т.к. его нет в Odoo)
            needs_update = (
                bot_name != odoo_name or
                bot_is_on_shift != odoo_is_online
            )
            
            if needs_update:
                logger.debug(f"[ADMIN] 🔄 Обновление курьера {tg_id}: name='{odoo_name}'->'{bot_name}', is_online={odoo_is_online}->{bot_is_on_shift}")
                # Удаляем курьера из Odoo перед созданием заново
                if await delete_courier(tg_id):
                    logger.debug(f"[ADMIN] ✅ Курьер {tg_id} удален из Odoo, создаем заново")
                    # Небольшая задержка после удаления, чтобы Odoo успел обработать транзакцию
                    import asyncio
                    await asyncio.sleep(0.5)
                    # Используем тот же метод создания курьера, что и при добавлении через админку
                    if await _create_courier_in_odoo(bot_name, tg_id, bot_username, bot_is_on_shift):
                        updated_count += 1
                        logger.debug(f"[ADMIN] ✅ Курьер {tg_id} успешно обновлен (удален и создан заново)")
                    else:
                        logger.error(f"[ADMIN] ❌ Не удалось создать курьера {tg_id} после удаления")
                else:
                    logger.warning(f"[ADMIN] ⚠️ Не удалось удалить курьера {tg_id} для обновления")
        
        # Формируем сообщение с результатами
        result_text = (
            f"✅ Синхронизация завершена\n\n"
            f"📊 Статистика:\n"
            f"• Курьеров в Odoo: {len(odoo_tg_ids)}\n"
            f"• Курьеров в боте: {len(bot_tg_ids)}\n\n"
            f"🔄 Изменения:\n"
            f"• Удалено из Odoo: {deleted_count}\n"
            f"• Добавлено в Odoo: {added_count}\n"
            f"• Обновлено в Odoo: {updated_count}\n"
        )
        
        if deleted_count == 0 and added_count == 0 and updated_count == 0:
            result_text += "\n✨ Все курьеры синхронизированы!"
        
        logger.info(f"[ADMIN] ✅ Синхронизация завершена: удалено={deleted_count}, добавлено={added_count}, обновлено={updated_count}")
        await call.message.edit_text(result_text, reply_markup=admin_main_kb())
        
    except Exception as e:
        logger.error(f"[ADMIN] ❌ Ошибка синхронизации с Odoo: {e}", exc_info=True)
        await call.message.edit_text(
            f"❌ Ошибка синхронизации с Odoo\n\n{str(e)}",
            reply_markup=admin_main_kb()
        )

@router.callback_query(F.data == "admin:on_shift")
async def cb_on_shift_couriers(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[ADMIN] 🚚 Админ {call.from_user.id} запрашивает список курьеров на смене")
    if not await is_super_admin(call.from_user.id):
        logger.warning(f"[ADMIN] ⚠️ Доступ запрещен для пользователя {call.from_user.id}")
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    db = await get_db()
    from datetime import datetime
    
    # Получаем всех курьеров на смене
    logger.debug(f"[ADMIN] 🔍 Поиск курьеров на смене")
    couriers = await db.couriers.find({"is_on_shift": True}).to_list(1000)
    logger.info(f"[ADMIN] 📊 Найдено {len(couriers)} курьеров на смене")
    
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
    now = datetime.now(TIMEZONE)
    start_today = datetime(now.year, now.month, now.day, tzinfo=TIMEZONE)
    
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
                if shift_started_at.endswith('Z'):
                    shift_dt = datetime.fromisoformat(shift_started_at.replace('Z', '+00:00'))
                else:
                    shift_dt = datetime.fromisoformat(shift_started_at)
                if shift_dt.tzinfo is None:
                    shift_dt = shift_dt.replace(tzinfo=TIMEZONE)
                elif shift_dt.tzinfo != TIMEZONE:
                    shift_dt = shift_dt.astimezone(TIMEZONE)
                months_ru = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
                month_ru = months_ru[shift_dt.month - 1]
                shift_time_text = f"{shift_dt.day} {month_ru}. {shift_dt.strftime('%H:%M')}"
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
            
            # Редактируем сообщение с правильной клавиатурой
            # Кнопка "Маршрут сегодня" теперь всегда показывается
            if idx == len(couriers) - 1:
                # Для последнего сообщения добавляем кнопку "Назад"
                await bot.edit_message_reply_markup(
                    chat_id=admin_chat_id,
                    message_id=msg_id,
                    reply_markup=courier_location_with_back_kb(chat_id)
                )
            else:
                # Для остальных сообщений кнопки "Где курьер?" и "Маршрут сегодня"
                await bot.edit_message_reply_markup(
                    chat_id=admin_chat_id,
                    message_id=msg_id,
                    reply_markup=courier_location_kb(chat_id)
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
    from datetime import datetime, timedelta
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    chat_id = int(call.data.split(":", 2)[2])
    
    try:
        db = await get_db()
        now = datetime.now(TIMEZONE)
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
            await call.answer("❌ Данных недостаточно для построения маршрута", show_alert=True)
            return
        
        # Проверяем последнюю локацию - она должна быть не старше 24 часов
        last_location = locations[-1]
        last_location_time = datetime.fromtimestamp(last_location.get("timestamp_ns", 0) / 1e9, tz=TIMEZONE)
        
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
                # Ограничиваем количество точек до 50, чтобы Google Maps мог обработать маршрут
                # Google Maps имеет ограничение на длину URL и количество waypoints
                MAX_WAYPOINTS = 50
                if len(waypoints) > MAX_WAYPOINTS:
                    # Берем первую, последнюю и равномерно распределенные промежуточные точки
                    selected_waypoints = [waypoints[0]]  # Первая точка
                    step = len(waypoints) / (MAX_WAYPOINTS - 1)
                    for i in range(1, MAX_WAYPOINTS - 1):
                        idx = int(i * step)
                        if idx < len(waypoints):
                            selected_waypoints.append(waypoints[idx])
                    selected_waypoints.append(waypoints[-1])  # Последняя точка
                    waypoints = selected_waypoints
                
                # Создаем URL с маршрутом
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
        
        now = datetime.now(TIMEZONE)
        start_today = datetime(now.year, now.month, now.day, tzinfo=TIMEZONE)
        
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
                if shift_started_at.endswith('Z'):
                    shift_dt = datetime.fromisoformat(shift_started_at.replace('Z', '+00:00'))
                else:
                    shift_dt = datetime.fromisoformat(shift_started_at)
                if shift_dt.tzinfo is None:
                    shift_dt = shift_dt.replace(tzinfo=TIMEZONE)
                elif shift_dt.tzinfo != TIMEZONE:
                    shift_dt = shift_dt.astimezone(TIMEZONE)
                months_ru = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
                month_ru = months_ru[shift_dt.month - 1]
                shift_time_text = f"{shift_dt.day} {month_ru}. {shift_dt.strftime('%H:%M')}"
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
        
        # Восстанавливаем исходное сообщение с кнопками
        # Кнопка "Маршрут сегодня" теперь всегда показывается
        await call.message.edit_text(text, reply_markup=courier_location_kb(chat_id))
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
        logger.warning(f"[ADMIN] ⚠️ Не-админ пытается отправить рассылку: {message.from_user.id}")
        return
    
    data = await state.get_data()
    group = data.get("broadcast_group", "all")
    logger.info(f"[ADMIN] 📢 Админ {message.from_user.id} начинает рассылку группе: {group}")
    
    db = await get_db()
    query = {}
    if group == "on_shift":
        query["is_on_shift"] = True
    elif group == "off_shift":
        query["is_on_shift"] = False
    
    logger.debug(f"[ADMIN] 🔍 Поиск курьеров для рассылки: query={query}")
    couriers = await db.couriers.find(query).to_list(1000)
    logger.info(f"[ADMIN] 📊 Найдено {len(couriers)} курьеров для рассылки (группа: {group})")
    
    sent = 0
    failed = 0
    
    from db.models import Action
    await Action.log(db, message.from_user.id, "admin_broadcast", details={"group": group, "text": message.text})
    logger.debug(f"[ADMIN] 📝 Действие 'admin_broadcast' залогировано")
    
    logger.debug(f"[ADMIN] 📤 Начало отправки рассылки...")
    for courier in couriers:
        try:
            await bot.send_message(courier["tg_chat_id"], f"📢 {message.text}")
            sent += 1
            if sent % 10 == 0:
                logger.debug(f"[ADMIN] 📊 Отправлено {sent}/{len(couriers)} сообщений")
        except Exception as e:
            logger.warning(f"[ADMIN] ⚠️ Ошибка отправки рассылки курьеру {courier['tg_chat_id']}: {e}")
            failed += 1
    
    logger.info(f"[ADMIN] ✅ Рассылка завершена: отправлено={sent}, ошибок={failed}")
    await message.answer(
        f"✅ Рассылка завершена\n\n"
        f"Отправлено: {sent}\n"
        f"Ошибок: {failed}",
        reply_markup=admin_main_kb()
    )
    await state.clear()

@router.callback_query(F.data == "admin:all_deliveries")
async def cb_all_deliveries(call: CallbackQuery):
    """Обработчик кнопки 'Все доставки' - показывает статистику всех заказов"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    logger.info(f"[ADMIN] 📦 Админ {call.from_user.id} запрашивает статистику всех доставок")
    
    db = await get_db()
    from datetime import datetime
    
    # Получаем текущую дату (начало и конец дня)
    now = datetime.now(TIMEZONE)
    start_today = datetime(now.year, now.month, now.day, tzinfo=TIMEZONE)
    end_today = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=TIMEZONE)
    
    # Всего заказов в ожидании (waiting)
    waiting_count = await db.couriers_deliveries.count_documents({"status": "waiting"})
    
    # Всего заказов в пути (in_transit)
    in_transit_count = await db.couriers_deliveries.count_documents({"status": "in_transit"})
    
    # Доставлено сегодня (done с 0:00 до конца текущего дня)
    # Используем updated_at или created_at для определения даты доставки
    # Обычно done заказы обновляются при завершении, используем updated_at
    delivered_today = await db.couriers_deliveries.count_documents({
        "status": "done",
        "updated_at": {
            "$gte": start_today.isoformat(),
            "$lte": end_today.isoformat()
        }
    })
    
    text = (
        f"📦 Все доставки\n\n"
        f"Всего заказов в ожидании: {waiting_count}\n"
        f"Всего заказов в пути: {in_transit_count}\n"
        f"Доставлено сегодня: {delivered_today}"
    )
    
    await call.message.edit_text(text, reply_markup=all_deliveries_kb())
    await call.answer()

@router.callback_query(F.data == "admin:view_all_orders")
async def cb_view_all_orders(call: CallbackQuery):
    """Обработчик кнопки 'Посмотреть все' - показывает список всех активных заказов"""
    await _show_all_orders_page(call, page=0)

@router.callback_query(F.data.startswith("admin:all_orders_page:"))
async def cb_all_orders_page(call: CallbackQuery):
    """Обработчик навигации по страницам всех заказов"""
    page = int(call.data.split(":")[2])
    await _show_all_orders_page(call, page)

async def _show_all_orders_page(call: CallbackQuery, page: int = 0):
    """Показывает страницу со списком всех активных заказов"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    logger.info(f"[ADMIN] 👁 Админ {call.from_user.id} запрашивает все активные заказы (страница {page})")
    
    db = await get_db()
    
    # Получаем все активные заказы (waiting и in_transit) без фильтра по курьеру
    all_orders = await db.couriers_deliveries.find({
        "status": {"$in": ["waiting", "in_transit"]}
    }).sort("priority", -1).sort("created_at", 1).to_list(1000)
    
    if not all_orders:
        await call.message.edit_text(
            "📦 Все активные заказы\n\nНет активных заказов.",
            reply_markup=all_orders_list_kb([], page=0, total_pages=1)
        )
        await call.answer()
        return
    
    # Разбиваем на чанки по 10 заказов
    ORDERS_PER_PAGE = 10
    total_pages = (len(all_orders) + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE
    page = max(0, min(page, total_pages - 1))  # Ограничиваем page в допустимых пределах
    
    start_idx = page * ORDERS_PER_PAGE
    end_idx = start_idx + ORDERS_PER_PAGE
    orders = all_orders[start_idx:end_idx]
    
    # Формируем текст со списком заказов
    text = f"📦 Все активные заказы (страница {page + 1}/{total_pages}):\n\n"
    for order in orders:
        external_id = order.get("external_id", "N/A")
        address = order.get("address", "—")
        client = order.get("client", {})
        client_tg = client.get("tg", "")
        client_username = f"@{client_tg.lstrip('@')}" if client_tg else ""
        text += f"<b>{external_id}</b> - {address}\n"
        if client_username:
            text += f"   {client_username}\n"
        text += "\n"
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=all_orders_list_kb(orders, page=page, total_pages=total_pages))
    await call.answer()

@router.callback_query(F.data.startswith("admin:active_orders:"))
async def cb_active_orders(call: CallbackQuery):
    """Обработчик кнопки 'Активные заказы' - показывает список активных заказов курьера"""
    chat_id = int(call.data.split(":", 2)[2])
    await _show_active_orders_page(call, chat_id, page=0)

@router.callback_query(F.data.startswith("admin:active_orders_page:"))
async def cb_active_orders_page(call: CallbackQuery):
    """Обработчик навигации по страницам активных заказов курьера"""
    parts = call.data.split(":")
    chat_id = int(parts[2])
    page = int(parts[3])
    await _show_active_orders_page(call, chat_id, page)

async def _show_active_orders_page(call: CallbackQuery, chat_id: int, page: int = 0):
    """Показывает страницу со списком активных заказов курьера"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    logger.info(f"[ADMIN] 📦 Админ {call.from_user.id} запрашивает активные заказы курьера {chat_id} (страница {page})")
    
    db = await get_db()
    
    # Получаем активные заказы курьера (waiting и in_transit)
    all_orders = await db.couriers_deliveries.find({
        "courier_tg_chat_id": chat_id,
        "status": {"$in": ["waiting", "in_transit"]}
    }).sort("priority", -1).sort("created_at", 1).to_list(100)
    
    if not all_orders:
        await call.message.edit_text(
            "📦 Активные заказы\n\nНет активных заказов у этого курьера.",
            reply_markup=active_orders_kb([], chat_id, page=0, total_pages=1)
        )
        await call.answer()
        return
    
    # Разбиваем на чанки по 10 заказов
    ORDERS_PER_PAGE = 10
    total_pages = (len(all_orders) + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE
    page = max(0, min(page, total_pages - 1))  # Ограничиваем page в допустимых пределах
    
    start_idx = page * ORDERS_PER_PAGE
    end_idx = start_idx + ORDERS_PER_PAGE
    orders = all_orders[start_idx:end_idx]
    
    # Формируем текст со списком заказов
    text = f"📦 Активные заказы (страница {page + 1}/{total_pages}):\n\n"
    for order in orders:
        external_id = order.get("external_id", "N/A")
        address = order.get("address", "—")
        client = order.get("client", {})
        client_tg = client.get("tg", "")
        client_username = f"@{client_tg.lstrip('@')}" if client_tg else ""
        text += f"<b>{external_id}</b> - {address}\n"
        if client_username:
            text += f"   {client_username}\n"
        text += "\n"
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=active_orders_kb(orders, chat_id, page=page, total_pages=total_pages))
    await call.answer()

@router.callback_query(F.data.startswith("admin:order_edit:"))
async def cb_order_edit(call: CallbackQuery):
    """Обработчик кнопки редактирования заказа"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    # Формат: admin:order_edit:external_id или admin:order_edit:external_id:original_courier_chat_id
    parts = call.data.split(":")
    external_id = parts[2]
    # Если есть исходный courier_chat_id, используем его, иначе берем из заказа
    original_courier_chat_id = int(parts[3]) if len(parts) > 3 else None
    
    logger.info(f"[ADMIN] ✏️ Админ {call.from_user.id} редактирует заказ {external_id}")
    
    # Проверяем заказ перед действием (для админов allow_admin=True)
    from handlers.orders import validate_order_for_action
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.from_user.id,
        allow_admin=True
    )
    
    if not is_valid:
        logger.warning(f"[ADMIN] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    db = await get_db()
    
    # Определяем, откуда открыт заказ (из общего списка или из списка курьера)
    from_all_orders = (original_courier_chat_id is None)
    
    # Если исходный courier_chat_id не передан, используем текущий из заказа для кнопок действий
    if original_courier_chat_id is None:
        original_courier_chat_id = order.get("courier_tg_chat_id")
    
    # Формируем текст заказа
    from utils.order_format import format_order_text
    text = format_order_text(order)
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=order_edit_kb(external_id, original_courier_chat_id, from_all_orders))
    await call.answer()

@router.callback_query(F.data.startswith("admin:order_complete:"))
async def cb_order_complete(call: CallbackQuery, bot: Bot):
    """Обработчик кнопки 'Заказ выполнен'"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    # Формат: admin:order_complete:external_id:original_courier_chat_id
    parts = call.data.split(":")
    external_id = parts[2]
    original_courier_chat_id = int(parts[3]) if len(parts) > 3 else None
    
    logger.info(f"[ADMIN] ✅ Админ {call.from_user.id} завершает заказ {external_id}")
    
    # Проверяем заказ перед действием (для админов allow_admin=True)
    from handlers.orders import validate_order_for_action
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.from_user.id,
        allow_admin=True
    )
    
    if not is_valid:
        logger.warning(f"[ADMIN] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    db = await get_db()
    
    # Если исходный courier_chat_id не передан, используем текущий из заказа
    if original_courier_chat_id is None:
        original_courier_chat_id = order.get("courier_tg_chat_id")
    
    # Для отправки сообщения используем текущего курьера заказа
    current_courier_chat_id = order.get("courier_tg_chat_id")
    address = order.get("address", "")
    
    # Удаляем сообщения о заказе перед закрытием
    from utils.order_messages import delete_order_messages_from_courier
    await delete_order_messages_from_courier(bot, order)
    
    # Обновляем заказ: статус done, записываем что закрыл администратор
    from db.models import utcnow_iso
    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {
            "$set": {
                "status": "done",
                "closed_by_admin_id": call.from_user.id,
                "updated_at": utcnow_iso()
            }
        }
    )
    
    # Получаем обновленный заказ для webhook
    updated_order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    # Проверка: если заказ тестовый (отрицательный external_id), не отправляем webhook
    is_test = is_test_order(external_id)
    
    # Отправка webhook только для реальных заказов (не тестовых)
    if not is_test:
        order_data = await prepare_order_data(db, updated_order)
        webhook_data = {
            **order_data,
            "timestamp": utcnow_iso()
        }
        await send_webhook("order_completed", webhook_data)
        logger.info(f"[ADMIN] 📤 Webhook 'order_completed' отправлен для заказа {external_id}")
    else:
        logger.info(f"[ADMIN] 🧪 Тестовый заказ {external_id} - webhook не отправляется")
    
    # Отправляем сообщение курьеру
    try:
        await bot.send_message(
            current_courier_chat_id,
            f"✅ Заказ {external_id}, {address} выполнен."
        )
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Не удалось отправить сообщение курьеру {current_courier_chat_id}: {e}")
    
    # Показываем попап с подтверждением
    await call.answer("✅ Заказ выполнен", show_alert=True)
    
    # Определяем, откуда был открыт заказ (из общего списка или из списка курьера)
    # Если original_courier_chat_id не был передан в callback_data, значит заказ из общего списка
    from_all_orders = (len(parts) == 3)  # admin:order_complete:external_id (без chat_id)
    
    if from_all_orders:
        # Возвращаем к общему списку всех активных заказов (первая страница)
        await _show_all_orders_page(call, page=0)
    else:
        # Возвращаем к списку заказов исходного курьера (первая страница)
        await _show_active_orders_page(call, original_courier_chat_id, page=0)

@router.callback_query(F.data.startswith("admin:order_delete:"))
async def cb_order_delete(call: CallbackQuery, bot: Bot):
    """Обработчик кнопки 'Удалить заказ'"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    # Формат: admin:order_delete:external_id:original_courier_chat_id
    parts = call.data.split(":")
    external_id = parts[2]
    original_courier_chat_id = int(parts[3]) if len(parts) > 3 else None
    
    logger.info(f"[ADMIN] 🗑️ Админ {call.from_user.id} удаляет заказ {external_id}")
    
    # Проверяем заказ перед действием (для админов allow_admin=True)
    # Для удаления проверяем что заказ существует (не валидируем статус)
    db = await get_db()
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    if not order:
        logger.warning(f"[ADMIN] ⚠️ Заказ {external_id} не найден (возможно уже удален)")
        try:
            await call.message.edit_text("Заказ не найден или уже удален")
        except:
            pass
        await call.answer("Заказ не найден или уже удален", show_alert=True)
        return
    
    # Если исходный courier_chat_id не передан, используем текущий из заказа
    if original_courier_chat_id is None:
        original_courier_chat_id = order.get("courier_tg_chat_id")
    
    # Для отправки сообщения используем текущего курьера заказа
    current_courier_chat_id = order.get("courier_tg_chat_id")
    address = order.get("address", "")
    
    # Удаляем заказ
    await db.couriers_deliveries.delete_one({"external_id": external_id})
    
    # Отправляем сообщение курьеру
    try:
        await bot.send_message(
            current_courier_chat_id,
            f"🗑 Заказ {external_id} удален\nАдрес: {address}"
        )
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Не удалось отправить сообщение курьеру {current_courier_chat_id}: {e}")
    
    # Показываем попап с подтверждением
    await call.answer("🗑 Заказ удален", show_alert=True)
    
    # Определяем, откуда был открыт заказ (из общего списка или из списка курьера)
    from_all_orders = (len(parts) == 3)  # admin:order_delete:external_id (без chat_id)
    
    if from_all_orders:
        # Возвращаем к общему списку всех активных заказов (первая страница)
        await _show_all_orders_page(call, page=0)
    else:
        # Возвращаем к списку заказов исходного курьера (первая страница)
        await _show_active_orders_page(call, original_courier_chat_id, page=0)

@router.callback_query(F.data.startswith("admin:order_assign_courier:"))
async def cb_order_assign_courier(call: CallbackQuery):
    """Обработчик кнопки 'Назначить курьера' - показывает список курьеров"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    # Формат: admin:order_assign_courier:external_id:original_courier_chat_id
    parts = call.data.split(":")
    external_id = parts[2]
    original_courier_chat_id = int(parts[3]) if len(parts) > 3 else None
    
    logger.info(f"[ADMIN] 👤 Админ {call.from_user.id} назначает курьера для заказа {external_id}")
    
    db = await get_db()
    couriers = await db.couriers.find().sort("name", 1).to_list(1000)
    
    if not couriers:
        await call.answer("❌ Нет доступных курьеров", show_alert=True)
        return
    
    # Передаем исходный courier_chat_id в клавиатуру для сохранения контекста
    await call.message.edit_text(
        f"👤 Назначить курьера для заказа {external_id}:\n\nВыберите курьера:",
        reply_markup=courier_list_kb(couriers, external_id, original_courier_chat_id)
    )
    await call.answer()

@router.callback_query(F.data.startswith("admin:assign_courier:"))
async def cb_assign_courier(call: CallbackQuery, bot: Bot):
    """Обработчик назначения курьера заказу"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    # Формат: admin:assign_courier:external_id:new_courier_chat_id:original_courier_chat_id
    parts = call.data.split(":")
    external_id = parts[2]
    new_courier_chat_id = int(parts[3])
    original_courier_chat_id = int(parts[4]) if len(parts) > 4 else None
    
    logger.info(f"[ADMIN] 👤 Админ {call.from_user.id} назначает курьера {new_courier_chat_id} для заказа {external_id}")
    
    # Проверяем заказ перед действием (для админов allow_admin=True)
    from handlers.orders import validate_order_for_action
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.from_user.id,
        allow_admin=True
    )
    
    if not is_valid:
        logger.warning(f"[ADMIN] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    db = await get_db()
    
    new_courier = await db.couriers.find_one({"tg_chat_id": new_courier_chat_id})
    if not new_courier:
        await call.answer("❌ Курьер не найден", show_alert=True)
        return
    
    old_courier_chat_id = order.get("courier_tg_chat_id")
    # Если исходный courier_chat_id не передан, используем старый из заказа
    if original_courier_chat_id is None:
        original_courier_chat_id = old_courier_chat_id
    address = order.get("address", "")
    
    # Удаляем сообщения у старого курьера перед переназначением
    if old_courier_chat_id != new_courier_chat_id:
        from utils.order_messages import delete_order_messages_from_courier
        await delete_order_messages_from_courier(bot, order)
    
    # Обновляем заказ в БД
    from db.models import utcnow_iso
    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {
            "$set": {
                "courier_tg_chat_id": new_courier_chat_id,
                "assigned_to": new_courier["_id"],
                "updated_at": utcnow_iso()
            }
        }
    )
    
    # Обновляем курьера заказа в Odoo
    try:
        from utils.odoo import update_order_courier
        await update_order_courier(external_id, str(new_courier_chat_id))
        logger.info(f"[ADMIN] ✅ Курьер заказа обновлен в Odoo")
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Не удалось обновить курьера заказа в Odoo: {e}")
    
    # Отправляем сообщение старому курьеру (если он отличается от нового)
    if old_courier_chat_id != new_courier_chat_id:
        try:
            await bot.send_message(
                old_courier_chat_id,
                f"🔄 Заказ {external_id} переназначен другому курьеру\nАдрес: {address}"
            )
        except Exception as e:
            logger.warning(f"[ADMIN] ⚠️ Не удалось отправить сообщение старому курьеру {old_courier_chat_id}: {e}")
    
    # Отправляем сообщение новому курьеру
    try:
        from utils.order_format import format_order_text
        order = await db.couriers_deliveries.find_one({"external_id": external_id})
        text = format_order_text(order)
        from keyboards.orders_kb import new_order_kb, in_transit_kb
        kb = new_order_kb(external_id) if order.get("status") == "waiting" else in_transit_kb(external_id, order)
        message = await bot.send_message(
            new_courier_chat_id,
            text,
            parse_mode="HTML",
            reply_markup=kb
        )
        # Сохраняем message_id в заказе
        from utils.order_messages import save_order_message_id
        await save_order_message_id(order, message.message_id)
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Не удалось отправить сообщение новому курьеру {new_courier_chat_id}: {e}")
    
    # Показываем попап с подтверждением
    await call.answer("✅ Курьер назначен", show_alert=True)
    
    # Определяем, откуда был открыт заказ (из общего списка или из списка курьера)
    # Если original_courier_chat_id не был передан в callback_data, значит заказ из общего списка
    from_all_orders = (len(parts) == 4)  # admin:assign_courier:external_id:new_courier_chat_id (без original_courier_chat_id)
    
    if from_all_orders:
        # Возвращаем к общему списку всех активных заказов (первая страница)
        await _show_all_orders_page(call, page=0)
    else:
        # Возвращаем к списку заказов исходного курьера (первая страница)
        await _show_active_orders_page(call, original_courier_chat_id, page=0)

@router.callback_query(F.data.startswith("admin:close_shift:"))
async def cb_close_shift(call: CallbackQuery):
    """Обработчик кнопки 'Закрыть смену курьера'"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    courier_chat_id = int(call.data.split(":")[2])
    logger.info(f"[ADMIN] 🔴 Админ {call.from_user.id} закрывает смену курьера {courier_chat_id}")
    
    db = await get_db()
    
    # Проверяем наличие активных заказов
    active_orders = await db.couriers_deliveries.find({
        "courier_tg_chat_id": courier_chat_id,
        "status": {"$in": ["waiting", "in_transit"]}
    }).to_list(100)
    
    if active_orders:
        # Если есть активные заказы - показываем список курьеров для передачи
        all_couriers = await db.couriers.find().to_list(1000)
        
        # Исключаем текущего курьера из списка
        couriers_for_transfer = [c for c in all_couriers if c.get("tg_chat_id") != courier_chat_id]
        
        # Сортируем: сначала онлайн, потом оффлайн, внутри по имени
        couriers_for_transfer.sort(key=lambda x: (
            0 if x.get("is_on_shift", False) else 1,  # Сначала онлайн (0), потом оффлайн (1)
            x.get("name", "").lower()  # Внутри по имени
        ))
        
        if not couriers_for_transfer:
            await call.answer("❌ Нет других курьеров для передачи заказов", show_alert=True)
            return
        
        text = (
            f"🔴 Закрыть смену курьера\n\n"
            f"У курьера есть активные заказы ({len(active_orders)}).\n"
            f"Выберите курьера, на которого передать заказы:"
        )
        
        await call.message.edit_text(text, reply_markup=courier_transfer_kb(couriers_for_transfer, courier_chat_id))
        await call.answer()
    else:
        # Если нет активных заказов - сразу закрываем смену
        await _close_shift_without_transfer(call, courier_chat_id)

@router.callback_query(F.data.startswith("admin:transfer_orders:"))
async def cb_transfer_orders(call: CallbackQuery, bot: Bot):
    """Обработчик передачи заказов другому курьеру при закрытии смены"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    parts = call.data.split(":")
    courier_to_close_chat_id = int(parts[2])
    new_courier_chat_id = int(parts[3])
    
    logger.info(f"[ADMIN] 🔄 Админ {call.from_user.id} передает заказы от курьера {courier_to_close_chat_id} курьеру {new_courier_chat_id}")
    
    db = await get_db()
    
    # Получаем информацию о курьерах
    old_courier = await db.couriers.find_one({"tg_chat_id": courier_to_close_chat_id})
    new_courier = await db.couriers.find_one({"tg_chat_id": new_courier_chat_id})
    
    if not old_courier or not new_courier:
        await call.answer("❌ Курьер не найден", show_alert=True)
        return
    
    # Получаем активные заказы
    active_orders = await db.couriers_deliveries.find({
        "courier_tg_chat_id": courier_to_close_chat_id,
        "status": {"$in": ["waiting", "in_transit"]}
    }).to_list(100)
    
    if not active_orders:
        await call.answer("❌ Нет активных заказов для передачи", show_alert=True)
        return
    
    # Передаем заказы новому курьеру
    from db.models import utcnow_iso
    from utils.odoo import update_order_courier
    
    transferred_count = 0
    for order in active_orders:
        external_id = order.get("external_id")
        try:
            # Удаляем сообщения у старого курьера перед передачей
            from utils.order_messages import delete_order_messages_from_courier
            await delete_order_messages_from_courier(bot, order)
            
            # Обновляем в БД
            await db.couriers_deliveries.update_one(
                {"external_id": external_id},
                {
                    "$set": {
                        "courier_tg_chat_id": new_courier_chat_id,
                        "assigned_to": new_courier["_id"],
                        "updated_at": utcnow_iso()
                    }
                }
            )
            
            # Обновляем в Odoo
            try:
                await update_order_courier(external_id, str(new_courier_chat_id))
            except Exception as e:
                logger.warning(f"[ADMIN] ⚠️ Не удалось обновить курьера заказа {external_id} в Odoo: {e}")
            
            transferred_count += 1
        except Exception as e:
            logger.error(f"[ADMIN] ❌ Ошибка передачи заказа {external_id}: {e}", exc_info=True)
    
    logger.info(f"[ADMIN] ✅ Передано {transferred_count} заказов от курьера {courier_to_close_chat_id} курьеру {new_courier_chat_id}")
    
    # Отправляем сообщение новому курьеру о переданных заказах
    try:
        from utils.order_format import format_order_text
        from keyboards.orders_kb import new_order_kb, in_transit_kb
        
        for order in active_orders:
            try:
                # Получаем актуальные данные заказа из БД
                updated_order = await db.couriers_deliveries.find_one({"external_id": order.get("external_id")})
                if not updated_order:
                    continue
                    
                text = format_order_text(updated_order)
                kb = new_order_kb(updated_order["external_id"]) if updated_order.get("status") == "waiting" else in_transit_kb(updated_order["external_id"], updated_order)
                message = await bot.send_message(
                    new_courier_chat_id,
                    text,
                    parse_mode="HTML",
                    reply_markup=kb
                )
                # Сохраняем message_id в заказе
                from utils.order_messages import save_order_message_id
                await save_order_message_id(updated_order, message.message_id)
            except Exception as e:
                logger.warning(f"[ADMIN] ⚠️ Не удалось отправить сообщение новому курьеру {new_courier_chat_id} о заказе {order.get('external_id')}: {e}")
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Ошибка отправки сообщений новому курьеру: {e}")
    
    # Показываем попап с подтверждением
    await call.answer(f"✅ Заказы переданы курьеру {new_courier.get('name', 'Unknown')}", show_alert=True)
    
    # Закрываем смену
    await _close_shift_final(call, bot, courier_to_close_chat_id)

@router.callback_query(F.data.startswith("admin:close_shift_no_transfer:"))
async def cb_close_shift_no_transfer(call: CallbackQuery, bot: Bot):
    """Обработчик закрытия смены без передачи заказов"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(call.from_user.id):
        await call.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    courier_chat_id = int(call.data.split(":")[2])
    logger.info(f"[ADMIN] 🔴 Админ {call.from_user.id} закрывает смену курьера {courier_chat_id} без передачи заказов")
    
    await _close_shift_final(call, bot, courier_chat_id)

async def _close_shift_final(call: CallbackQuery, bot: Bot, courier_chat_id: int):
    """Финальное закрытие смены курьера"""
    import logging
    logger = logging.getLogger(__name__)
    
    db = await get_db()
    redis = get_redis()
    
    courier = await db.couriers.find_one({"tg_chat_id": courier_chat_id})
    if not courier:
        await call.answer("❌ Курьер не найден", show_alert=True)
        return
    
    # Сохраняем время начала смены для подсчета заказов
    shift_started_at = courier.get("shift_started_at")
    current_shift_id = courier.get("current_shift_id")
    user_id = courier_chat_id  # Используем chat_id как user_id
    
    # Подсчет заказов за смену
    orders_count = 0
    complete_orders_count = 0
    
    if shift_started_at:
        try:
            orders_count = await db.couriers_deliveries.count_documents({
                "courier_tg_chat_id": courier_chat_id,
                "created_at": {"$gte": shift_started_at}
            })
            complete_orders_count = await db.couriers_deliveries.count_documents({
                "courier_tg_chat_id": courier_chat_id,
                "status": "done",
                "created_at": {"$gte": shift_started_at}
            })
        except Exception as e:
            logger.warning(f"[ADMIN] ⚠️ Ошибка подсчета заказов за смену: {e}", exc_info=True)
    
    # Обновляем статус курьера
    await db.couriers.update_one(
        {"_id": courier["_id"]},
        {"$set": {"is_on_shift": False}, "$unset": {"current_shift_id": "", "shift_started_at": ""}}
    )
    
    # Удаляем данные из Redis
    await redis.delete(f"courier:shift:{courier_chat_id}")
    await redis.delete(f"courier:loc:{courier_chat_id}")
    
    # Записываем в историю
    from db.models import Action, ShiftHistory
    await Action.log(db, user_id, "shift_end")
    await ShiftHistory.log(
        db,
        courier_chat_id,
        "shift_ended",
        shift_id=current_shift_id,
        total_orders=orders_count,
        complete_orders=complete_orders_count,
        shift_started_at=shift_started_at
    )
    
    # Обновление статуса в Odoo
    try:
        from utils.odoo import update_courier_status
        await update_courier_status(str(courier_chat_id), is_online=False)
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Не удалось обновить статус курьера в Odoo: {e}")
    
    # Отправляем сообщение курьеру
    try:
        await bot.send_message(
            courier_chat_id,
            "🔴 Ваша смена завершена офис-менеджером.\n\nСпасибо за работу!"
        )
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Не удалось отправить сообщение курьеру {courier_chat_id}: {e}")
    
    # Удаляем сообщение
    try:
        await call.message.delete()
    except Exception as e:
        logger.warning(f"[ADMIN] ⚠️ Не удалось удалить сообщение: {e}")
    
    logger.info(f"[ADMIN] ✅ Смена курьера {courier_chat_id} закрыта админом")

async def _close_shift_without_transfer(call: CallbackQuery, courier_chat_id: int):
    """Закрытие смены без передачи заказов (когда нет активных заказов)"""
    bot = call.message.bot
    await _close_shift_final(call, bot, courier_chat_id)
