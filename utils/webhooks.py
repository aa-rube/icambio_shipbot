import aiohttp
import logging
from typing import Dict, Any, Optional
from config import WEBHOOK_URL

logger = logging.getLogger(__name__)

# Маппинг внутренних статусов заказов на внешние статусы для webhook
ORDER_STATUS_MAPPING = {
    "in_transit": "stage_delivery_10",
    "done": "stage_delivery_11",
    # Остальные статусы остаются без изменений
    "waiting": "waiting",
    "cancelled": "cancelled"
}

def map_order_status(status: str) -> str:
    """
    Преобразует внутренний статус заказа в внешний статус для webhook
    
    Args:
        status: Внутренний статус заказа (waiting, in_transit, done, cancelled)
        
    Returns:
        Внешний статус для webhook
    """
    return ORDER_STATUS_MAPPING.get(status, status)

async def send_webhook(event_type: str, data: Dict[str, Any]) -> bool:
    """
    Отправляет webhook с данными события
    
    Args:
        event_type: Тип события (shift_start, shift_end, order_accepted, order_completed)
        data: Полные данные для отправки
        
    Returns:
        True если успешно отправлено, False в противном случае
    """
    if not WEBHOOK_URL:
        logger.debug(f"WEBHOOK_URL not configured, skipping webhook for {event_type}")
        return False
    
    payload = {
        "event_type": event_type,
        "timestamp": data.get("timestamp"),
        "data": data
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                WEBHOOK_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    logger.info(f"Webhook sent successfully for {event_type}")
                    return True
                else:
                    logger.warning(f"Webhook failed with status {response.status} for {event_type}")
                    return False
    except Exception as e:
        logger.error(f"Error sending webhook for {event_type}: {e}", exc_info=True)
        return False

async def prepare_courier_data(db, courier: Dict[str, Any]) -> Dict[str, Any]:
    """Подготавливает данные курьера для webhook"""
    courier_data = {
        "courier_id": str(courier["_id"]),
        "name": courier.get("name"),
        "username": courier.get("username"),
        "tg_chat_id": courier.get("tg_chat_id"),
        "is_on_shift": courier.get("is_on_shift", False),
        "shift_started_at": courier.get("shift_started_at"),
        "current_shift_id": courier.get("current_shift_id"),
        "last_location": courier.get("last_location")
    }
    
    # Получаем статистику заказов
    courier_id = courier["_id"]
    active_orders = await db.couriers_deliveries.count_documents({
        "courier_tg_chat_id": courier.get("tg_chat_id"),
        "status": {"$in": ["waiting", "in_transit"]}
    })
    
    courier_data["active_orders_count"] = active_orders
    
    return courier_data

async def prepare_order_data(db, order: Dict[str, Any]) -> Dict[str, Any]:
    """Подготавливает полные данные заказа для webhook"""
    # Получаем данные курьера
    courier = await db.couriers.find_one({"_id": order.get("assigned_to")})
    courier_data = None
    if courier:
        courier_data = {
            "courier_id": str(courier["_id"]),
            "name": courier.get("name"),
            "username": courier.get("username"),
            "tg_chat_id": courier.get("tg_chat_id")
        }
    
    # Получаем внутренний статус и преобразуем его для webhook
    internal_status = order.get("status")
    mapped_status = map_order_status(internal_status)
    
    order_data = {
        "order_id": str(order["_id"]),
        "external_id": order.get("external_id"),
        "status": mapped_status,  # Используем преобразованный статус
        "payment_status": order.get("payment_status"),
        "is_cash_payment": order.get("is_cash_payment", False),
        "delivery_time": order.get("delivery_time"),
        "priority": order.get("priority", 0),
        "brand": order.get("brand"),
        "source": order.get("source"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "client": order.get("client", {}),
        "address": order.get("address"),
        "map_url": order.get("map_url"),
        "notes": order.get("notes"),
        "photos": order.get("photos", []),
        "pay_photo": order.get("pay_photo", []),
        "courier": courier_data
    }
    
    logger.debug(f"Order status mapped: {internal_status} -> {mapped_status} for order {order.get('external_id')}")
    
    return order_data

