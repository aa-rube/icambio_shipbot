import uvicorn
import json
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Header, Query
from fastapi.responses import JSONResponse, RedirectResponse
from aiogram import Bot
from db.mongo import get_db
from db.redis_client import get_redis
from db.models import (
    IncomingOrder, UpdateOrder, utcnow_iso, get_status_history_update,
    CouriersOnShiftResponse, CourierOnShift, CourierOrdersStats,
    CourierLocationResponse, LocationData,
    CourierRouteResponse, RouteData, RouteTimeRange,
    ActiveOrdersResponse, PaginationInfo,
    AssignCourierRequest, CloseShiftRequest,
    OrderCompleteResponse, OrderDeleteResponse, OrderAssignResponse, CloseShiftResponse
)
from keyboards.orders_kb import new_order_kb, in_transit_kb
from utils.logger import setup_logging
from utils.order_format import format_order_text
from utils.notifications import notify_manager
from utils.test_orders import is_test_order
from handlers.admin import (
    is_super_admin, get_courier_statistics, format_shift_time,
    get_courier_location, get_courier_route
)
from utils.webhooks import send_webhook, prepare_order_data
from config import BOT_TOKEN, API_HOST, API_PORT, TIMEZONE

app = FastAPI(title="Courier Local API")
bot = Bot(BOT_TOKEN)

def get_client_ip(request: Request) -> Optional[str]:
    """
    Получает IP адрес клиента из запроса.
    Проверяет заголовки X-Forwarded-For, X-Real-IP, затем request.client.host.
    Возвращает None для локальных адресов (127.0.0.1, ::1, localhost).
    """
    # Проверяем заголовки прокси
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For может содержать несколько IP через запятую
        ip = forwarded_for.split(",")[0].strip()
        if ip and not _is_local_ip(ip):
            return ip
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        ip = real_ip.strip()
        if ip and not _is_local_ip(ip):
            return ip
    
    # Используем IP из request.client
    if request.client:
        ip = request.client.host
        if ip and not _is_local_ip(ip):
            return ip
    
    return None

def _is_local_ip(ip: str) -> bool:
    """Проверяет, является ли IP локальным адресом"""
    if not ip:
        return True
    ip = ip.strip().lower()
    local_ips = ["127.0.0.1", "::1", "localhost", "0.0.0.0"]
    if ip in local_ips:
        return True
    # Проверяем IPv4 локальные адреса (127.x.x.x)
    if ip.startswith("127."):
        return True
    # Проверяем IPv6 локальные адреса (::1, ::ffff:127.0.0.1 и т.д.)
    if ip.startswith("::"):
        return True
    return False

@app.on_event("startup")
async def on_startup():
    # Инициализация уже выполняется в bot.py, здесь только логирование
    setup_logging()

# --- Admin API Authentication ---

async def verify_admin(x_admin_user_id: int = Header(..., alias="X-Admin-User-ID")) -> int:
    """
    Проверяет права администратора через заголовок X-Admin-User-ID.
    Вызывает HTTPException(403) если пользователь не является супер-админом.
    Используется как dependency в FastAPI endpoints.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not await is_super_admin(x_admin_user_id):
        logger.warning(f"[API] ⚠️ Доступ запрещен для пользователя {x_admin_user_id}")
        raise HTTPException(status_code=403, detail="Access denied. Super admin rights required.")
    
    return x_admin_user_id

@app.post("/api/orders")
async def create_order(payload: IncomingOrder, request: Request):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 📥 Входящий запрос на создание заказа: external_id={payload.external_id}, courier_tg_chat_id={payload.courier_tg_chat_id} (type: {type(payload.courier_tg_chat_id).__name__})")
    logger.debug(f"[API] 📋 Данные заказа: payment_status={payload.payment_status}, priority={payload.priority}, address={payload.address[:50]}...")
    
    # Получаем IP адрес клиента
    client_ip = get_client_ip(request)
    if client_ip:
        logger.info(f"[API] 🌐 IP адрес клиента: {client_ip}")
    else:
        logger.debug(f"[API] 🌐 Локальный запрос, IP не сохраняется")
    
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

    # Инициализируем историю статусов
    current_time = utcnow_iso()
    status_history = {
        "waiting": current_time
    }
    # Добавляем начальный статус оплаты
    payment_status_key = "un_paid" if payload.payment_status == "NOT_PAID" else "paid"
    status_history[payment_status_key] = current_time
    
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
        "created_at": current_time,
        "updated_at": current_time,
        "status_history": status_history,
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
    
    # Сохраняем IP адрес клиента, если он не локальный
    if client_ip:
        order_doc["client_ip"] = client_ip
    
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

    # Уведомление менеджеру о назначении заказа на курьера (только для реальных заказов)
    is_test = is_test_order(payload.external_id)
    if not is_test:
        try:
            await notify_manager(bot, courier, f"📦 Заказ {payload.external_id} назначен на курьера {courier.get('name', 'Неизвестный')}")
            logger.info(f"[API] ✅ Менеджер уведомлен о назначении заказа {payload.external_id} на курьера {courier.get('name')}")
        except Exception as e:
            logger.error(f"[API] ❌ Ошибка уведомления менеджера о назначении заказа: {e}", exc_info=True)
    else:
        logger.info(f"[API] 🧪 Тестовый заказ {payload.external_id} - уведомление менеджеру не отправляется")

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
    
    # Если обновляется payment_status, добавляем запись в историю
    if payload.payment_status is not None:
        update_data["payment_status"] = payload.payment_status
        status_history_update = get_status_history_update(order, new_payment_status=payload.payment_status)
        update_data.update(status_history_update)
    
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
    from datetime import datetime, timedelta
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
    now = datetime.now(TIMEZONE)
    if time_72h_ago_str:
        if time_72h_ago_str.endswith('Z'):
            time_72h_ago = datetime.fromisoformat(time_72h_ago_str.replace('Z', '+00:00'))
        else:
            time_72h_ago = datetime.fromisoformat(time_72h_ago_str)
        if time_72h_ago.tzinfo is None:
            time_72h_ago = time_72h_ago.replace(tzinfo=TIMEZONE)
        elif time_72h_ago.tzinfo != TIMEZONE:
            time_72h_ago = time_72h_ago.astimezone(TIMEZONE)
    else:
        time_72h_ago = now - timedelta(hours=72)
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
    last_location_time = datetime.fromtimestamp(last_location.get("timestamp_ns", 0) / 1e9, tz=TIMEZONE)
    
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

# --- Admin API Endpoints ---

@app.get("/api/admin/couriers/on-shift", response_model=CouriersOnShiftResponse)
async def get_couriers_on_shift(admin_user_id: int = verify_admin):
    """
    Главный экран - список курьеров на смене.
    Возвращает список всех курьеров с is_on_shift: True с полной информацией.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 🚚 Админ {admin_user_id} запрашивает список курьеров на смене")
    
    db = await get_db()
    from datetime import datetime
    
    # Получаем всех курьеров на смене
    couriers = await db.couriers.find({"is_on_shift": True}).to_list(1000)
    logger.info(f"[API] 📊 Найдено {len(couriers)} курьеров на смене")
    
    result_couriers = []
    
    for courier in couriers:
        chat_id = courier.get("tg_chat_id")
        name = courier.get("name", "Unknown")
        username = courier.get("username")
        
        # Получаем статистику
        stats = await get_courier_statistics(chat_id, db)
        
        # Форматируем время начала смены
        shift_started_at = courier.get("shift_started_at")
        shift_time_readable, shift_time_iso = format_shift_time(shift_started_at)
        
        result_couriers.append(CourierOnShift(
            chat_id=chat_id,
            name=name,
            username=username,
            status=stats["status_text"],
            orders=CourierOrdersStats(
                total_today=stats["total_today"],
                delivered_today=stats["delivered_today"],
                waiting=stats["waiting_orders"]
            ),
            shift_started_at=shift_time_iso,
            shift_started_at_readable=shift_time_readable
        ))
    
    return CouriersOnShiftResponse(couriers=result_couriers)

@app.get("/api/admin/couriers/{chat_id}/location", response_model=CourierLocationResponse)
async def get_courier_location_endpoint(
    chat_id: int,
    admin_user_id: int = verify_admin
):
    """
    Текущее местоположение курьера.
    Возвращает последнюю известную локацию курьера с ссылкой на Google Maps.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 📍 Админ {admin_user_id} запрашивает локацию курьера {chat_id}")
    
    location_data = await get_courier_location(chat_id)
    
    if not location_data:
        raise HTTPException(status_code=404, detail="Location not found")
    
    maps_url = f"https://maps.google.com/?q={location_data['lat']},{location_data['lon']}"
    
    return CourierLocationResponse(
        chat_id=chat_id,
        location=LocationData(
            lat=location_data["lat"],
            lon=location_data["lon"],
            maps_url=maps_url,
            timestamp=location_data.get("timestamp")
        )
    )

@app.get("/api/admin/couriers/{chat_id}/route", response_model=CourierRouteResponse)
async def get_courier_route_endpoint(
    chat_id: int,
    admin_user_id: int = verify_admin
):
    """
    Маршрут курьера за последние 72 часа.
    Возвращает маршрут курьера с ссылкой на Google Maps (до 50 точек).
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 🗺️ Админ {admin_user_id} запрашивает маршрут курьера {chat_id}")
    
    route_data = await get_courier_route(chat_id)
    
    if not route_data:
        raise HTTPException(status_code=404, detail="Insufficient data for route")
    
    return CourierRouteResponse(
        chat_id=chat_id,
        route=RouteData(
            maps_url=route_data["maps_url"],
            points_count=route_data["points_count"],
            time_range=RouteTimeRange(
                start=route_data["time_range"]["start"],
                end=route_data["time_range"]["end"]
            )
        )
    )

@app.get("/api/admin/couriers/{chat_id}/orders/active", response_model=ActiveOrdersResponse)
async def get_courier_active_orders(
    chat_id: int,
    page: int = Query(0, ge=0),
    per_page: int = Query(10, ge=1, le=100),
    admin_user_id: int = verify_admin
):
    """
    Активные заказы курьера.
    Возвращает список активных заказов (waiting, in_transit) с пагинацией.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 📦 Админ {admin_user_id} запрашивает активные заказы курьера {chat_id} (страница {page})")
    
    db = await get_db()
    
    # Получаем активные заказы курьера
    all_orders = await db.couriers_deliveries.find({
        "courier_tg_chat_id": chat_id,
        "status": {"$in": ["waiting", "in_transit"]}
    }).sort("priority", -1).sort("created_at", 1).to_list(1000)
    
    total = len(all_orders)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    orders = all_orders[start_idx:end_idx]
    
    # Преобразуем ObjectId в строки для JSON
    orders_json = []
    for order in orders:
        order_dict = dict(order)
        if "_id" in order_dict:
            order_dict["_id"] = str(order_dict["_id"])
        if "assigned_to" in order_dict and order_dict["assigned_to"]:
            order_dict["assigned_to"] = str(order_dict["assigned_to"])
        orders_json.append(order_dict)
    
    return ActiveOrdersResponse(
        orders=orders_json,
        pagination=PaginationInfo(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages
        )
    )

@app.get("/api/admin/couriers/{chat_id}")
async def get_courier_details(
    chat_id: int,
    admin_user_id: int = verify_admin
):
    """
    Детальная информация о курьере.
    Возвращает полную информацию о курьере (объединяет данные из нескольких endpoints).
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 👤 Админ {admin_user_id} запрашивает детали курьера {chat_id}")
    
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    
    if not courier:
        raise HTTPException(status_code=404, detail="Courier not found")
    
    # Получаем статистику
    stats = await get_courier_statistics(chat_id, db)
    
    # Форматируем время начала смены
    shift_started_at = courier.get("shift_started_at")
    shift_time_readable, shift_time_iso = format_shift_time(shift_started_at)
    
    # Получаем локацию
    location_data = await get_courier_location(chat_id)
    
    result = {
        "ok": True,
        "chat_id": chat_id,
        "name": courier.get("name", "Unknown"),
        "username": courier.get("username"),
        "is_on_shift": courier.get("is_on_shift", False),
        "status": stats["status_text"],
        "orders": {
            "total_today": stats["total_today"],
            "delivered_today": stats["delivered_today"],
            "waiting": stats["waiting_orders"]
        },
        "shift_started_at": shift_time_iso,
        "shift_started_at_readable": shift_time_readable
    }
    
    if location_data:
        result["location"] = {
            "lat": location_data["lat"],
            "lon": location_data["lon"],
            "maps_url": f"https://maps.google.com/?q={location_data['lat']},{location_data['lon']}",
            "timestamp": location_data.get("timestamp")
        }
    
    return JSONResponse(result)

@app.post("/api/admin/orders/{external_id}/complete", response_model=OrderCompleteResponse)
async def complete_order(
    external_id: str,
    admin_user_id: int = verify_admin
):
    """
    Завершить заказ.
    Завершает заказ (статус -> done), отправляет webhook, уведомляет курьера.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] ✅ Админ {admin_user_id} завершает заказ {external_id}")
    
    db = await get_db()
    
    # Проверяем заказ
    from handlers.orders import validate_order_for_action
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        admin_user_id,
        allow_admin=True
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg or "Cannot complete order")
    
    current_courier_chat_id = order.get("courier_tg_chat_id")
    address = order.get("address", "")
    
    # Обновляем заказ
    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {
            "$set": {
                "status": "done",
                "closed_by_admin_id": admin_user_id,
                "updated_at": utcnow_iso()
            }
        }
    )
    
    # Получаем обновленный заказ для webhook
    updated_order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    # Проверка: если заказ тестовый, не отправляем webhook
    is_test = is_test_order(external_id)
    
    if not is_test:
        order_data = await prepare_order_data(db, updated_order)
        webhook_data = {
            **order_data,
            "timestamp": utcnow_iso()
        }
        await send_webhook("order_completed", webhook_data)
        logger.info(f"[API] 📤 Webhook 'order_completed' отправлен для заказа {external_id}")
    
    # Отправляем сообщение курьеру
    try:
        await bot.send_message(
            current_courier_chat_id,
            f"✅ Заказ {external_id} выполнен\nАдрес: {address}"
        )
    except Exception as e:
        logger.warning(f"[API] ⚠️ Не удалось отправить сообщение курьеру {current_courier_chat_id}: {e}")
    
    return OrderCompleteResponse(external_id=external_id)

@app.delete("/api/admin/orders/{external_id}", response_model=OrderDeleteResponse)
async def delete_order(
    external_id: str,
    admin_user_id: int = verify_admin
):
    """
    Удалить заказ.
    Удаляет заказ из системы, уведомляет курьера.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 🗑️ Админ {admin_user_id} удаляет заказ {external_id}")
    
    db = await get_db()
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    current_courier_chat_id = order.get("courier_tg_chat_id")
    address = order.get("address", "")
    
    # Удаляем заказ
    await db.couriers_deliveries.delete_one({"external_id": external_id})
    
    # Отправляем сообщение курьеру
    try:
        await bot.send_message(
            current_courier_chat_id,
            f"🗑 Заказ {external_id} удален\nАдрес: {address}"
        )
    except Exception as e:
        logger.warning(f"[API] ⚠️ Не удалось отправить сообщение курьеру {current_courier_chat_id}: {e}")
    
    return OrderDeleteResponse(external_id=external_id)

@app.patch("/api/admin/orders/{external_id}/assign", response_model=OrderAssignResponse)
async def assign_courier_to_order(
    external_id: str,
    payload: AssignCourierRequest,
    admin_user_id: int = verify_admin
):
    """
    Назначить курьера на заказ.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 👤 Админ {admin_user_id} назначает курьера {payload.courier_chat_id} для заказа {external_id}")
    
    db = await get_db()
    
    # Проверяем заказ
    from handlers.orders import validate_order_for_action
    is_valid, order, error_msg = await validate_order_for_action(
        external_id,
        admin_user_id,
        allow_admin=True
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg or "Cannot assign courier")
    
    new_courier = await db.couriers.find_one({"tg_chat_id": payload.courier_chat_id})
    if not new_courier:
        raise HTTPException(status_code=404, detail="Courier not found")
    
    old_courier_chat_id = order.get("courier_tg_chat_id")
    address = order.get("address", "")
    
    # Обновляем заказ в БД
    await db.couriers_deliveries.update_one(
        {"external_id": external_id},
        {
            "$set": {
                "courier_tg_chat_id": payload.courier_chat_id,
                "assigned_to": new_courier["_id"],
                "updated_at": utcnow_iso()
            }
        }
    )
    
    # Обновляем курьера заказа в Odoo
    try:
        from utils.odoo import update_order_courier
        await update_order_courier(external_id, str(payload.courier_chat_id))
        logger.info(f"[API] ✅ Курьер заказа обновлен в Odoo")
    except Exception as e:
        logger.warning(f"[API] ⚠️ Не удалось обновить курьера заказа в Odoo: {e}")
    
    # Отправляем сообщение старому курьеру (если он отличается от нового)
    if old_courier_chat_id != payload.courier_chat_id:
        try:
            await bot.send_message(
                old_courier_chat_id,
                f"🔄 Заказ {external_id} переназначен другому курьеру\nАдрес: {address}"
            )
        except Exception as e:
            logger.warning(f"[API] ⚠️ Не удалось отправить сообщение старому курьеру {old_courier_chat_id}: {e}")
    
    # Отправляем сообщение новому курьеру
    try:
        order = await db.couriers_deliveries.find_one({"external_id": external_id})
        text = format_order_text(order)
        kb = new_order_kb(external_id) if order.get("status") == "waiting" else in_transit_kb(external_id, order)
        await bot.send_message(
            payload.courier_chat_id,
            text,
            parse_mode="HTML",
            reply_markup=kb
        )
    except Exception as e:
        logger.warning(f"[API] ⚠️ Не удалось отправить сообщение новому курьеру {payload.courier_chat_id}: {e}")
    
    return OrderAssignResponse(external_id=external_id, courier_chat_id=payload.courier_chat_id)

@app.post("/api/admin/couriers/{chat_id}/close-shift", response_model=CloseShiftResponse)
async def close_courier_shift(
    chat_id: int,
    payload: CloseShiftRequest,
    admin_user_id: int = verify_admin
):
    """
    Закрыть смену курьера.
    Если есть активные заказы и не указан transfer_to_chat_id, возвращает ошибку.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API] 🔴 Админ {admin_user_id} закрывает смену курьера {chat_id}")
    
    db = await get_db()
    redis = get_redis()
    
    courier = await db.couriers.find_one({"tg_chat_id": chat_id})
    if not courier:
        raise HTTPException(status_code=404, detail="Courier not found")
    
    # Проверяем наличие активных заказов
    active_orders = await db.couriers_deliveries.find({
        "courier_tg_chat_id": chat_id,
        "status": {"$in": ["waiting", "in_transit"]}
    }).to_list(100)
    
    if active_orders:
        if not payload.transfer_to_chat_id:
            raise HTTPException(
                status_code=400,
                detail=f"Courier has {len(active_orders)} active orders. Please specify transfer_to_chat_id to transfer orders."
            )
        
        # Передаем заказы новому курьеру
        new_courier = await db.couriers.find_one({"tg_chat_id": payload.transfer_to_chat_id})
        if not new_courier:
            raise HTTPException(status_code=404, detail="Transfer courier not found")
        
        from utils.odoo import update_order_courier
        
        transferred_count = 0
        for order in active_orders:
            external_id = order.get("external_id")
            try:
                await db.couriers_deliveries.update_one(
                    {"external_id": external_id},
                    {
                        "$set": {
                            "courier_tg_chat_id": payload.transfer_to_chat_id,
                            "assigned_to": new_courier["_id"],
                            "updated_at": utcnow_iso()
                        }
                    }
                )
                
                try:
                    await update_order_courier(external_id, str(payload.transfer_to_chat_id))
                except Exception as e:
                    logger.warning(f"[API] ⚠️ Не удалось обновить курьера заказа {external_id} в Odoo: {e}")
                
                transferred_count += 1
            except Exception as e:
                logger.error(f"[API] ❌ Ошибка передачи заказа {external_id}: {e}", exc_info=True)
        
        logger.info(f"[API] ✅ Передано {transferred_count} заказов от курьера {chat_id} курьеру {payload.transfer_to_chat_id}")
        
        # Отправляем сообщение новому курьеру о переданных заказах
        try:
            for order in active_orders:
                try:
                    text = format_order_text(order)
                    kb = new_order_kb(order["external_id"]) if order.get("status") == "waiting" else in_transit_kb(order["external_id"], order)
                    await bot.send_message(
                        payload.transfer_to_chat_id,
                        text,
                        parse_mode="HTML",
                        reply_markup=kb
                    )
                except Exception as e:
                    logger.warning(f"[API] ⚠️ Не удалось отправить сообщение новому курьеру {payload.transfer_to_chat_id} о заказе {order.get('external_id')}: {e}")
        except Exception as e:
            logger.warning(f"[API] ⚠️ Ошибка отправки сообщений новому курьеру: {e}")
    
    # Сохраняем время начала смены для подсчета заказов
    shift_started_at = courier.get("shift_started_at")
    current_shift_id = courier.get("current_shift_id")
    
    # Подсчет заказов за смену
    orders_count = 0
    complete_orders_count = 0
    
    if shift_started_at:
        try:
            orders_count = await db.couriers_deliveries.count_documents({
                "courier_tg_chat_id": chat_id,
                "created_at": {"$gte": shift_started_at}
            })
            complete_orders_count = await db.couriers_deliveries.count_documents({
                "courier_tg_chat_id": chat_id,
                "status": "done",
                "created_at": {"$gte": shift_started_at}
            })
        except Exception as e:
            logger.warning(f"[API] ⚠️ Ошибка подсчета заказов за смену: {e}", exc_info=True)
    
    # Обновляем статус курьера
    await db.couriers.update_one(
        {"_id": courier["_id"]},
        {"$set": {"is_on_shift": False}, "$unset": {"current_shift_id": "", "shift_started_at": ""}}
    )
    
    # Удаляем данные из Redis
    await redis.delete(f"courier:shift:{chat_id}")
    await redis.delete(f"courier:loc:{chat_id}")
    
    # Записываем в историю
    from db.models import Action, ShiftHistory
    await Action.log(db, chat_id, "shift_end")
    await ShiftHistory.log(
        db,
        chat_id,
        "shift_ended",
        shift_id=current_shift_id,
        total_orders=orders_count,
        complete_orders=complete_orders_count,
        shift_started_at=shift_started_at
    )
    
    # Обновление статуса в Odoo
    try:
        from utils.odoo import update_courier_status
        await update_courier_status(str(chat_id), is_online=False)
    except Exception as e:
        logger.warning(f"[API] ⚠️ Не удалось обновить статус курьера в Odoo: {e}")
    
    # Отправляем сообщение курьеру
    try:
        await bot.send_message(
            chat_id,
            "🔴 Ваша смена завершена офис-менеджером.\n\nСпасибо за работу!"
        )
    except Exception as e:
        logger.warning(f"[API] ⚠️ Не удалось отправить сообщение курьеру {chat_id}: {e}")
    
    message = f"Shift closed successfully"
    if active_orders:
        message += f". {len(active_orders)} orders transferred to courier {payload.transfer_to_chat_id}"
    
    logger.info(f"[API] ✅ Смена курьера {chat_id} закрыта админом")
    
    return CloseShiftResponse(chat_id=chat_id, message=message)
