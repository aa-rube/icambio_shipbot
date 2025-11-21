import logging
import base64
from typing import Optional
from aiogram import Bot

logger = logging.getLogger(__name__)

async def get_user_profile_photo_base64(bot: Bot, user_id: int) -> Optional[str]:
    """
    Получает фото профиля пользователя из Telegram и конвертирует в base64 с префиксом data URI
    
    Args:
        bot: Экземпляр бота для работы с Telegram API
        user_id: ID пользователя в Telegram
        
    Returns:
        Base64-строка с префиксом data URI (например, "data:image/jpeg;base64,...") или None в случае ошибки
    """
    try:
        # Получаем список фото профиля пользователя
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        
        if not photos or not photos.photos or len(photos.photos) == 0:
            logger.debug(f"User {user_id} has no profile photos")
            return None
        
        # Берем первое (самое большое) фото
        photo_sizes = photos.photos[0]
        if not photo_sizes or len(photo_sizes) == 0:
            logger.debug(f"User {user_id} photo has no sizes")
            return None
        
        # Берем самый большой размер фото
        largest_photo = photo_sizes[-1]
        file_id = largest_photo.file_id
        
        logger.debug(f"Downloading photo for user {user_id}, file_id: {file_id}")
        
        # Получаем файл
        file = await bot.get_file(file_id)
        
        # Скачиваем файл в память (без указания destination возвращает bytes)
        photo_bytes = await bot.download(file.file_path, destination=None)
        
        # Убеждаемся, что получили байты
        if not isinstance(photo_bytes, bytes):
            # Если по какой-то причине получили путь, читаем файл
            with open(photo_bytes, 'rb') as f:
                photo_bytes = f.read()
        
        # Определяем MIME тип по расширению файла
        # Telegram обычно возвращает jpeg для фото профиля
        mime_type = "image/jpeg"
        if hasattr(file, 'file_path') and file.file_path:
            if file.file_path.endswith('.png'):
                mime_type = "image/png"
            elif file.file_path.endswith('.gif'):
                mime_type = "image/gif"
            elif file.file_path.endswith('.webp'):
                mime_type = "image/webp"
        
        # Конвертируем в base64
        photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        
        # Формируем data URI
        data_uri = f"data:{mime_type};base64,{photo_base64}"
        
        logger.info(f"Successfully converted user {user_id} photo to base64, size: {len(photo_bytes)} bytes")
        return data_uri
        
    except Exception as e:
        logger.error(f"Error getting user {user_id} profile photo: {e}", exc_info=True)
        return None

