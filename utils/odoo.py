import aiohttp
import logging
import json
from typing import Dict, Any, Optional
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
        
        logger.info(f"[Odoo Auth] Request URL: {ODOO_URL}")
        logger.info(f"[Odoo Auth] Request payload: {json.dumps(auth_payload, indent=2, ensure_ascii=False)}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ODOO_URL,
                json=auth_payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response_text = await response.text()
                logger.info(f"[Odoo Auth] Response status: {response.status}")
                logger.info(f"[Odoo Auth] Response body: {response_text}")
                
                if response.status == 200:
                    try:
                        result = json.loads(response_text)
                        logger.info(f"[Odoo Auth] Response JSON: {json.dumps(result, indent=2, ensure_ascii=False)}")
                    except Exception as e:
                        logger.error(f"[Odoo Auth] Failed to parse JSON response: {e}, body: {response_text}")
                        return None
                    
                    if "error" in result:
                        error_data = result.get("error", {})
                        error_message = error_data.get("message", "Unknown error")
                        error_code = error_data.get("code", 0)
                        error_data_full = error_data.get("data", {})
                        error_name = error_data_full.get("name", "") if isinstance(error_data_full, dict) else ""
                        error_debug = error_data_full.get("debug", "") if isinstance(error_data_full, dict) else ""
                        
                        logger.error(f"[Odoo Auth] Error: code={error_code}, message={error_message}, name={error_name}")
                        if error_debug:
                            logger.error(f"[Odoo Auth] Error debug traceback:\n{error_debug}")
                        
                        # Если ошибка аутентификации, очищаем кэш чтобы можно было повторить попытку
                        if error_code == 200 or "Access Denied" in str(error_message):
                            _odoo_uid_cache = None
                            logger.warning("Cleared Odoo UID cache due to authentication failure")
                        
                        return None
                    uid = result.get("result")
                    if uid and isinstance(uid, int):
                        _odoo_uid_cache = uid
                        logger.info(f"[Odoo Auth] Authentication successful, UID: {uid}")
                        return uid
                    elif uid is False:
                        # False означает что аутентификация не удалась
                        logger.warning("[Odoo Auth] Authentication returned False - invalid credentials")
                        _odoo_uid_cache = None
                        return None
                    else:
                        logger.warning(f"[Odoo Auth] Invalid UID returned: {uid}")
                        return None
                else:
                    logger.warning(f"[Odoo Auth] HTTP error status {response.status}, body: {response_text}")
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
    
    logger.info(f"[Odoo API] Calling: model={model}, method={method_name}")
    logger.info(f"[Odoo API] Request URL: {ODOO_URL}")
    logger.info(f"[Odoo API] Request payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
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
                logger.info(f"[Odoo API] Response status: {response.status}")
                logger.info(f"[Odoo API] Response body: {response_text}")
                
                if response.status == 200:
                    try:
                        result = json.loads(response_text)
                        logger.info(f"[Odoo API] Response JSON: {json.dumps(result, indent=2, ensure_ascii=False)}")
                    except Exception as e:
                        logger.error(f"[Odoo API] Failed to parse JSON response: {e}, body: {response_text}")
                        return None
                    
                    if "error" in result:
                        error_data = result.get("error", {})
                        error_message = error_data.get("message", "Unknown error")
                        error_code = error_data.get("code", 0)
                        error_data_full = error_data.get("data", {})
                        error_name = error_data_full.get("name", "") if isinstance(error_data_full, dict) else ""
                        error_debug = error_data_full.get("debug", "") if isinstance(error_data_full, dict) else ""
                        
                        logger.error(f"[Odoo API] Error: code={error_code}, message={error_message}, name={error_name}")
                        if error_debug:
                            logger.error(f"[Odoo API] Error debug traceback:\n{error_debug}")
                        
                        # Если ошибка связана с аутентификацией, очищаем кэш
                        if error_code == 200 or "Access Denied" in str(error_message) or "authentication" in str(error_message).lower():
                            clear_odoo_uid_cache()
                        
                        return None
                    
                    api_result = result.get("result")
                    logger.info(f"[Odoo API] Success, result: {api_result}")
                    return api_result
                else:
                    logger.warning(f"[Odoo API] HTTP error status {response.status}, body: {response_text}")
                    return None
    except Exception as e:
        logger.error(f"[Odoo API] Exception during API call: {e}", exc_info=True)
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
    
    # В старом формате /jsonrpc аргументы для create должны быть в двойном массиве [[{...}]]
    result = await odoo_call("call", "courier.person", "create", [[courier_data]])
    
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

