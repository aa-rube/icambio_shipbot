# Traefik + Odoo: Odoo перехватывает запросы к FastAPI и добавляет префикс языка

## Описание проблемы

У меня настроена инфраструктура с Traefik в качестве reverse proxy, Odoo (порт 8069) и FastAPI приложение (порт 5055) на одном домене `icambio-test-odoo.setrealtora.ru`.

**Проблема:** Odoo перехватывает запросы к FastAPI endpoint `/api/location/{key}` и добавляет префикс языка `/en/`, что приводит к 404 ошибке.

**Ожидаемое поведение:**
- Запрос `GET /api/location/{key}` должен обрабатываться Traefik и проксироваться в FastAPI
- FastAPI должен вернуть редирект 302/303 на Google Maps

**Фактическое поведение:**
1. Первый запрос `GET /api/location/{key}` возвращает 303 (редирект) - это правильно
2. Но затем Odoo перехватывает запрос и пытается обработать `GET /en/api/location/{key}`, что приводит к 404

**Что уже пробовал:**
- Установил высокий приоритет (10000) для роутеров Traefik `/api`
- Добавил fallback обработчик в FastAPI для `/{lang}/api/location/{key}`
- Но проблема сохраняется - Odoo все еще перехватывает запросы

## Архитектура

```
Internet → Traefik → [Odoo (8069) | FastAPI (5055)]
```

- **Traefik:** Reverse proxy с Docker provider
- **Odoo:** Работает на порту 8069, обрабатывает основной сайт
- **FastAPI:** Работает на порту 5055, обрабатывает `/api/*` endpoints

## Основная ошибка

Из логов Odoo:

```
odoo-app  | 2025-11-08 15:03:32,270 31 INFO icambio_first_test werkzeug: 172.18.0.1 - - [08/Nov/2025 15:03:32] "GET /api/location/8vmhKrn6uMg9uL9EcMcPZQ-300 HTTP/1.1" 303 - 1 0.002 0.027

odoo-app  | 2025-11-08 15:03:32,390 33 INFO icambio_first_test werkzeug: 172.18.0.1 - - [08/Nov/2025 15:03:32] "GET /en/api/location/8vmhKrn6uMg9uL9EcMcPZQ-300 HTTP/1.1" 404 - 17 0.017 0.051
```

**Анализ:**
1. Первый запрос `/api/location/{key}` возвращает 303 - это правильно, запрос доходит до FastAPI
2. Второй запрос `/en/api/location/{key}` возвращает 404 - Odoo пытается обработать запрос с префиксом языка

**Вопрос:** Почему Odoo перехватывает запросы к `/api/*` даже при высоком приоритете роутера в Traefik? Как правильно настроить Traefik, чтобы `/api/*` обрабатывался раньше Odoo?

## Список файлов для копирования

Пожалуйста, предоставьте содержимое следующих файлов:

1. **docker-compose.traefik.shipbot.yml** - Конфигурация Traefik для FastAPI
2. **api_server.py** (строки 139-201) - FastAPI endpoint для редиректа
3. **utils/location_redirect.py** - Утилита для генерации URL редиректа
4. **docker-compose.traefik.yml** (Odoo) - Конфигурация Traefik для Odoo (если есть)

## Конфигурации

### 1. Traefik конфигурация для FastAPI (docker-compose.traefik.shipbot.yml)

```yaml
services:
  shipbot-api:
    extra_hosts:
      - "host.docker.internal:host-gateway"
    labels:
      - traefik.enable=true
      - traefik.docker.network=root_default
      
      # --- HTTP -> HTTPS ---
      - traefik.http.middlewares.shipbot-api-https-redirect.redirectscheme.scheme=https
      - traefik.http.middlewares.shipbot-api-headers.headers.customrequestheaders.X-Forwarded-Proto=https
      
      # --- HTTP Router (редирект на HTTPS) ---
      # Высокий приоритет (10000) чтобы обрабатывать раньше Odoo
      - traefik.http.routers.shipbot-api-http.priority=10000
      - traefik.http.routers.shipbot-api-http.rule=Host(`icambio-test-odoo.setrealtora.ru`) && PathPrefix(`/api`)
      - traefik.http.routers.shipbot-api-http.entrypoints=web
      - traefik.http.routers.shipbot-api-http.middlewares=shipbot-api-https-redirect
      - traefik.http.routers.shipbot-api-http.service=shipbot-api
      
      # --- HTTPS Router (основной API, включая /api/location) ---
      # Высокий приоритет (10000) чтобы обрабатывать раньше Odoo
      - traefik.http.routers.shipbot-api.priority=10000
      - traefik.http.routers.shipbot-api.rule=Host(`icambio-test-odoo.setrealtora.ru`) && PathPrefix(`/api`)
      - traefik.http.routers.shipbot-api.entrypoints=websecure
      - traefik.http.routers.shipbot-api.tls=true
      - traefik.http.routers.shipbot-api.tls.certresolver=mytlschallenge
      - traefik.http.routers.shipbot-api.middlewares=shipbot-api-headers
      - traefik.http.routers.shipbot-api.service=shipbot-api
      
      # --- Service ---
      - traefik.http.services.shipbot-api.loadbalancer.server.port=5055
      - traefik.http.services.shipbot-api.loadbalancer.passhostheader=true
      
    networks:
      - shipbot-net       # из базового compose
      - traefik-net       # внешний, определён ниже

networks:
  traefik-net:
    external: true
    name: root_default
```

### 2. FastAPI endpoint (api_server.py)

```python
@app.get("/api/location/{key}")
@app.get("/{lang}/api/location/{key}")  # Обработка префикса языка от Odoo (fallback)
async def location_redirect(key: str, lang: str = None):
    """
    Редирект на Google Maps с координатами курьера.
    Проверяет ключ в Redis, обновляет координаты из актуального источника и редиректит на карту.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Получаем данные редиректа (БЕЗ обновления TTL - чтобы ключ истекал через 24 часа)
    redis = get_redis()
    data_str = await redis.get(f"location:redirect:{key}")
    
    if not data_str:
        # Если ключ не найден или истек - игнорируем запрос
        logger.warning(f"Location redirect key not found or expired: {key}")
        raise HTTPException(status_code=404, detail="Link expired or invalid")
    
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in redirect data for key: {key}")
        raise HTTPException(status_code=500, detail="Invalid redirect data")
    
    chat_id = data.get("chat_id")
    
    # Получаем актуальную локацию из Redis или БД
    lat = None
    lon = None
    
    # Сначала пытаемся из Redis (быстрее и актуальнее)
    loc_str = await redis.get(f"courier:loc:{chat_id}")
    if loc_str:
        try:
            parts = loc_str.split(",")
            if len(parts) == 2:
                lat = float(parts[0])
                lon = float(parts[1])
        except (ValueError, IndexError):
            pass
    
    # Если не нашли в Redis, используем из ключа (fallback)
    if lat is None or lon is None:
        lat = data.get("lat")
        lon = data.get("lon")
    
    if not lat or not lon:
        logger.error(f"Invalid coordinates in redirect data: {data}")
        raise HTTPException(status_code=500, detail="Invalid location data")
    
    # Валидация координат
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        logger.error(f"Coordinates out of range: lat={lat}, lon={lon}")
        raise HTTPException(status_code=500, detail="Invalid coordinates")
    
    # Формируем ссылку на Google Maps
    maps_url = f"https://maps.google.com/?q={lat},{lon}"
    
    logger.debug(f"Redirecting location key {key} to Google Maps: {lat},{lon}")
    
    # Редиректим на Google Maps
    return RedirectResponse(url=maps_url, status_code=302)
```

### 3. Утилита для генерации URL (utils/location_redirect.py)

```python
def get_location_redirect_url(key: str) -> str:
    """
    Формирует URL для редиректа локации.
    
    Args:
        key: Ключ редиректа
        
    Returns:
        Полный URL для редиректа
    """
    return f"{API_BASE_URL}/api/location/{key}"
```

## Вопросы к сообществу

1. **Почему Odoo перехватывает запросы к `/api/*` даже при высоком приоритете роутера в Traefik?**
   - Может ли Odoo обрабатывать запросы на уровне приложения до Traefik?
   - Как правильно настроить приоритеты в Traefik для нескольких сервисов на одном домене?

2. **Как правильно настроить Traefik, чтобы `/api/*` обрабатывался раньше Odoo?**
   - Нужно ли настраивать приоритеты для роутеров Odoo?
   - Есть ли способ исключить `/api/*` из обработки Odoo?

3. **Альтернативные решения:**
   - Использовать поддомен для API (например, `api.icambio-test-odoo.setrealtora.ru`)?
   - Использовать другой путь, который точно не будет конфликтовать с Odoo?
   - Настроить Odoo, чтобы он не обрабатывал `/api/*`?

## Дополнительная информация

- **Traefik версия:** (укажите версию)
- **Odoo версия:** (укажите версию)
- **FastAPI версия:** (укажите версию)
- **Docker Compose версия:** (укажите версию)

## Логи Traefik

Если есть доступ к логам Traefik, пожалуйста, предоставьте их для анализа.
