import uvicorn
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from aiogram import Bot
from db.mongo import get_db
from db.redis_client import get_redis
from db.models import IncomingOrder, UpdateOrder, utcnow_iso
from keyboards.orders_kb import new_order_kb
from utils.logger import setup_logging
from utils.order_format import format_order_text
from config import BOT_TOKEN, API_HOST, API_PORT

app = FastAPI(title="Courier Local API")
bot = Bot(BOT_TOKEN)

@app.on_event("startup")
async def on_startup():
    # Инициализация уже выполняется в bot.py, здесь только логирование
    setup_logging()

@app.post("/api/orders")
async def create_order(payload: IncomingOrder):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 📥 Входящий запрос на создание заказа: external_id={payload.external_id}, courier_tg_chat_id={payload.courier_tg_chat_id} (type: {type(payload.courier_tg_chat_id).__name__})")
    logger.debug(f"[API] 📋 Данные заказа: payment_status={payload.payment_status}, priority={payload.priority}, address={payload.address[:50]}...")
    
    db = await get_db()
    redis = get_redis()
    logger.debug(f"[API] 🔌 Подключение к БД и Redis установлено")

    # Find courier by tg_chat_id
    logger.debug(f"[API] 🔍 Поиск курьера по tg_chat_id={payload.courier_tg_chat_id}")
    courier = await db.couriers.find_one({"tg_chat_id": payload.courier_tg_chat_id})
    if not courier:
        logger.warning(f"[API] ⚠️ Курьер не найден: {payload.courier_tg_chat_id}")
        raise HTTPException(status_code=404, detail="Courier not found")
    
    logger.info(f"[API] ✅ Курьер найден: _id={courier.get('_id')}, name={courier.get('name')}, tg_chat_id={courier.get('tg_chat_id')}")

    # Ensure external order id uniqueness (also enforced by unique index)
    logger.debug(f"[API] 🔍 Проверка уникальности external_id={payload.external_id}")
    existing_order = await db.couriers_deliveries.find_one({"external_id": payload.external_id})
    if existing_order:
        logger.warning(f"[API] ⚠️ Заказ с external_id {payload.external_id} уже существует")
        raise HTTPException(status_code=409, detail="Order with this external_id already exists")
    logger.debug(f"[API] ✅ external_id уникален")

    order_doc = {
        "external_id": payload.external_id,
        "courier_tg_chat_id": payload.courier_tg_chat_id,
        "assigned_to": courier["_id"],
        "status": "waiting",
        "payment_status": payload.payment_status,
        "is_cash_payment": payload.is_cash_payment,
        "delivery_time": payload.delivery_time,
        "priority": payload.priority,
        "brand": payload.brand,
        "source": payload.source,
        "created_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
        "client": {
            "name": payload.client_name,
            "phone": payload.client_phone,
            "chat_id": payload.client_chat_id,
            "tg": payload.client_tg,
            "contact_url": payload.contact_url,
        },
        "address": payload.address,
        "map_url": payload.map_url,
        "notes": payload.notes,
        "photos": [],
        "pay_photo": [],
    }
    
    logger.debug(f"[API] 📝 Документ заказа подготовлен: courier_tg_chat_id={order_doc['courier_tg_chat_id']} (type: {type(order_doc['courier_tg_chat_id']).__name__})")
    
    logger.debug(f"[API] 💾 Сохранение заказа в БД...")
    res = await db.couriers_deliveries.insert_one(order_doc)
    order_doc["_id"] = res.inserted_id
    
    logger.info(f"[API] ✅ Заказ успешно создан: _id={order_doc['_id']}, external_id={payload.external_id}, courier_tg_chat_id={order_doc['courier_tg_chat_id']}")

    # Проверка статуса смены курьера (Redis + MongoDB fallback)
    logger.debug(f"[API] 🔍 Проверка статуса смены курьера: tg_chat_id={courier['tg_chat_id']}")
    is_on_redis = await redis.get(f"courier:shift:{courier['tg_chat_id']}")
    is_on_mongo = courier.get("is_on_shift", False)
    
    logger.debug(f"[API] 📊 Статус смены: Redis={is_on_redis}, MongoDB={is_on_mongo}, tg_chat_id={courier['tg_chat_id']}")
    
    # Если ключ в Redis истек, но курьер на смене в MongoDB - восстанавливаем ключ
    if is_on_redis != "on" and is_on_mongo:
        logger.warning(f"[API] ⚠️ Ключ в Redis истек, но курьер на смене в MongoDB. Восстанавливаем ключ в Redis.")
        from config import SHIFT_TTL
        await redis.setex(f"courier:shift:{courier['tg_chat_id']}", SHIFT_TTL, "on")
        is_on_redis = "on"
        logger.info(f"[API] ✅ Ключ в Redis восстановлен для курьера {courier['tg_chat_id']}")
    
    # Отправляем сообщение, если курьер на смене (Redis или MongoDB)
    is_on_shift = is_on_redis == "on" or is_on_mongo
    if is_on_shift:
        logger.info(f"[API] 🚚 Курьер на смене, отправка уведомления в Telegram...")
        
        # Используем унифицированную функцию форматирования заказа
        text = format_order_text(order_doc)

        try:
            logger.debug(f"[API] 📤 Отправка Telegram сообщения курьеру {courier['tg_chat_id']} для заказа {payload.external_id}")
            await bot.send_message(
                courier["tg_chat_id"],
                text,
                parse_mode="HTML",
                reply_markup=new_order_kb(payload.external_id)
            )
            logger.info(f"[API] ✅ Telegram сообщение успешно отправлено курьеру {courier['tg_chat_id']}")
        except Exception as e:
            logger.error(f"[API] ❌ Ошибка отправки Telegram сообщения курьеру {courier['tg_chat_id']}: {e}", exc_info=True)
            pass
    else:
        logger.info(f"[API] ⏸️ Курьер {courier['tg_chat_id']} не на смене, уведомление пропущено")

    logger.info(f"[API] ✅ Создание заказа завершено: external_id={payload.external_id}, order_id={order_doc['_id']}")
    return JSONResponse({"ok": True, "order_id": str(order_doc["_id"]), "external_id": payload.external_id})

@app.patch("/api/orders/{external_id}")
async def update_order(external_id: str, payload: UpdateOrder):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[API] 📝 Обновление заказа: external_id={external_id}")
    db = await get_db()
    
    logger.debug(f"[API] 🔍 Поиск заказа по external_id={external_id}")
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    if not order:
        logger.warning(f"[API] ⚠️ Заказ не найден: external_id={external_id}")
        raise HTTPException(status_code=404, detail="Order not found")
    logger.debug(f"[API] ✅ Заказ найден: _id={order.get('_id')}")
    
    update_data = {"updated_at": utcnow_iso()}
    if payload.payment_status is not None:
        update_data["payment_status"] = payload.payment_status
    if payload.is_cash_payment is not None:
        update_data["is_cash_payment"] = payload.is_cash_payment
    if payload.delivery_time is not None:
        update_data["delivery_time"] = payload.delivery_time
    if payload.priority is not None:
        update_data["priority"] = payload.priority
    if payload.address is not None:
        update_data["address"] = payload.address
    if payload.map_url is not None:
        update_data["map_url"] = payload.map_url
    if payload.notes is not None:
        update_data["notes"] = payload.notes
    
    logger.debug(f"[API] 💾 Обновление данных заказа: {update_data}")
    await db.couriers_deliveries.update_one({"external_id": external_id}, {"$set": update_data})
    logger.info(f"[API] ✅ Заказ {external_id} обновлен: {update_data}")
    
    return JSONResponse({"ok": True, "external_id": external_id})

@app.get("/api/location/route/{key}")
async def route_redirect(key: str):
    """
    Редирект на Google Maps с маршрутом курьера за смену.
    Проверяет ключ в Redis, получает актуальные данные и редиректит на карту с маршрутом.
    
    Теперь использует локации за последние 72 часа для маршрута,
    но последняя точка должна быть не старше 24 часов.
    """
    import logging
    from datetime import datetime, timezone, timedelta
    from db.redis_client import get_redis
    
    logger = logging.getLogger(__name__)
    
    # Логируем входящий запрос для отладки
    logger.info(f"[API] 🔗 Запрос на редирект маршрута: key={key}")
    
    # Получаем данные редиректа (БЕЗ обновления TTL - чтобы ключ истекал через 24 часа)
    redis = get_redis()
    data_str = await redis.get(f"route:redirect:{key}")
    
    if not data_str:
        # Если ключ не найден или истек
        logger.warning(f"[API] ⚠️ Ключ редиректа маршрута не найден или истек: key={key}")
        raise HTTPException(status_code=404, detail="Link expired or invalid")
    
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in redirect data for key: {key}")
        raise HTTPException(status_code=500, detail="Invalid redirect data")
    
    chat_id = data.get("chat_id")
    shift_id = data.get("shift_id")
    time_72h_ago_str = data.get("time_72h_ago")
    
    if not shift_id:
        logger.error(f"Shift ID not found in redirect data: {data}")
        raise HTTPException(status_code=500, detail="Invalid redirect data")
    
    db = await get_db()
    now = datetime.now(timezone.utc)
    time_72h_ago = datetime.fromisoformat(time_72h_ago_str.replace('Z', '+00:00')) if time_72h_ago_str else now - timedelta(hours=72)
    time_24h_ago = now - timedelta(hours=24)
    
    # Получаем все локации за последние 72 часа, отсортированные по timestamp
    locations = await db.locations.find(
        {
            "chat_id": chat_id,
            "timestamp_ns": {"$gte": int(time_72h_ago.timestamp() * 1e9)}
        }
    ).sort("timestamp_ns", 1).to_list(10000)  # Сортируем от меньшего к большему
    
    if not locations:
        logger.warning(f"[API] ⚠️ Локации не найдены для курьера {chat_id} за последние 72 часа")
        raise HTTPException(status_code=404, detail="No locations found")
    logger.info(f"[API] 📍 Найдено {len(locations)} локаций для курьера {chat_id}")
    
    # Проверяем последнюю локацию - она должна быть не старше 24 часов
    last_location = locations[-1]
    last_location_time = datetime.fromtimestamp(last_location.get("timestamp_ns", 0) / 1e9, tz=timezone.utc)
    
    if last_location_time < time_24h_ago:
        # Если последняя локация старше 24 часов, ищем последнюю локацию за 24 часа
        recent_location = await db.locations.find_one(
            {
                "chat_id": chat_id,
                "timestamp_ns": {"$gte": int(time_24h_ago.timestamp() * 1e9)}
            },
            sort=[("timestamp_ns", -1)]
        )
        
        if recent_location:
            # Используем последнюю локацию за 24 часа как финальную точку
            locations = [loc for loc in locations if loc.get("timestamp_ns") <= recent_location.get("timestamp_ns")]
            locations.append(recent_location)
        else:
            # Если нет локаций за 24 часа, используем последнюю доступную
            logger.warning(f"No locations found for courier {chat_id} in last 24 hours, using last available")
    
    if len(locations) < 2:
        # Если только одна точка, просто показываем её
        loc = locations[0]
        maps_url = f"https://maps.google.com/?q={loc['lat']},{loc['lon']}"
        logger.debug(f"Redirecting route key {key} to Google Maps (single point): {loc['lat']},{loc['lon']}")
        return RedirectResponse(url=maps_url, status_code=302)
    
    # Формируем waypoints
    waypoints = []
    for loc in locations:
        lat = loc.get("lat")
        lon = loc.get("lon")
        if lat is not None and lon is not None:
            # Валидация координат
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                waypoints.append(f"{lat},{lon}")
    
    if len(waypoints) < 2:
        # Если после валидации осталось меньше 2 точек
        loc = locations[0]
        maps_url = f"https://maps.google.com/?q={loc['lat']},{loc['lon']}"
        logger.debug(f"Redirecting route key {key} to Google Maps (single point after validation): {loc['lat']},{loc['lon']}")
        return RedirectResponse(url=maps_url, status_code=302)
    
    # Создаем URL с маршрутом
    waypoints_str = "/".join(waypoints)
    maps_url = f"https://www.google.com/maps/dir/{waypoints_str}"
    
    logger.info(f"[API] ✅ Редирект маршрута: key={key}, {len(waypoints)} точек, курьер {chat_id}")
    
    # Редиректим на Google Maps
    return RedirectResponse(url=maps_url, status_code=302)

@app.get("/api/location/{key}")
async def location_redirect(key: str, lang: str = None):
    """
    Редирект на Google Maps с координатами курьера.
    Проверяет ключ в Redis, обновляет координаты из актуального источника и редиректит на карту.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Логируем входящий запрос для отладки
    logger.info(f"[API] 📍 Запрос на редирект локации: key={key}, lang={lang}")
    
    # Получаем данные редиректа (БЕЗ обновления TTL - чтобы ключ истекал через 24 часа)
    redis = get_redis()
    data_str = await redis.get(f"location:redirect:{key}")
    
    if not data_str:
        # Если ключ не найден или истек - игнорируем запрос
        logger.warning(f"[API] ⚠️ Ключ редиректа локации не найден или истек: key={key}")
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
    
    logger.info(f"[API] ✅ Редирект локации: key={key}, координаты {lat},{lon}")
    
    # Редиректим на Google Maps
    return RedirectResponse(url=maps_url, status_code=302)
