from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from db.redis_client import get_redis
from db.mongo import get_db
from utils.notifications import notify_manager
from utils.test_orders import is_test_order
from db.models import utcnow_iso

router = Router()

@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"User {message.from_user.id} sent photo")
    
    redis = get_redis()
    db = await get_db()
    chat_id = message.chat.id
    
    # Проверяем, ожидается ли фото оплаты
    external_id = await redis.get(f"courier:payment_photo_wait:{chat_id}")
    if external_id:
        # Проверка: если заказ тестовый (отрицательный external_id), автоматически устанавливаем оплату "PAID"
        is_test = is_test_order(external_id)
        if is_test:
            logger.info(f"[PHOTO] 🧪 Тестовый заказ {external_id} - автоматически устанавливаем оплату PAID")
        
        # Обработка фотографии оплаты
        photo = message.photo[-1]  # largest size
        file_id = photo.file_id

        await db.couriers_deliveries.update_one(
            {"external_id": external_id},
            {
                "$set": {"updated_at": utcnow_iso()},
                "$push": {"pay_photo": {"file_id": file_id, "uploaded_at": utcnow_iso()}}
            }
        )

        from db.models import Action
        await Action.log(db, message.from_user.id, "payment_photo_sent", order_id=external_id, details={"file_id": file_id})
        logger.info(f"User {message.from_user.id} sent payment photo for order {external_id}")

        # Показываем сообщение с возможностью отправить еще фото или завершить заказ
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить заказ", callback_data=f"order:finish_after_payment:{external_id}")]
        ])
        await message.answer("✅ Фото оплаты сохранено.\n\nВы можете отправить еще фото или завершить заказ.", reply_markup=kb)
        return
    
    # Проверяем, ожидается ли фото подтверждения выполнения
    external_id = await redis.get(f"courier:photo_wait:{chat_id}")
    if not external_id:
        logger.warning(f"User {message.from_user.id} sent photo without order context")
        await message.answer("Фото не ожидается. Сначала нажми «Заказ выполнен».")
        return

    # Получаем заказ ДО завершения, чтобы проверить условия
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    if not order:
        logger.warning(f"[PHOTO] ⚠️ Заказ {external_id} не найден")
        await message.answer("Заказ не найден")
        await redis.delete(f"courier:photo_wait:{chat_id}")
        return

    # Фото для закрытия заказа требуется ТОЛЬКО для наличных заказов без client_ip
    is_cash_payment = order.get("is_cash_payment", False)
    has_client_ip = bool(order.get("client_ip"))
    
    if not (is_cash_payment and not has_client_ip):
        logger.warning(f"[PHOTO] ⚠️ Фото не требуется для закрытия заказа {external_id} (is_cash_payment={is_cash_payment}, has_client_ip={has_client_ip})")
        await message.answer("❌ Фото не требуется для закрытия этого заказа. Заказ должен быть закрыт автоматически.")
        await redis.delete(f"courier:photo_wait:{chat_id}")
        return

    # Проверяем статус оплаты перед завершением заказа
    # Исключение: заказы с client_ip могут быть завершены без проверки оплаты
    payment_status = order.get("payment_status")
    
    if payment_status == "NOT_PAID" and not has_client_ip:
        logger.warning(f"[PHOTO] ⚠️ Попытка завершить заказ {external_id} без оплаты")
        await message.answer("❌ Заказ не оплачен. Свяжитесь с менеджером для уточнения.")
        await redis.delete(f"courier:photo_wait:{chat_id}")
        return

    photo = message.photo[-1]  # largest size
    file_id = photo.file_id

    # Для наличных заказов без client_ip устанавливаем статус оплаты в PAID при закрытии
    update_data = {
        "$set": {"status": "done", "updated_at": utcnow_iso()},
        "$push": {"photos": {"file_id": file_id, "uploaded_at": utcnow_iso()}}
    }
    
    # Если это наличный заказ без client_ip, устанавливаем payment_status в PAID
    if is_cash_payment and not has_client_ip:
        update_data["$set"]["payment_status"] = "PAID"
        logger.debug(f"[PHOTO] 💰 Установка payment_status=PAID для наличного заказа {external_id}")

    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        update_data
    )
    await redis.delete(f"courier:photo_wait:{chat_id}")

    # Получаем обновленный заказ для webhook
    order = await db.couriers_deliveries.find_one({"external_id": external_id})

    from db.models import Action
    await Action.log(db, message.from_user.id, "photo_sent", order_id=external_id, details={"file_id": file_id})
    logger.info(f"User {message.from_user.id} completed order {external_id} with photo")

    # Проверка: если заказ тестовый (отрицательный external_id), не отправляем webhook и уведомления
    is_test = is_test_order(external_id)
    
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
        logger.info(f"[PHOTO] 🧪 Тестовый заказ {external_id} - webhook не отправляется")

    await message.answer("✅ Заказ выполнен. Фото сохранено.")

    # Уведомление менеджера только для реальных заказов (не тестовых)
    if not is_test:
        courier = await db.couriers.find_one({"tg_chat_id": chat_id})
        if courier:
            await notify_manager(bot, courier, f"📦 Курьер {courier['name']} завершил заказ {external_id}")
    else:
        logger.info(f"[PHOTO] 🧪 Тестовый заказ {external_id} - уведомление менеджеру не отправляется")
    
    # Показываем список активных заказов (waiting и in_transit)
    from handlers.orders import show_active_orders
    await show_active_orders(chat_id, message)
