"""
Утилита для сокращения длинных URL через публичные сервисы
"""
import aiohttp
import logging

logger = logging.getLogger(__name__)

async def shorten_url(url: str) -> str:
    """
    Сокращает длинный URL через публичные сервисы.
    
    Args:
        url: Длинный URL для сокращения
        
    Returns:
        Сокращенный URL или исходный URL в случае ошибки
    """
    # Список сервисов для сокращения ссылок (в порядке приоритета)
    services = [
        {
            "name": "is.gd",
            "url": f"https://is.gd/create.php?format=json&url={url}"
        },
        {
            "name": "tinyurl",
            "url": f"https://tinyurl.com/api-create.php?url={url}"
        }
    ]
    
    async with aiohttp.ClientSession() as session:
        for service in services:
            try:
                async with session.get(service["url"], timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        if service["name"] == "is.gd":
                            # is.gd возвращает JSON
                            data = await response.json()
                            if "shorturl" in data:
                                short_url = data["shorturl"]
                                logger.debug(f"URL shortened via {service['name']}: {url[:50]}... -> {short_url}")
                                return short_url
                        elif service["name"] == "tinyurl":
                            # tinyurl возвращает plain text
                            short_url = (await response.text()).strip()
                            if short_url and short_url.startswith("http"):
                                logger.debug(f"URL shortened via {service['name']}: {url[:50]}... -> {short_url}")
                                return short_url
            except Exception as e:
                logger.warning(f"Failed to shorten URL via {service['name']}: {e}")
                continue
    
    # Если все сервисы не сработали, возвращаем исходный URL
    logger.warning(f"All URL shortening services failed, using original URL")
    return url

