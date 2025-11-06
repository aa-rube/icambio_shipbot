from aiogram import Router, F, Bot
from aiogram.types import Message
from db.redis_client import get_redis
from db.mongo import get_db
from utils.notifications import notify_manager
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
    external_id = await redis.get(f"courier:photo_wait:{chat_id}")
    if not external_id:
        logger.warning(f"User {message.from_user.id} sent photo without order context")
        await message.answer("Фото не ожидается. Сначала нажми «Заказ выполнен».")
        return

    photo = message.photo[-1]  # largest size
    file_id = photo.file_id

    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {
            "$set": {"status": "done", "updated_at": utcnow_iso()},
            "$push": {"photos": {"file_id": file_id, "uploaded_at": utcnow_iso()}}
        }
    )
    await redis.delete(f"courier:photo_wait:{chat_id}")

    # Получаем обновленный заказ для webhook
    order = await db.couriers_deliveries.find_one({"external_id": external_id})

    from db.models import Action
    await Action.log(db, message.from_user.id, "photo_sent", order_id=external_id, details={"file_id": file_id})
    logger.info(f"User {message.from_user.id} completed order {external_id} with photo")

    # Отправка webhook
    from utils.webhooks import send_webhook, prepare_order_data
    order_data = await prepare_order_data(db, order)
    webhook_data = {
        **order_data,
        "timestamp": utcnow_iso()
    }
    await send_webhook("order_completed", webhook_data)

    await message.answer("✅ Заказ выполнен. Фото сохранено.")

    # notify manager
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if courier:
        await notify_manager(bot, courier, f"📦 Курьер {courier['name']} завершил заказ {external_id}")
