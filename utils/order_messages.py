"""
Утилита для управления сообщениями о заказах в чате курьера.

Функции для сохранения и удаления message_id сообщений с заказами,
отправленных курьеру в Telegram.
"""
import logging
from typing import Dict, Any
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from db.mongo import get_db

logger = logging.getLogger(__name__)


async def save_order_message_id(order: Dict[str, Any], message_id: int) -> None:
    """
    Сохраняет message_id сообщения в массив courier_message_ids заказа.
    
    Использует $addToSet для избежания дубликатов.
    
    Args:
        order: Словарь с данными заказа (должен содержать external_id)
        message_id: ID сообщения из Telegram
    """
    if not order or not order.get("external_id"):
        logger.warning(f"[ORDER_MESSAGES] ⚠️ Не удалось сохранить message_id {message_id}: заказ не найден или нет external_id")
        return
    
    external_id = order.get("external_id")
    db = await get_db()
    
    try:
        await db.couriers_deliveries.update_one(
            {"external_id": external_id},
            {"$addToSet": {"courier_message_ids": message_id}}
        )
        logger.debug(f"[ORDER_MESSAGES] ✅ Сохранен message_id {message_id} для заказа {external_id}")
    except Exception as e:
        logger.error(f"[ORDER_MESSAGES] ❌ Ошибка сохранения message_id {message_id} для заказа {external_id}: {e}", exc_info=True)


async def delete_order_messages_from_courier(bot: Bot, order: Dict[str, Any]) -> None:
    """
    Удаляет все сообщения о заказе из чата курьера.
    
    Получает courier_message_ids из заказа, удаляет все сообщения через bot.delete_message(),
    обрабатывает ошибки (сообщение уже удалено, не найдено и т.д.),
    и после успешного удаления каждого сообщения удаляет его message_id из массива в БД.
    
    Args:
        bot: Экземпляр бота для удаления сообщений
        order: Словарь с данными заказа (должен содержать external_id и courier_tg_chat_id)
    """
    if not order or not order.get("external_id"):
        logger.warning(f"[ORDER_MESSAGES] ⚠️ Не удалось удалить сообщения: заказ не найден или нет external_id")
        return
    
    external_id = order.get("external_id")
    courier_chat_id = order.get("courier_tg_chat_id")
    
    if not courier_chat_id:
        logger.warning(f"[ORDER_MESSAGES] ⚠️ Не удалось удалить сообщения для заказа {external_id}: нет courier_tg_chat_id")
        return
    
    # Получаем актуальные данные заказа из БД
    db = await get_db()
    current_order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    if not current_order:
        logger.warning(f"[ORDER_MESSAGES] ⚠️ Заказ {external_id} не найден в БД")
        return
    
    # Проверяем, что заказ не закрыт или удален (защита от повторного удаления)
    status = current_order.get("status")
    if status in ["done", "cancelled"]:
        logger.debug(f"[ORDER_MESSAGES] ⚠️ Заказ {external_id} уже закрыт (status: {status}), пропускаем удаление сообщений")
        # Но все равно удаляем message_id из массива, если они есть
        if current_order.get("courier_message_ids"):
            await db.couriers_deliveries.update_one(
                {"external_id": external_id},
                {"$set": {"courier_message_ids": []}}
            )
        return
    
    message_ids = current_order.get("courier_message_ids", [])
    
    if not message_ids:
        logger.debug(f"[ORDER_MESSAGES] ℹ️ Нет сообщений для удаления для заказа {external_id}")
        return
    
    logger.info(f"[ORDER_MESSAGES] 🗑️ Удаление {len(message_ids)} сообщений для заказа {external_id} из чата курьера {courier_chat_id}")
    
    # Удаляем сообщения параллельно
    import asyncio
    
    async def delete_single_message(msg_id: int) -> bool:
        """Удаляет одно сообщение и возвращает True при успехе"""
        try:
            await bot.delete_message(chat_id=courier_chat_id, message_id=msg_id)
            logger.debug(f"[ORDER_MESSAGES] ✅ Удалено сообщение {msg_id} для заказа {external_id}")
            return True
        except TelegramBadRequest as e:
            # Игнорируем ошибки "message not found", "message already deleted"
            error_message = str(e).lower()
            if "message not found" in error_message or "message to delete not found" in error_message:
                logger.debug(f"[ORDER_MESSAGES] ℹ️ Сообщение {msg_id} уже удалено или не найдено для заказа {external_id}")
            else:
                logger.warning(f"[ORDER_MESSAGES] ⚠️ Ошибка удаления сообщения {msg_id} для заказа {external_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"[ORDER_MESSAGES] ❌ Неожиданная ошибка при удалении сообщения {msg_id} для заказа {external_id}: {e}", exc_info=True)
            return False
    
    # Удаляем сообщения параллельно
    results = await asyncio.gather(*[delete_single_message(msg_id) for msg_id in message_ids], return_exceptions=True)
    
    # Определяем, какие message_id нужно удалить из БД (те, что успешно удалены или уже не существуют)
    # Удаляем все message_id из массива, так как мы уже попытались их удалить
    # (независимо от результата, чтобы не накапливать несуществующие ID)
    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {"$set": {"courier_message_ids": []}}
    )
    
    successful_deletes = sum(1 for r in results if r is True)
    logger.info(f"[ORDER_MESSAGES] ✅ Удалено {successful_deletes} из {len(message_ids)} сообщений для заказа {external_id}")

