from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from db.mongo import get_db
from db.redis_client import get_redis
from keyboards.orders_kb import new_order_kb, in_transit_kb
from keyboards.main_menu import main_menu
from utils.notifications import notify_manager
from utils.order_format import format_order_text
from utils.test_orders import is_test_order
from config import ORDER_LOCK_TTL, PHOTO_WAIT_TTL, TIMEZONE
from db.models import utcnow_iso
from datetime import datetime
from typing import Optional, Tuple

router = Router()

async def validate_order_for_action(
    external_id: str,
    user_chat_id: int,
    expected_statuses: Optional[list] = None,
    allow_admin: bool = False
) -> Tuple[bool, Optional[dict], Optional[str]]:
    """
    Проверяет заказ перед выполнением действия.
    
    Args:
        external_id: ID заказа
        user_chat_id: Chat ID пользователя, выполняющего действие
        expected_statuses: Ожидаемые статусы заказа (если None, проверяет что заказ не закрыт)
        allow_admin: Разрешить админам выполнять действия (проверка курьера игнорируется)
        
    Returns:
        Tuple[bool, Optional[dict], Optional[str]]: 
        - True если заказ валиден, False если нет
        - Объект заказа или None
        - Сообщение об ошибке или None
    """
    import logging
    logger = logging.getLogger(__name__)
    
    db = await get_db()
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    if not order:
        logger.warning(f"[ORDERS] ⚠️ Заказ {external_id} не найден (возможно удален)")
        return False, None, "Заказ не найден или удален"
    
    # Проверяем, что заказ не закрыт
    status = order.get("status")
    if status in ["done", "cancelled"]:
        logger.warning(f"[ORDERS] ⚠️ Попытка выполнить действие с закрытым заказом {external_id} (status: {status})")
        return False, order, "Заказ уже закрыт"
    
    # Проверяем ожидаемые статусы (если указаны)
    if expected_statuses and status not in expected_statuses:
        logger.warning(f"[ORDERS] ⚠️ Неверный статус заказа {external_id}: ожидался {expected_statuses}, получен {status}")
        return False, order, "Заказ в неверном статусе"
    
    # Проверяем, что заказ принадлежит текущему курьеру (если не админ)
    if not allow_admin:
        order_courier_chat_id = order.get("courier_tg_chat_id")
        # Приводим к одному типу для сравнения
        if isinstance(order_courier_chat_id, str):
            order_courier_chat_id = int(order_courier_chat_id)
        if isinstance(user_chat_id, str):
            user_chat_id = int(user_chat_id)
            
        if order_courier_chat_id != user_chat_id:
            logger.warning(f"[ORDERS] ⚠️ Попытка выполнить действие с заказом {external_id} другого курьера. Заказ: {order_courier_chat_id}, Пользователь: {user_chat_id}")
            return False, order, "Заказ назначен другому курьеру"
    
    return True, order, None

@router.message(F.text == "/orders")
async def cmd_orders(message: Message):
    import logging
    logger = logging.getLogger(__name__)
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    logger.info(f"[ORDERS] 📦 Команда /orders от пользователя {user_id} (chat_id: {chat_id})")
    
    # Проверяем, что пользователь - курьер
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        logger.warning(f"[ORDERS] ⚠️ Пользователь {user_id} не является курьером, игнорируем команду /orders")
        return
    
    try:
        await show_active_orders(chat_id, message)
    except Exception as e:
        logger.error(f"[ORDERS] ❌ Ошибка в cmd_orders для пользователя {user_id} (chat_id: {chat_id}): {e}", exc_info=True)
        await message.answer("Произошла ошибка при загрузке заказов")

@router.callback_query(F.data == "orders:list")
async def cb_my_orders(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    logger.info(f"[ORDERS] 📦 Нажата кнопка 'Мои заказы' пользователем {user_id} (chat_id: {chat_id})")
    
    try:
        await show_active_orders(chat_id, call.message)
        await call.answer()
    except Exception as e:
        logger.error(f"[ORDERS] ❌ Ошибка в cb_my_orders для пользователя {user_id} (chat_id: {chat_id}): {e}", exc_info=True)
        await call.answer("Произошла ошибка при загрузке заказов", show_alert=True)

async def show_waiting_orders(chat_id: int, message: Message):
    """Показывает только заказы со статусом waiting для курьера"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[ORDERS] 🔍 Поиск ожидающих заказов для chat_id: {chat_id}")
    
    db = await get_db()
    
    # Проверяем заказы с разными типами данных
    logger.debug(f"[ORDERS] 🔍 Проверка заказов с типом int для chat_id: {chat_id}")
    orders_as_int = await db.couriers_deliveries.count_documents({"courier_tg_chat_id": int(chat_id), "status": "waiting"})
    
    # Определяем правильный тип для запроса
    search_chat_id = int(chat_id) if orders_as_int > 0 else chat_id
    logger.debug(f"[ORDERS] 📊 Используется search_chat_id: {search_chat_id} (type: {type(search_chat_id).__name__})")
    
    # Логируем запрос к БД
    query = {
        "courier_tg_chat_id": search_chat_id,
        "status": "waiting"
    }
    logger.debug(f"[ORDERS] 🔍 MongoDB запрос для ожидающих заказов: {query}")
    
    cursor = db.couriers_deliveries.find(query).sort("priority", -1).sort("created_at", 1)
    
    found = False
    order_count = 0
    async for order in cursor:
        found = True
        order_count += 1
        logger.info(f"[ORDERS] ✅ Найден ожидающий заказ #{order_count}: external_id={order.get('external_id')}, priority={order.get('priority')}")
        
        text = format_order_text(order)
        await message.answer(text, parse_mode="HTML", reply_markup=new_order_kb(order["external_id"]))
        logger.debug(f"[ORDERS] 📤 Отправлен ожидающий заказ {order.get('external_id')} в chat_id {chat_id}")
    
    if not found:
        logger.info(f"[ORDERS] ⚠️ Ожидающих заказов не найдено для chat_id {chat_id}")
        await message.answer("Нет активных заказов.")
    else:
        logger.info(f"[ORDERS] ✅ Успешно отправлено {order_count} ожидающих заказов в chat_id {chat_id}")

async def show_active_orders(chat_id: int, message: Message):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[ORDERS] 🔍 Поиск активных заказов для chat_id: {chat_id} (type: {type(chat_id).__name__})")
    
    db = await get_db()
    
    # Проверяем, есть ли заказы с таким courier_tg_chat_id (без фильтра по статусу)
    all_orders_count = await db.couriers_deliveries.count_documents({"courier_tg_chat_id": chat_id})
    logger.debug(f"[ORDERS] 📊 Всего заказов для chat_id {chat_id}: {all_orders_count}")
    
    # Проверяем заказы с разными типами данных
    # Пробуем найти заказы как с числом, так и со строкой
    logger.debug(f"[ORDERS] 🔍 Проверка заказов с типом int для chat_id: {chat_id}")
    orders_as_int = await db.couriers_deliveries.count_documents({"courier_tg_chat_id": int(chat_id)})
    logger.debug(f"[ORDERS] 📊 Заказов с courier_tg_chat_id как int({chat_id}): {orders_as_int}")
    
    # Определяем правильный тип для запроса
    # Если заказы найдены с int, используем int, иначе используем исходный тип
    search_chat_id = int(chat_id) if orders_as_int > 0 else chat_id
    logger.debug(f"[ORDERS] 📊 Используется search_chat_id: {search_chat_id} (type: {type(search_chat_id).__name__})")
    
    # Получаем пример заказа для отладки
    sample_order = await db.couriers_deliveries.find_one({"courier_tg_chat_id": search_chat_id})
    if sample_order:
        logger.debug(f"[ORDERS] 📋 Пример заказа найден: courier_tg_chat_id={sample_order.get('courier_tg_chat_id')} (type: {type(sample_order.get('courier_tg_chat_id')).__name__}), status={sample_order.get('status')}, external_id={sample_order.get('external_id')}")
    else:
        logger.warning(f"[ORDERS] ⚠️ Заказы не найдены для chat_id {chat_id} (пробовали как {type(search_chat_id).__name__})")
    
    # Логируем запрос к БД
    query = {
        "courier_tg_chat_id": search_chat_id,
        "status": {"$in": ["waiting", "in_transit"]}
    }
    logger.debug(f"[ORDERS] 🔍 MongoDB запрос: {query}")
    
    cursor = db.couriers_deliveries.find(query).sort("priority", -1).sort("created_at", 1)
    
    found = False
    order_count = 0
    async for order in cursor:
        found = True
        order_count += 1
        logger.info(f"[ORDERS] ✅ Найден активный заказ #{order_count}: external_id={order.get('external_id')}, status={order.get('status')}, priority={order.get('priority')}")
        
        text = format_order_text(order)
        if order["status"] == "waiting":
            await message.answer(text, parse_mode="HTML", reply_markup=new_order_kb(order["external_id"]))
            logger.debug(f"[ORDERS] 📤 Отправлен ожидающий заказ {order.get('external_id')} в chat_id {chat_id}")
        elif order["status"] == "in_transit":
            await message.answer(text, parse_mode="HTML", reply_markup=in_transit_kb(order["external_id"], order))
            logger.debug(f"[ORDERS] 📤 Отправлен заказ в пути {order.get('external_id')} в chat_id {chat_id}")
    
    if not found:
        logger.warning(f"[ORDERS] ⚠️ Активных заказов не найдено для chat_id {chat_id}. Всего заказов: {all_orders_count}, Заказов как int: {orders_as_int}")
        await message.answer("Нет активных заказов.")
    else:
        logger.info(f"[ORDERS] ✅ Успешно отправлено {order_count} активных заказов в chat_id {chat_id}")

@router.callback_query(F.data.startswith("order:go:"))
async def cb_order_go(call: CallbackQuery, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"[ORDERS] 🚚 Пользователь {call.from_user.id} принимает заказ {external_id}")
    
    # Проверяем заказ перед действием
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.message.chat.id,
        expected_statuses=["waiting"]
    )
    
    if not is_valid:
        logger.warning(f"[ORDERS] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    db = await get_db()
    redis = get_redis()

    # lock to avoid double accept
    lock_key = f"order:lock:{external_id}"
    logger.debug(f"[ORDERS] 🔒 Установка блокировки для заказа {external_id}")
    ok = await redis.set(lock_key, "1", ex=ORDER_LOCK_TTL, nx=True)
    if not ok:
        logger.warning(f"[ORDERS] ⚠️ Заказ {external_id} уже обрабатывается")
        await call.answer("Кто-то уже обрабатывает этот заказ", show_alert=True)
        return

    logger.debug(f"[ORDERS] 💾 Обновление статуса заказа {external_id} на 'in_transit'")
    
    # Обновляем статус заказа на "in_transit" без изменения payment_status
    # Для тестовых заказов оплата будет установлена только при проверке оплаты
    await db.couriers_deliveries.update_one({"_id": order["_id"]}, {"$set": {"status": "in_transit", "updated_at": utcnow_iso()}})
    
    order = await db.couriers_deliveries.find_one({"_id": order["_id"]})
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_accepted", order_id=external_id)
    logger.info(f"[ORDERS] ✅ Пользователь {call.from_user.id} принял заказ {external_id}")
    
    # Проверка для webhook (тестовые заказы не отправляют webhook)
    is_test = is_test_order(external_id)
    
    # Отправка webhook только для реальных заказов (не тестовых)
    if not is_test:
        from utils.webhooks import send_webhook, prepare_order_data
        order_data = await prepare_order_data(db, order)
        webhook_data = {
            **order_data,
            "timestamp": utcnow_iso()
        }
        await send_webhook("order_accepted", webhook_data)
    else:
        logger.info(f"[ORDERS] 🧪 Тестовый заказ {external_id} - webhook не отправляется")
    
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
    """
    Обработчик кнопки "💰 Принять оплату" для заказов с оплатой наличными.
    
    ПРАВИЛО ИСПОЛЬЗОВАНИЯ:
    =====================
    
    Эта функция вызывается ТОЛЬКО для заказов с is_cash_payment=True и payment_status="NOT_PAID".
    Кнопка "💰 Принять оплату" показывается в клавиатуре in_transit_kb() только для таких заказов.
    
    ЛОГИКА РАБОТЫ:
    ==============
    
    1. Курьер получает деньги от клиента физически
    2. Курьер нажимает "💰 Принять оплату"
    3. Бот устанавливает флаг ожидания фото оплаты в Redis
    4. Бот просит курьера отфотографировать купюры
    5. Курьер отправляет фото купюр (может отправить несколько фото)
    6. Фото сохраняются в массиве pay_photo заказа
    7. После отправки фото показывается кнопка "✅ Завершить заказ"
    8. При нажатии "✅ Завершить заказ" заказ завершается с payment_status="PAID"
    
    ВАЖНО:
    - Для наличных заказов НЕ проверяется статус в Odoo (там всегда будет NOT_PAID)
    - Оплата подтверждается только после получения фото купюр от курьера
    - Менеджер не может поставить "оплачено" для наличных заказов до встречи курьера с клиентом
    """
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"[ORDERS] 💰 Пользователь {call.from_user.id} принимает оплату за заказ {external_id}")
    
    # Проверяем заказ перед действием
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.message.chat.id,
        expected_statuses=["in_transit"]
    )
    
    if not is_valid:
        logger.warning(f"[ORDERS] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    redis = get_redis()
    # Устанавливаем флаг ожидания фотографий оплаты в Redis
    # Этот флаг используется в handlers/photo.py для определения, что отправленное фото - это фото оплаты
    logger.debug(f"[ORDERS] ⏳ Установка флага ожидания фото оплаты для chat_id {call.message.chat.id}")
    await redis.setex(f"courier:payment_photo_wait:{call.message.chat.id}", PHOTO_WAIT_TTL, external_id)
    
    db = await get_db()
    from db.models import Action
    await Action.log(db, call.from_user.id, "payment_accepted", order_id=external_id)
    logger.debug(f"[ORDERS] 📝 Действие 'payment_accepted' залогировано для заказа {external_id}")
    
    # Просим курьера отфотографировать купюры
    # После отправки фото в handlers/photo.py будет обработано и сохранено в pay_photo массиве заказа
    await call.message.answer("💰 Отфотографируйте купюры и отправьте фото в бот")
    await call.answer()

@router.callback_query(F.data.startswith("order:finish_after_payment:"))
async def cb_order_finish_after_payment(call: CallbackQuery, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"[ORDERS] ✅ Пользователь {call.from_user.id} завершает заказ {external_id} после оплаты")
    
    # Проверяем заказ перед действием
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.message.chat.id,
        expected_statuses=["in_transit"]
    )
    
    if not is_valid:
        logger.warning(f"[ORDERS] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    db = await get_db()
    redis = get_redis()
    
    # Проверка: если заказ тестовый (отрицательный external_id), автоматически устанавливаем оплату "PAID"
    is_test = is_test_order(external_id)
    if is_test:
        logger.info(f"[ORDERS] 🧪 Тестовый заказ {external_id} - автоматически устанавливаем оплату PAID")
    
    # Обновляем статус оплаты и статус заказа
    logger.debug(f"[ORDERS] 💾 Обновление статуса заказа {external_id} на 'done' с оплатой 'PAID'")
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
    logger.debug(f"[ORDERS] 🗑️ Удаление флага ожидания фото оплаты для chat_id {call.message.chat.id}")
    await redis.delete(f"courier:payment_photo_wait:{call.message.chat.id}")
    
    # Получаем обновленный заказ для webhook
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_completed", order_id=external_id, details={"after_payment": True})
    logger.info(f"[ORDERS] ✅ Пользователь {call.from_user.id} завершил заказ {external_id} после оплаты")
    
    # Отправка webhook только для реальных заказов (не тестовых)
    if not is_test:
        from utils.webhooks import send_webhook, prepare_order_data
        order_data = await prepare_order_data(db, order)
        webhook_data = {
            **order_data,
            "timestamp": utcnow_iso()
        }
        await send_webhook("order_completed", webhook_data)
    else:
        logger.info(f"[ORDERS] 🧪 Тестовый заказ {external_id} - webhook не отправляется")
    
    await call.message.answer("✅ Заказ выполнен. Оплата принята.")
    await call.answer()
    
    # Уведомление менеджера только для реальных заказов (не тестовых)
    if not is_test:
        courier = await db.couriers.find_one({"tg_chat_id": call.message.chat.id})
        if courier:
            await notify_manager(bot, courier, f"📦 Курьер {courier['name']} завершил заказ {external_id} (оплата наличными)")
    else:
        logger.info(f"[ORDERS] 🧪 Тестовый заказ {external_id} - уведомление менеджеру не отправляется")
    
    # Показываем список активных заказов (waiting и in_transit)
    await show_active_orders(call.message.chat.id, call.message)

@router.callback_query(F.data.startswith("order:check_payment:"))
async def cb_order_check_payment(call: CallbackQuery, bot: Bot):
    import logging
    import json
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"[ORDERS] 🔍 Пользователь {call.from_user.id} проверяет оплату заказа {external_id}")
    
    # Проверяем заказ перед действием
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.message.chat.id,
        expected_statuses=["in_transit"]
    )
    
    if not is_valid:
        logger.warning(f"[ORDERS] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    db = await get_db()
    
    # Проверка: если заказ тестовый (отрицательный external_id), автоматически устанавливаем оплату "PAID"
    is_test = is_test_order(external_id)
    if is_test:
        logger.info(f"[ORDERS] 🧪 Тестовый заказ {external_id} - автоматически устанавливаем оплату PAID, пропускаем проверку в Odoo")
        # Для тестовых заказов автоматически устанавливаем оплату "PAID" без обращения к Odoo
        await db.couriers_deliveries.update_one(
            {"external_id": external_id},
            {
                "$set": {
                    "payment_status": "PAID",
                    "updated_at": utcnow_iso()
                }
            }
        )
        order = await db.couriers_deliveries.find_one({"external_id": external_id})
        text = format_order_text(order)
        from keyboards.orders_kb import in_transit_kb
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=in_transit_kb(external_id, order))
        await call.message.answer("✅ Оплата подтверждена (тестовый заказ)")
        await call.answer()
        return
    
    # ПРОВЕРКА: для заказов с наличными (is_cash_payment=True) не проверяем в Odoo
    # 
    # ВАЖНО: Эта проверка является защитной мерой на случай, если курьер каким-то образом
    # попытается вызвать проверку оплаты для наличного заказа (например, через прямой callback).
    # 
    # В нормальном сценарии кнопка "🔍 Проверь оплату" НЕ должна показываться для наличных заказов,
    # так как в функции in_transit_kb() для наличных заказов с NOT_PAID показывается кнопка
    # "💰 Принять оплату" вместо "🔍 Проверь оплату".
    # 
    # ЛОГИКА: Менеджер не может поставить "оплачено" для наличных заказов в Odoo до встречи
    # курьера с клиентом, так как оплата происходит физически при передаче денег.
    # Поэтому проверка статуса в Odoo для наличных заказов бессмысленна - там всегда будет NOT_PAID.
    # 
    # Для наличных заказов курьер должен:
    # 1. Получить деньги от клиента
    # 2. Нажать "💰 Принять оплату"
    # 3. Сфотографировать купюры
    # 4. Завершить заказ
    is_cash = order.get("is_cash_payment", False)
    if is_cash:
        logger.warning(f"[ORDERS] 💵 Заказ {external_id} с оплатой наличными - попытка проверить оплату в Odoo (не должно происходить)")
        await call.message.answer(
            "💵 Заказ с оплатой наличными.\n\n"
            "Для принятия оплаты используйте кнопку \"💰 Принять оплату\" после получения денег от клиента."
        )
        await call.answer()
        return
    
    # Показываем, что идет проверка
    await call.answer("Проверяю статус оплаты...", show_alert=False)
    
    # Получаем полный объект лида из Odoo
    # external_id должен быть ID лида в Odoo
    try:
        lead_id = int(external_id)
    except ValueError:
        logger.error(f"[ORDERS] ⚠️ external_id {external_id} не является числом, не могу запросить статус из Odoo")
        await call.message.answer("❌ Не удалось проверить оплату: неверный формат ID заказа")
        return
    
    from utils.odoo import get_lead
    lead_data = await get_lead(lead_id)
    
    if lead_data is None:
        logger.warning(f"[ORDERS] ⚠️ Не удалось получить объект лида из Odoo для lead_id {lead_id}")
        await call.message.answer("❌ Не удалось проверить оплату. Попробуйте позже.")
        return
    
    # Логируем все тело полученного объекта для отладки (DEBUG уровень)
    logger.debug(f"[ORDERS] 📋 Полный объект лида из Odoo (lead_id={lead_id}):")
    logger.debug(f"[ORDERS] 📋 Тело объекта: {json.dumps(lead_data, indent=2, ensure_ascii=False, default=str)}")
    
    # Получаем текущий статус оплаты из объекта лида
    odoo_payment_status = lead_data.get("payment_status")
    
    if odoo_payment_status is None:
        logger.warning(f"[ORDERS] ⚠️ Поле payment_status не найдено в объекте лида {lead_id}")
        await call.message.answer("❌ Не удалось определить статус оплаты.")
        return
    
    # Сохраняем старый статус для логирования
    old_payment_status = order.get("payment_status")
    
    # Маппинг статуса из Odoo в наш формат и русские названия
    PAYMENT_STATUS_MAPPING = {
        'paid': ('PAID', 'Оплачен'),
        'not_paid': ('NOT_PAID', 'Нет оплаты'),
        'refund': ('REFUND', 'Возврат средств')
    }
    
    # Получаем наш формат статуса и русское название
    status_info = PAYMENT_STATUS_MAPPING.get(odoo_payment_status, ('NOT_PAID', 'Неизвестно'))
    new_payment_status, status_name_ru = status_info
    
    # При проверке статуса НЕ обновляем статус в Odoo - только читаем
    # Обновление статуса происходит только когда курьер принимает оплату наличными
    
    # Если оплата не оплачена, отправляем сообщение в чаттер лида (только для реальных заказов)
    # Проверка: для тестовых заказов не отправляем сообщения в Odoo
    if odoo_payment_status == 'not_paid' and not is_test_order(external_id):
        # Получаем информацию о курьере из базы данных
        courier = await db.couriers.find_one({"tg_chat_id": call.message.chat.id})
        if courier:
            courier_name = courier.get("name", "Курьер")
            courier_username = courier.get("username")
            
            # Формируем текст сообщения
            username_part = f"(@{courier_username})" if courier_username else ""
            message_text = f"Курьер {courier_name}{username_part} просит проверить и подтвердить оплату заказа."
            
            # Отправляем сообщение в чаттер лида от имени пользователя API ключа
            from utils.odoo import send_message_to_lead_chatter
            logger.info(f"[ORDERS] 💬 Отправка сообщения в чаттер лида {lead_id} о необходимости проверки оплаты")
            chatter_result = await send_message_to_lead_chatter(lead_id, message_text)
            if chatter_result:
                logger.info(f"[ORDERS] ✅ Сообщение успешно отправлено в чаттер лида {lead_id}")
            else:
                logger.warning(f"[ORDERS] ⚠️ Не удалось отправить сообщение в чаттер лида {lead_id}")
        else:
            logger.warning(f"[ORDERS] ⚠️ Курьер не найден в базе данных для chat_id {call.message.chat.id}")
    elif odoo_payment_status == 'not_paid' and is_test_order(external_id):
        logger.info(f"[ORDERS] 🧪 Тестовый заказ {external_id} - сообщение в чаттер Odoo не отправляется")
    else:
        logger.debug(f"[ORDERS] 💰 Оплата есть (status: {odoo_payment_status}), сообщение в чаттер не отправляется")
    
    # Обновляем статус оплаты в базе данных
    logger.debug(f"[ORDERS] 💾 Обновление статуса оплаты заказа {external_id} с '{old_payment_status}' на '{new_payment_status}'")
    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {
            "$set": {
                "payment_status": new_payment_status,
                "updated_at": utcnow_iso()
            }
        }
    )
    
    # Получаем обновленный заказ
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    # Логируем действие
    from db.models import Action
    await Action.log(db, call.from_user.id, "payment_checked", order_id=external_id, details={
        "old_status": old_payment_status,
        "new_status": new_payment_status,
        "odoo_status": odoo_payment_status,
        "odoo_lead_id": lead_id
    })
    
    # Обновляем сообщение с заказом
    text = format_order_text(order)
    from keyboards.orders_kb import in_transit_kb
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=in_transit_kb(external_id, order))
    
    # Показываем результат проверки
    status_text = {
        'PAID': '✅ Оплата подтверждена',
        'NOT_PAID': '❌ Заказ не оплачен',
        'REFUND': '🔄 Отмена заказа'
    }
    await call.message.answer(f"🔍 {status_text.get(new_payment_status, 'Статус обновлен')}")
    logger.info(f"[ORDERS] ✅ Статус оплаты проверен для заказа {external_id}: {new_payment_status}")

@router.callback_query(F.data.startswith("order:done:"))
async def cb_order_done(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"[ORDERS] ✅ Пользователь {call.from_user.id} завершает заказ {external_id}")
    
    # Проверяем заказ перед действием
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.message.chat.id,
        expected_statuses=["in_transit"]
    )
    
    if not is_valid:
        logger.warning(f"[ORDERS] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    db = await get_db()
    
    # Проверка: тестовые заказы должны пройти проверку оплаты перед завершением
    is_test = is_test_order(external_id)
    
    # Если статус оплаты "не оплачен", не позволяем завершить заказ
    if order.get("payment_status") == "NOT_PAID":
        if is_test:
            logger.warning(f"[ORDERS] ⚠️ Тестовый заказ {external_id} - оплата не подтверждена, нужно проверить оплату")
            await call.answer("Сначала проверьте оплату (тестовый заказ)", show_alert=True)
        else:
            logger.warning(f"[ORDERS] ⚠️ Попытка завершить заказ {external_id} без оплаты")
            await call.answer("Сначала проверьте оплату", show_alert=True)
        return
    
    redis = get_redis()
    logger.debug(f"[ORDERS] ⏳ Установка флага ожидания фото для chat_id {call.message.chat.id}")
    await redis.setex(f"courier:photo_wait:{call.message.chat.id}", PHOTO_WAIT_TTL, external_id)
    
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_completed", order_id=external_id)
    logger.debug(f"[ORDERS] 📝 Действие 'order_completed' залогировано для заказа {external_id}")
    
    await call.message.answer("📸 Пришли фото подтверждение (чек или доставка)")
    await call.answer()

@router.callback_query(F.data.startswith("order:problem:"))
async def cb_order_problem(call: CallbackQuery):
    import logging
    logger = logging.getLogger(__name__)
    external_id = call.data.split(":", 2)[2]
    logger.info(f"[ORDERS] ⚠️ Пользователь {call.from_user.id} сообщил о проблеме с заказом {external_id}")
    
    # Проверяем заказ перед действием
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        call.message.chat.id,
        expected_statuses=["waiting", "in_transit"]
    )
    
    if not is_valid:
        logger.warning(f"[ORDERS] ⚠️ Действие отклонено для заказа {external_id}: {error_msg}")
        try:
            await call.message.edit_text(error_msg or "Действие невозможно")
        except:
            pass
        await call.answer(error_msg or "Действие невозможно", show_alert=True)
        return
    
    redis = get_redis()
    logger.debug(f"[ORDERS] ⏳ Установка флага ожидания описания проблемы для chat_id {call.message.chat.id}")
    await redis.setex(f"courier:problem_wait:{call.message.chat.id}", PHOTO_WAIT_TTL, external_id)
    
    db = await get_db()
    from db.models import Action
    await Action.log(db, call.from_user.id, "order_problem", order_id=external_id)
    logger.debug(f"[ORDERS] 📝 Действие 'order_problem' залогировано для заказа {external_id}")
    
    await call.message.answer(f"⚠ Опиши коротко проблему по заказу {external_id}, чтобы менеджер помог")
    await call.answer()

@router.message(F.text == "/history_today")
async def cmd_history_today(message: Message):
    db = await get_db()
    
    # Проверяем, что пользователь - курьер
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    if not courier:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"[ORDERS] ⚠️ Пользователь {message.from_user.id} не является курьером, игнорируем команду /history_today")
        return
    
    now = datetime.now(TIMEZONE)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    
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
    # Проверяем, что пользователь - курьер
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    if not courier:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"[ORDERS] ⚠️ Пользователь {message.from_user.id} не является курьером, игнорируем команду /history_all")
        return
    
    await show_history_page(message, 0)

@router.callback_query(F.data.startswith("history:page:"))
async def cb_history_page(call: CallbackQuery):
    page = int(call.data.split(":")[2])
    await show_history_page(call.message, page)
    await call.answer()

async def show_history_page(message: Message, page: int):
    db = await get_db()
    now = datetime.now(TIMEZONE)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    
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