import aiohttp
import logging
from typing import Dict, Any, Optional
from config import ODOO_URL, ODOO_LOGIN, ODOO_API_KEY

logger = logging.getLogger(__name__)

async def odoo_call(method: str, model: str, method_name: str, args: list, kwargs: dict = None) -> Optional[Any]:
    """
    Выполняет JSON-RPC запрос к Odoo API
    
    Args:
        method: HTTP метод (обычно "call")
        model: Модель Odoo (например, "courier.person")
        method_name: Метод модели (например, "create", "write", "search_read")
        args: Аргументы метода
        kwargs: Дополнительные аргументы (обычно пустой dict)
        
    Returns:
        Результат запроса или None в случае ошибки
    """
    if not ODOO_URL:
        logger.debug("ODOO_URL not configured, skipping Odoo call")
        return None
    
    if not ODOO_LOGIN or not ODOO_API_KEY:
        logger.warning("ODOO_LOGIN or ODOO_API_KEY not configured")
        return None
    
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": {
            "model": model,
            "method": method_name,
            "args": args,
            "kwargs": kwargs or {}
        },
        "id": 1
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ODOO_URL,
                json=payload,
                auth=aiohttp.BasicAuth(ODOO_LOGIN, ODOO_API_KEY),
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if "error" in result:
                        logger.error(f"Odoo API error: {result['error']}")
                        return None
                    return result.get("result")
                else:
                    logger.warning(f"Odoo API returned status {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error calling Odoo API: {e}", exc_info=True)
        return None

async def create_courier(name: str, courier_tg_chat_id: str, phone: Optional[str] = None, is_online: bool = False) -> Optional[int]:
    """
    Создает курьера в Odoo
    
    Args:
        name: Имя курьера
        courier_tg_chat_id: Telegram Chat ID курьера (строка)
        phone: Телефон курьера (опционально)
        is_online: Статус онлайн/оффлайн
        
    Returns:
        ID созданного курьера в Odoo или None в случае ошибки
    """
    courier_data = {
        "name": name,
        "courier_tg_chat_id": str(courier_tg_chat_id),
        "is_online": is_online
    }
    
    if phone:
        courier_data["phone"] = phone
    
    result = await odoo_call("call", "courier.person", "create", [courier_data])
    
    if result:
        logger.info(f"Courier created in Odoo with ID: {result}")
        return result
    else:
        logger.warning(f"Failed to create courier in Odoo: {name} (TG: {courier_tg_chat_id})")
        return None

async def update_courier_status(courier_tg_chat_id: str, is_online: bool) -> bool:
    """
    Обновляет статус онлайн/оффлайн курьера в Odoo по courier_tg_chat_id
    
    Args:
        courier_tg_chat_id: Telegram Chat ID курьера (строка) - используется как основной идентификатор
        is_online: Новый статус (True = онлайн, False = оффлайн)
        
    Returns:
        True если успешно обновлено, False в противном случае
    """
    # Сначала находим курьера по courier_tg_chat_id через search
    search_result = await odoo_call(
        "call",
        "courier.person",
        "search",
        [
            [["courier_tg_chat_id", "=", str(courier_tg_chat_id)]]
        ]
    )
    
    if not search_result or len(search_result) == 0:
        logger.warning(f"Courier with TG ID {courier_tg_chat_id} not found in Odoo")
        return False
    
    # Получаем внутренний ID Odoo из результата search
    odoo_internal_id = search_result[0]
    
    # Обновляем статус используя внутренний ID
    result = await odoo_call("call", "courier.person", "write", [[odoo_internal_id], {"is_online": is_online}])
    
    if result:
        logger.info(f"Courier {courier_tg_chat_id} (Odoo ID: {odoo_internal_id}) status updated to {'online' if is_online else 'offline'}")
        return True
    else:
        logger.warning(f"Failed to update courier {courier_tg_chat_id} status")
        return False

async def find_courier_by_tg_chat_id(courier_tg_chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Находит курьера в Odoo по Telegram Chat ID
    
    Args:
        courier_tg_chat_id: Telegram Chat ID курьера (строка)
        
    Returns:
        Данные курьера или None если не найден
    """
    result = await odoo_call(
        "call",
        "courier.person",
        "search_read",
        [
            [["courier_tg_chat_id", "=", str(courier_tg_chat_id)]],
            ["id", "name", "phone", "courier_tg_chat_id", "is_online"]
        ]
    )
    
    if result and len(result) > 0:
        logger.info(f"Found courier in Odoo: {result[0]}")
        return result[0]
    else:
        logger.debug(f"Courier with TG ID {courier_tg_chat_id} not found in Odoo")
        return None

