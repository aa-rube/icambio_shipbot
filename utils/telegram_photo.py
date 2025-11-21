import logging
import base64
import json
import io
from typing import Optional
from aiogram import Bot
import aiohttp
from PIL import Image

logger = logging.getLogger(__name__)

async def get_user_profile_photo_base64(bot: Bot, user_id: int) -> Optional[str]:
    """
    Получает фото профиля пользователя из Telegram и конвертирует в base64
    Использует прямые HTTPS запросы к API Telegram для избежания проблем с file_id
    Валидирует изображение через PIL перед возвратом
    
    Args:
        bot: Экземпляр бота для работы с Telegram API (используется только для получения токена)
        user_id: ID пользователя в Telegram
        
    Returns:
        Чистая base64-строка (без префикса data URI) или None в случае ошибки
    """
    try:
        # Получаем токен бота
        bot_token = bot.token
        
        # ШАГ 1: Получаем список фото профиля пользователя через API
        logger.debug(f"🔍 Getting profile photos for user {user_id}")
        url = f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={"user_id": user_id, "limit": 1}) as response:
                if response.status != 200:
                    logger.error(f"Failed to get profile photos: HTTP {response.status}")
                    return None
                
                result = await response.json()
                
                if not result.get('ok'):
                    logger.debug(f"User {user_id} has no profile photos or API error: {result.get('description', 'Unknown error')}")
                    return None
                
                photos_data = result.get('result', {})
                total_count = photos_data.get('total_count', 0)
                
                if total_count == 0:
                    logger.debug(f"User {user_id} has no profile photos")
                    return None
                
                photos = photos_data.get('photos', [])
                if not photos or len(photos) == 0:
                    logger.debug(f"User {user_id} photo array is empty")
                    return None
                
                # Берем первую (самую большую) версию первой фотографии
                photo_sizes = photos[0]
                if not photo_sizes or len(photo_sizes) == 0:
                    logger.debug(f"User {user_id} photo has no sizes")
                    return None
                
                # Первый элемент - самая большая версия
                largest_photo = photo_sizes[0]
                file_id = largest_photo.get('file_id')
                
                if not file_id:
                    logger.error(f"Failed to get file_id from photo data")
                    return None
                
                logger.debug(f"🔍 Downloading photo for user {user_id}, file_id: {file_id}")
                
                # ШАГ 2: Получаем путь к файлу по file_id
                get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile"
                async with session.post(get_file_url, data={"file_id": file_id}) as file_response:
                    if file_response.status != 200:
                        logger.error(f"Failed to get file path: HTTP {file_response.status}")
                        return None
                    
                    file_result = await file_response.json()
                    
                    if not file_result.get('ok'):
                        error_desc = file_result.get('description', 'Unknown error')
                        logger.error(f"Failed to get file path: {error_desc}")
                        return None
                    
                    file_path = file_result['result'].get('file_path')
                    if not file_path:
                        logger.error(f"File path is empty in API response")
                        return None
                    
                    logger.debug(f"File path: {file_path}")
                    
                    # ШАГ 3: Скачиваем файл из Telegram
                    download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
                    async with session.get(download_url) as download_response:
                        if download_response.status != 200:
                            logger.error(f"Failed to download file: HTTP {download_response.status}")
                            return None
                        
                        photo_bytes = await download_response.read()
                        
                        if not photo_bytes:
                            logger.error(f"Downloaded file is empty")
                            return None
                        
                        # Валидация изображения через PIL
                        try:
                            image = Image.open(io.BytesIO(photo_bytes))
                            # Проверяем, что это действительно изображение, пытаясь загрузить его
                            image.verify()
                            # verify() закрывает файл, поэтому нужно открыть заново для дальнейшего использования
                            image = Image.open(io.BytesIO(photo_bytes))
                            logger.debug(f"✅ Image validated: format={image.format}, size={image.size}, mode={image.mode}")
                        except Exception as img_error:
                            logger.error(f"❌ Invalid image file for user {user_id}: {img_error}")
                            return None
                        
                        # Проверяем Content-Type ответа от Telegram
                        content_type = download_response.headers.get('Content-Type', '')
                        if content_type and not content_type.startswith('image/'):
                            logger.warning(f"⚠️ Unexpected Content-Type: {content_type}, but image validation passed")
                        
                        # Конвертируем в base64 (только чистый base64, без data URI префикса)
                        photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')
                        
                        logger.info(f"✅ Successfully converted user {user_id} photo to base64, size: {len(photo_bytes)} bytes")
                        return photo_base64
        
    except Exception as e:
        logger.error(f"❌ Error getting user {user_id} profile photo: {e}", exc_info=True)
        return None

