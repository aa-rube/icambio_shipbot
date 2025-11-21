import aiohttp
import logging
import json
from typing import Dict, Any, Optional, List
from config import ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_API_KEY

logger = logging.getLogger(__name__)

# Кэш для UID пользователя
_odoo_uid_cache = None

def clear_odoo_uid_cache():
    """Очищает кэш UID пользователя Odoo (полезно при ошибках аутентификации)"""
    global _odoo_uid_cache
    _odoo_uid_cache = None
    logger.debug("Odoo UID cache cleared")

async def get_odoo_uid() -> Optional[int]:
    """Получает UID пользователя через аутентификацию с API ключом"""
    global _odoo_uid_cache
    
    if _odoo_uid_cache:
        return _odoo_uid_cache
    
    if not ODOO_URL or not ODOO_LOGIN or not ODOO_API_KEY:
        return None
    
    try:
        # Аутентификация через JSON-RPC /jsonrpc endpoint с методом authenticate
        # Используем тот же URL что и для обычных вызовов
        auth_payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "common",
                "method": "authenticate",
                "args": [
                    ODOO_DB or "",  # database name (пустая строка если не указано)
                    ODOO_LOGIN,     # login
                    ODOO_API_KEY,   # password (API ключ)
                    {}              # user agent env (пустой dict)
                ]
            },
            "id": 1
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ODOO_URL,
                json=auth_payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        result = json.loads(response_text)
                    except Exception as e:
                        logger.error(f"[Odoo Auth] Failed to parse JSON response: {e}")
                        return None
                    
                    if "error" in result:
                        error_data = result.get("error", {})
                        error_message = error_data.get("message", "Unknown error")
                        error_code = error_data.get("code", 0)
                        
                        logger.error(f"[Odoo Auth] Error: code={error_code}, message={error_message}")
                        
                        # Если ошибка аутентификации, очищаем кэш чтобы можно было повторить попытку
                        if error_code == 200 or "Access Denied" in str(error_message):
                            _odoo_uid_cache = None
                        
                        return None
                    uid = result.get("result")
                    if uid and isinstance(uid, int):
                        _odoo_uid_cache = uid
                        logger.debug(f"[Odoo Auth] Authentication successful, UID: {uid}")
                        return uid
                    elif uid is False:
                        # False означает что аутентификация не удалась
                        logger.warning("[Odoo Auth] Authentication failed - invalid credentials")
                        _odoo_uid_cache = None
                        return None
                    else:
                        logger.warning(f"[Odoo Auth] Invalid UID returned: {uid}")
                        return None
                else:
                    logger.warning(f"[Odoo Auth] HTTP error status {response.status}")
                    return None
        return None
    except Exception as e:
        logger.error(f"[Odoo Auth] Exception during authentication: {e}", exc_info=True)
        # Очищаем кэш при ошибке чтобы можно было повторить попытку
        _odoo_uid_cache = None
        return None

async def odoo_call(method: str, model: str, method_name: str, args: list, kwargs: dict = None) -> Optional[Any]:
    """
    Выполняет JSON-RPC запрос к Odoo API (старый формат: /jsonrpc)
    Использует API ключ для аутентификации
    
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
    
    # Получаем UID через аутентификацию с API ключом
    uid = await get_odoo_uid()
    if not uid:
        logger.warning("Failed to get Odoo UID - authentication may have failed")
        return None
    
    # Формат запроса для Odoo JSON-RPC API (старый формат: /jsonrpc)
    # Используем объектный формат для params, как в аутентификации
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [
                ODOO_DB or "",  # database name (пустая строка если не указано)
                uid,  # user id
                ODOO_API_KEY,  # API ключ используется как пароль
                model,  # model
                method_name,  # method
                args,  # args
                kwargs or {}  # kwargs
            ]
        },
        "id": 1
    }
    
    logger.debug(f"[Odoo API] Calling: model={model}, method={method_name}")
    
    try:
        async with aiohttp.ClientSession() as session:
            # API ключ также передается через Basic Auth для дополнительной безопасности
            async with session.post(
                ODOO_URL,
                json=payload,
                auth=aiohttp.BasicAuth(ODOO_LOGIN, ODOO_API_KEY),
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        result = json.loads(response_text)
                    except Exception as e:
                        logger.error(f"[Odoo API] Failed to parse JSON response: {e}")
                        logger.error(f"[Odoo API] Response text: {response_text[:500]}")
                        return None
                    
                    if "error" in result:
                        error_data = result.get("error", {})
                        error_message = error_data.get("message", "Unknown error")
                        error_code = error_data.get("code", 0)
                        error_data_full = error_data.get("data", {})
                        
                        logger.error(f"[Odoo API] Error: code={error_code}, message={error_message}")
                        # Логируем полную информацию об ошибке
                        if error_data_full:
                            logger.error(f"[Odoo API] Error data: {json.dumps(error_data_full, indent=2, ensure_ascii=False, default=str)}")
                        logger.error(f"[Odoo API] Full error response: {json.dumps(result, indent=2, ensure_ascii=False, default=str)}")
                        
                        # Если ошибка связана с аутентификацией, очищаем кэш
                        if error_code == 200 or "Access Denied" in str(error_message) or "authentication" in str(error_message).lower():
                            clear_odoo_uid_cache()
                        
                        return None
                    
                    api_result = result.get("result")
                    return api_result
                else:
                    logger.warning(f"[Odoo API] HTTP error status {response.status}")
                    return None
    except Exception as e:
        logger.error(f"[Odoo API] Exception during API call: {e}", exc_info=True)
        return None

async def create_courier(name: str, courier_tg_chat_id: str, phone: Optional[str] = None, username: Optional[str] = None, is_online: bool = False) -> Optional[int]:
    """
    Создает курьера в Odoo
    
    Args:
        name: Имя курьера
        courier_tg_chat_id: Telegram Chat ID курьера (строка)
        phone: Телефон курьера (опционально)
        username: Username курьера (опционально, НЕ сохраняется в Odoo - поле не существует в модели)
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
    
    # Поле username не существует в модели courier.person в Odoo, поэтому не добавляем его
    # if username:
    #     courier_data["username"] = username
    
    # В старом формате /jsonrpc аргументы для create должны быть в двойном массиве [[{...}]]
    result = await odoo_call("call", "courier.person", "create", [[courier_data]])
    
    if result:
        logger.debug(f"Courier created in Odoo with ID: {result}")
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
        logger.debug(f"Courier {courier_tg_chat_id} status updated to {'online' if is_online else 'offline'}")
        return True
    else:
        logger.warning(f"Failed to update courier {courier_tg_chat_id} status")
        return False

async def update_courier_photo(courier_tg_chat_id: str, photo_base64: str) -> bool:
    """
    Обновляет фотографию курьера в Odoo по courier_tg_chat_id
    
    Args:
        courier_tg_chat_id: Telegram Chat ID курьера (строка) - используется как основной идентификатор
        photo_base64: Base64-строка (чистая или с префиксом data URI, например, "data:image/jpeg;base64,...")
                     Odoo ожидает только чистый base64 без префикса
        
    Returns:
        True если успешно обновлено, False в противном случае
    """
    try:
        # Извлекаем чистый base64, если передан data URI
        clean_base64 = photo_base64
        if photo_base64.startswith('data:'):
            # Убираем префикс data URI (например, "data:image/jpeg;base64,")
            # Ищем запятую после base64,
            comma_index = photo_base64.find(',')
            if comma_index != -1:
                clean_base64 = photo_base64[comma_index + 1:]
                logger.debug(f"Extracted clean base64 from data URI (removed {comma_index + 1} chars)")
            else:
                logger.warning(f"Data URI format seems incorrect, using as-is")
        
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
        
        # Обновляем фото используя внутренний ID
        # Поле image_1920 автоматически создаст thumbnail image_128
        # Odoo ожидает только чистый base64 без префикса data URI
        result = await odoo_call(
            "call",
            "courier.person",
            "write",
            [[odoo_internal_id], {"image_1920": clean_base64}]
        )
        
        if result:
            logger.info(f"Courier {courier_tg_chat_id} photo updated successfully in Odoo")
            return True
        else:
            logger.warning(f"Failed to update courier {courier_tg_chat_id} photo in Odoo")
            return False
    except Exception as e:
        logger.error(f"Error updating courier {courier_tg_chat_id} photo in Odoo: {e}", exc_info=True)
        return False

async def delete_courier(courier_tg_chat_id: str) -> bool:
    """
    Удаляет курьера из Odoo по Telegram Chat ID
    
    Args:
        courier_tg_chat_id: Telegram Chat ID курьера (строка)
        
    Returns:
        True если успешно удалено, False в противном случае
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
        logger.warning(f"Courier with TG ID {courier_tg_chat_id} not found in Odoo, nothing to delete")
        return False
    
    # Получаем внутренний ID Odoo из результата search
    odoo_internal_id = search_result[0]
    
    # Удаляем курьера используя метод unlink
    # В Odoo unlink принимает список ID: [[id1, id2, ...]]
    result = await odoo_call("call", "courier.person", "unlink", [[odoo_internal_id]])
    
    if result:
        logger.info(f"Courier {courier_tg_chat_id} (Odoo ID: {odoo_internal_id}) deleted from Odoo")
        return True
    else:
        logger.warning(f"Failed to delete courier {courier_tg_chat_id} from Odoo")
        return False

async def get_all_couriers_from_odoo() -> List[Dict[str, Any]]:
    """
    Получает всех курьеров из Odoo
    
    Returns:
        Список курьеров из Odoo с полями: id, name, phone, courier_tg_chat_id, is_online
        (поле username не существует в модели Odoo)
    """
    result = await odoo_call(
        "call",
        "courier.person",
        "search_read",
        [
            [],  # Пустой фильтр - получаем всех курьеров
            ["id", "name", "phone", "courier_tg_chat_id", "is_online"]  # username не существует в модели
        ]
    )
    
    if result and isinstance(result, list):
        logger.debug(f"Found {len(result)} couriers in Odoo")
        return result
    else:
        logger.warning("Failed to get couriers from Odoo or empty result")
        return []

async def get_lead(lead_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает полный объект лида из Odoo по ID лида
    
    Args:
        lead_id: ID лида в Odoo
        
    Returns:
        Полный объект лида или None в случае ошибки
    """
    try:
        # Преобразуем lead_id в int, если это строка
        if isinstance(lead_id, str):
            lead_id = int(lead_id)
        
        # Получаем все данные лида из Odoo (без указания полей - получим все)
        # Для метода read: args = [[id1, id2, ...]], kwargs = {} (без fields - получим все поля)
        result = await odoo_call(
            "call",
            "crm.lead",
            "read",
            [[lead_id]],  # Список ID в двойном массиве
            {}  # Пустой kwargs - получим все поля
        )
        
        if result and len(result) > 0:
            lead_data = result[0]
            logger.debug(f"Lead {lead_id} retrieved successfully")
            return lead_data
        else:
            logger.warning(f"Lead {lead_id} not found in Odoo")
            return None
    except ValueError:
        logger.error(f"Invalid lead_id format: {lead_id}")
        return None
    except Exception as e:
        logger.error(f"Error getting lead {lead_id}: {e}", exc_info=True)
        return None

async def send_message_to_lead_chatter(lead_id: int, message_body: str) -> bool:
    """
    Отправляет сообщение в чаттер лида в Odoo от имени пользователя API ключа
    
    Args:
        lead_id: ID лида в Odoo
        message_body: Текст сообщения для отправки в чаттер
        
    Returns:
        True если успешно отправлено, False в противном случае
    """
    try:
        # Преобразуем lead_id в int, если это строка
        if isinstance(lead_id, str):
            lead_id = int(lead_id)
        
        # Отправляем сообщение в чаттер лида через метод message_post
        # Для метода message_post: args = [[id1, id2, ...]], kwargs = {"body": "текст", "message_type": "comment"}
        # message_post принимает аргументы как keyword arguments, а не позиционные
        result = await odoo_call(
            "call",
            "crm.lead",
            "message_post",
            [[lead_id]],  # Только список ID записей
            {"body": message_body, "message_type": "comment"}  # Аргументы передаются через kwargs
        )
        
        if result:
            logger.info(f"Message sent to lead {lead_id} chatter successfully")
            return True
        else:
            logger.warning(f"Failed to send message to lead {lead_id} chatter")
            return False
    except ValueError:
        logger.error(f"Invalid lead_id format: {lead_id}")
        return False
    except Exception as e:
        logger.error(f"Error sending message to lead {lead_id} chatter: {e}", exc_info=True)
        return False

async def update_order_courier(external_id: str, courier_tg_chat_id: str) -> bool:
    """
    Обновляет курьера заказа в Odoo
    
    Args:
        external_id: Внешний ID заказа (ID лида в Odoo)
        courier_tg_chat_id: Telegram Chat ID нового курьера (строка)
        
    Returns:
        True если успешно обновлено, False в противном случае
    """
    try:
        # Преобразуем external_id в int, если это строка
        if isinstance(external_id, str):
            try:
                lead_id = int(external_id)
            except ValueError:
                logger.warning(f"Invalid external_id format (not a number): {external_id}")
                return False
        else:
            lead_id = external_id
        
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
        
        # Получаем внутренний ID курьера из результата search
        courier_odoo_id = search_result[0]
        
        # Обновляем курьера заказа в лиде
        # Предполагаем, что в модели crm.lead есть поле courier_id или courier_tg_chat_id
        # Нужно проверить структуру модели в Odoo
        # Для начала попробуем обновить через поле courier_id (если оно существует)
        result = await odoo_call(
            "call",
            "crm.lead",
            "write",
            [[lead_id], {"courier_id": courier_odoo_id}]  # Предполагаем, что поле называется courier_id
        )
        
        if result:
            logger.info(f"Order {external_id} courier updated to {courier_tg_chat_id} in Odoo")
            return True
        else:
            # Если не получилось с courier_id, попробуем через courier_tg_chat_id (если такое поле есть)
            logger.debug(f"Trying to update via courier_tg_chat_id field")
            result2 = await odoo_call(
                "call",
                "crm.lead",
                "write",
                [[lead_id], {"courier_tg_chat_id": str(courier_tg_chat_id)}]
            )
            if result2:
                logger.info(f"Order {external_id} courier updated to {courier_tg_chat_id} in Odoo (via courier_tg_chat_id)")
                return True
            else:
                logger.warning(f"Failed to update order {external_id} courier in Odoo")
                return False
    except Exception as e:
        logger.error(f"Error updating order {external_id} courier in Odoo: {e}", exc_info=True)
        return False

