from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from db.redis_client import get_redis
from db.mongo import get_db
from utils.notifications import notify_manager
from utils.test_orders import is_test_order
from db.models import utcnow_iso, get_status_history_update

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

    # Фото доставки больше не требуется для завершения заказов без client_ip
    # Оплата устанавливается при клике "Завершить заказ" после принятия оплаты
    # Этот блок кода оставлен для обратной совместимости, но не должен выполняться
    # в нормальном флоу, так как мы убрали запрос фото доставки
    logger.warning(f"[PHOTO] ⚠️ Получено фото доставки для заказа {external_id}, но фото больше не требуется для завершения заказов")
    await message.answer("❌ Фото доставки больше не требуется. Используйте кнопку 'Завершить заказ' для завершения заказа.")
    await redis.delete(f"courier:photo_wait:{chat_id}")
    return
