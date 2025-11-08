import secrets
import json
from typing import Optional, Dict, Any
from db.redis_client import get_redis
from db.mongo import get_db
from config import LOCATION_REDIRECT_TTL, API_BASE_URL

async def generate_location_redirect_key(chat_id: int, msg_id: int) -> str:
    """
    Генерирует уникальный ключ для редиректа локации курьера.
    Формат: {random_part}-{msg_id}
    
    Args:
        chat_id: Telegram chat ID курьера
        msg_id: ID сообщения с кнопкой
        
    Returns:
        Уникальный ключ для редиректа
        
    Raises:
        ValueError: Если локация не найдена
    """
    # Генерируем случайную часть ключа
    random_part = secrets.token_urlsafe(16)
    key = f"{random_part}-{msg_id}"
    
    # Сначала пытаемся получить локацию из Redis (быстрее)
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
            raise ValueError(f"Location not found for courier {chat_id}")
        
        lat = last_location.get("lat")
        lon = last_location.get("lon")
        
        if not lat or not lon:
            raise ValueError(f"Coordinates not found for courier {chat_id}")
    
    # Валидация координат
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError(f"Invalid coordinates: lat={lat}, lon={lon}")
    
    # Сохраняем данные в Redis
    data = {
        "chat_id": chat_id,
        "lat": lat,
        "lon": lon,
        "msg_id": msg_id
    }
    
    await redis.setex(
        f"location:redirect:{key}",
        LOCATION_REDIRECT_TTL,
        json.dumps(data)
    )
    
    return key

async def get_location_redirect_data(key: str) -> Optional[Dict[str, Any]]:
    """
    Получает данные редиректа по ключу и обновляет TTL.
    
    Args:
        key: Ключ редиректа
        
    Returns:
        Данные редиректа или None если ключ не найден/истек
    """
    redis = get_redis()
    data_str = await redis.get(f"location:redirect:{key}")
    
    if not data_str:
        return None
    
    # Обновляем TTL
    await redis.expire(f"location:redirect:{key}", LOCATION_REDIRECT_TTL)
    
    try:
        return json.loads(data_str)
    except json.JSONDecodeError:
        return None

def get_location_redirect_url(key: str) -> str:
    """
    Формирует URL для редиректа локации.
    
    Args:
        key: Ключ редиректа
        
    Returns:
        Полный URL для редиректа
    """
    return f"{API_BASE_URL}/location/{key}"

