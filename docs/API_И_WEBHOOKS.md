# ShipBot API и Webhooks - Документация

## Содержание
1. [API Endpoints](#api-endpoints)
2. [Webhooks](#webhooks)
3. [Примеры использования на Python](#примеры-использования-на-python)

---

## API Endpoints

### Base URL
```
http://127.0.0.1:5055
```

### 1. Создание заказа

**Endpoint:** `POST /api/orders`

Создает новый заказ и назначает его курьеру. Если курьер на смене, он получит уведомление в Telegram.

#### Обязательные поля:
- `courier_tg_chat_id` (int) - Telegram chat ID курьера
- `external_id` (str) - уникальный ID заказа из внешней системы
- `client_name` (str) - имя клиента
- `client_phone` (str) - телефон клиента
- `address` (str) - адрес доставки

#### Опциональные поля:
- `client_chat_id` (int) - Telegram chat ID клиента
- `client_tg` (str) - Telegram username клиента (например, "@username")
- `contact_url` (str) - deep link на клиента в Telegram (например, "tg://user?id=123456789")
- `map_url` (str) - ссылка на карту с координатами
- `notes` (str) - примечания к заказу
- `brand` (str) - бренд/магазин
- `source` (str) - источник заказа
- `payment_status` (str) - статус оплаты: `NOT_PAID`, `PAID`, `REFUND` (по умолчанию: `NOT_PAID`)
- `is_cash_payment` (bool) - признак оплаты заказа наличными (по умолчанию: `False`)
- `delivery_time` (str) - время доставки (например, "14:00")
- `priority` (int) - приоритет заказа (по умолчанию: 0)

#### Пример запроса на Python:

```python
import requests

url = "http://127.0.0.1:5055/api/orders"

# Минимальный заказ
data_minimal = {
    "courier_tg_chat_id": 7960182194,
    "external_id": "ORDER123",
    "client_name": "Иван Иванов",
    "client_phone": "+79991234567",
    "address": "Москва, ул. Ленина, д. 10, кв. 5"
}

response = requests.post(url, json=data_minimal)
print(response.json())
# {"ok": true, "order_id": "507f1f77bcf86cd799439011", "external_id": "ORDER123"}

# Полный заказ со всеми полями
data_full = {
    "courier_tg_chat_id": 7960182194,
    "external_id": "ORDER124",
    "client_name": "Петр Петров",
    "client_phone": "+79991234567",
    "client_chat_id": 123456789,
    "client_tg": "@petrov",
    "contact_url": "tg://user?id=123456789",
    "address": "Москва, ул. Тверская, д. 1, кв. 10",
    "map_url": "https://maps.google.com/?q=55.7558,37.6173",
    "notes": "Позвонить за 10 минут до доставки",
    "brand": "SuperShop",
    "source": "Website",
    "payment_status": "NOT_PAID",
    "is_cash_payment": True,
    "delivery_time": "15:30",
    "priority": 5
}

response = requests.post(url, json=data_full)
print(response.json())
```

#### Ответ при успехе:
```json
{
    "ok": true,
    "order_id": "507f1f77bcf86cd799439011",
    "external_id": "ORDER123"
}
```

#### Ошибки:
- **404 Not Found**: Курьер не найден
- **409 Conflict**: Заказ с таким `external_id` уже существует

---

### 2. Обновление заказа

**Endpoint:** `PATCH /api/orders/{external_id}`

Обновляет существующий заказ. Все поля опциональны.

#### Пример запроса на Python:

```python
import requests

external_id = "ORDER123"
url = f"http://127.0.0.1:5055/api/orders/{external_id}"

# Обновить статус оплаты
data = {
    "payment_status": "PAID"
}
response = requests.patch(url, json=data)
print(response.json())
# {"ok": true, "external_id": "ORDER123"}

# Обновить приоритет и время доставки
data = {
    "priority": 5,
    "delivery_time": "18:00"
}
response = requests.patch(url, json=data)

# Обновить адрес
data = {
    "address": "Москва, ул. Арбат, д. 10"
}
response = requests.patch(url, json=data)

# Обновить примечания
data = {
    "notes": "Новые инструкции по доставке"
}
response = requests.patch(url, json=data)

# Установить возврат
data = {
    "payment_status": "REFUND"
}
response = requests.patch(url, json=data)

# Обновить несколько полей одновременно
data = {
    "payment_status": "PAID",
    "priority": 10,
    "delivery_time": "18:00",
    "is_cash_payment": True
}
response = requests.patch(url, json=data)
```

#### Ответ при успехе:
```json
{
    "ok": true,
    "external_id": "ORDER123"
}
```

#### Ошибки:
- **404 Not Found**: Заказ не найден

---

### 3. Редирект на локацию курьера

**Endpoint:** `GET /api/location/{key}`

Редиректит на Google Maps с текущей локацией курьера. Ключ генерируется системой и действителен 24 часа.

#### Пример использования на Python:

```python
import requests

key = "abc123def456"
url = f"http://127.0.0.1:5055/api/location/{key}"

# Редирект на Google Maps
response = requests.get(url, allow_redirects=False)
if response.status_code == 302:
    maps_url = response.headers['Location']
    print(f"Ссылка на карту: {maps_url}")
    # Открыть в браузере: https://maps.google.com/?q=55.7558,37.6173
```

---

### 4. Редирект на маршрут курьера

**Endpoint:** `GET /api/location/route/{key}`

Редиректит на Google Maps с маршрутом курьера за смену. Показывает все локации за последние 72 часа. Ключ действителен 24 часа.

#### Пример использования на Python:

```python
import requests

key = "xyz789abc123"
url = f"http://127.0.0.1:5055/api/location/route/{key}"

# Редирект на Google Maps с маршрутом
response = requests.get(url, allow_redirects=False)
if response.status_code == 302:
    maps_url = response.headers['Location']
    print(f"Ссылка на маршрут: {maps_url}")
    # Открыть в браузере: https://www.google.com/maps/dir/55.7558,37.6173/55.7600,37.6200/...
```

---

## Webhooks

ShipBot отправляет webhook-уведомления на настроенный URL при различных событиях.

### Настройка

Установите переменную окружения `WEBHOOK_URL` в файле `.env`:

```env
WEBHOOK_URL=https://your-server.com/webhook
```

### Формат запроса

Все webhook-запросы отправляются методом `POST` с JSON-телом:

```json
{
    "event_type": "order_accepted",
    "timestamp": "2025-01-15T10:30:00Z",
    "data": {
        // Данные события
    }
}
```

### Типы событий

1. **shift_start** - Курьер начал смену
2. **shift_end** - Курьер завершил смену
3. **order_accepted** - Курьер принял заказ (статус изменен на "в пути")
4. **order_completed** - Заказ выполнен (курьер отправил фото)

---

### 1. shift_start - Начало смены

Отправляется, когда курьер начинает смену и отправляет live location.

#### Пример обработчика на Python:

```python
from flask import Flask, request, jsonify
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
    event_type = data.get('event_type')
    timestamp = data.get('timestamp')
    event_data = data.get('data', {})
    
    if event_type == 'shift_start':
        courier_id = event_data.get('courier_id')
        courier_name = event_data.get('name')
        tg_chat_id = event_data.get('tg_chat_id')
        shift_id = event_data.get('shift_id')
        location = event_data.get('location')  # {"lat": 55.7558, "lon": 37.6173}
        is_on_shift = event_data.get('is_on_shift')
        active_orders_count = event_data.get('active_orders_count', 0)
        
        logging.info(f"Курьер {courier_name} (ID: {courier_id}) начал смену")
        logging.info(f"Shift ID: {shift_id}, Активных заказов: {active_orders_count}")
        
        # Ваша логика обработки
        
        return jsonify({"status": "ok"}), 200
    
    return jsonify({"status": "unknown_event"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

#### Структура данных события:

```json
{
    "event_type": "shift_start",
    "timestamp": "2025-01-15T10:30:00Z",
    "data": {
        "courier_id": "507f1f77bcf86cd799439011",
        "name": "Иван Иванов",
        "username": "ivan_ivanov",
        "tg_chat_id": 7960182194,
        "is_on_shift": true,
        "shift_started_at": "2025-01-15T10:30:00Z",
        "current_shift_id": "shift_1234567890",
        "last_location": {
            "lat": 55.7558,
            "lon": 37.6173
        },
        "active_orders_count": 2,
        "location": {
            "lat": 55.7558,
            "lon": 37.6173
        },
        "shift_id": "shift_1234567890"
    }
}
```

---

### 2. shift_end - Окончание смены

Отправляется, когда курьер завершает смену.

#### Пример обработчика на Python:

```python
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    event_type = data.get('event_type')
    event_data = data.get('data', {})
    
    if event_type == 'shift_end':
        courier_id = event_data.get('courier_id')
        courier_name = event_data.get('name')
        tg_chat_id = event_data.get('tg_chat_id')
        is_on_shift = event_data.get('is_on_shift')  # false
        active_orders_count = event_data.get('active_orders_count', 0)
        
        logging.info(f"Курьер {courier_name} (ID: {courier_id}) завершил смену")
        logging.info(f"Активных заказов: {active_orders_count}")
        
        # Ваша логика обработки
        
        return jsonify({"status": "ok"}), 200
    
    return jsonify({"status": "unknown_event"}), 200
```

#### Структура данных события:

```json
{
    "event_type": "shift_end",
    "timestamp": "2025-01-15T18:30:00Z",
    "data": {
        "courier_id": "507f1f77bcf86cd799439011",
        "name": "Иван Иванов",
        "username": "ivan_ivanov",
        "tg_chat_id": 7960182194,
        "is_on_shift": false,
        "shift_started_at": null,
        "current_shift_id": null,
        "last_location": {
            "lat": 55.7558,
            "lon": 37.6173
        },
        "active_orders_count": 0
    }
}
```

---

### 3. order_accepted - Заказ принят

Отправляется, когда курьер принимает заказ (нажимает кнопку "В путь").

#### Пример обработчика на Python:

```python
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    event_type = data.get('event_type')
    event_data = data.get('data', {})
    
    if event_type == 'order_accepted':
        external_id = event_data.get('external_id')
        status = event_data.get('status')  # "stage_delivery_10" (в пути)
        payment_status = event_data.get('payment_status')  # "NOT_PAID", "PAID", "REFUND"
        is_cash_payment = event_data.get('is_cash_payment', False)
        priority = event_data.get('priority', 0)
        address = event_data.get('address')
        
        # Данные клиента
        client = event_data.get('client', {})
        client_name = client.get('name')
        client_phone = client.get('phone')
        
        # Данные курьера
        courier = event_data.get('courier', {})
        courier_name = courier.get('name')
        
        logging.info(f"Заказ {external_id} принят курьером {courier_name}")
        logging.info(f"Статус: {status}, Адрес: {address}")
        
        # Ваша логика обработки (например, обновление статуса в CRM)
        
        return jsonify({"status": "ok"}), 200
    
    return jsonify({"status": "unknown_event"}), 200
```

#### Структура данных события:

```json
{
    "event_type": "order_accepted",
    "timestamp": "2025-01-15T11:00:00Z",
    "data": {
        "external_id": "ORDER123",
        "status": "stage_delivery_10",
        "payment_status": "NOT_PAID",
        "is_cash_payment": true,
        "delivery_time": "15:30",
        "priority": 5,
        "brand": "SuperShop",
        "source": "Website",
        "created_at": "2025-01-15T10:00:00Z",
        "updated_at": "2025-01-15T11:00:00Z",
        "address": "Москва, ул. Тверская, д. 1, кв. 10",
        "map_url": "https://maps.google.com/?q=55.7558,37.6173",
        "notes": "Позвонить за 10 минут до доставки",
        "client": {
            "name": "Петр Петров",
            "phone": "+79991234567",
            "chat_id": 123456789,
            "tg": "@petrov",
            "contact_url": "tg://user?id=123456789"
        },
        "courier": {
            "courier_id": "507f1f77bcf86cd799439011",
            "name": "Иван Иванов",
            "username": "ivan_ivanov",
            "tg_chat_id": 7960182194,
            "is_on_shift": true
        }
    }
}
```

#### Маппинг статусов:

Внутренние статусы заказов преобразуются для webhook:
- `waiting` → `waiting` (ожидает принятия)
- `in_transit` → `stage_delivery_10` (в пути)
- `done` → `stage_delivery_11` (доставлен)
- `cancelled` → `cancelled` (отменен)

---

### 4. order_completed - Заказ выполнен

Отправляется, когда курьер отправляет фото завершения заказа.

#### Пример обработчика на Python:

```python
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    event_type = data.get('event_type')
    event_data = data.get('data', {})
    
    if event_type == 'order_completed':
        external_id = event_data.get('external_id')
        status = event_data.get('status')  # "stage_delivery_11" (доставлен)
        payment_status = event_data.get('payment_status')
        is_cash_payment = event_data.get('is_cash_payment', False)
        
        # Данные клиента
        client = event_data.get('client', {})
        client_name = client.get('name')
        
        # Данные курьера
        courier = event_data.get('courier', {})
        courier_name = courier.get('name')
        
        logging.info(f"Заказ {external_id} выполнен курьером {courier_name}")
        logging.info(f"Статус: {status}, Оплата: {payment_status}")
        
        # Ваша логика обработки (например, закрытие заказа в CRM)
        
        return jsonify({"status": "ok"}), 200
    
    return jsonify({"status": "unknown_event"}), 200
```

#### Структура данных события:

```json
{
    "event_type": "order_completed",
    "timestamp": "2025-01-15T12:30:00Z",
    "data": {
        "external_id": "ORDER123",
        "status": "stage_delivery_11",
        "payment_status": "PAID",
        "is_cash_payment": true,
        "delivery_time": "15:30",
        "priority": 5,
        "brand": "SuperShop",
        "source": "Website",
        "created_at": "2025-01-15T10:00:00Z",
        "updated_at": "2025-01-15T12:30:00Z",
        "address": "Москва, ул. Тверская, д. 1, кв. 10",
        "map_url": "https://maps.google.com/?q=55.7558,37.6173",
        "notes": "Позвонить за 10 минут до доставки",
        "client": {
            "name": "Петр Петров",
            "phone": "+79991234567",
            "chat_id": 123456789,
            "tg": "@petrov",
            "contact_url": "tg://user?id=123456789"
        },
        "courier": {
            "courier_id": "507f1f77bcf86cd799439011",
            "name": "Иван Иванов",
            "username": "ivan_ivanov",
            "tg_chat_id": 7960182194,
            "is_on_shift": true
        }
    }
}
```

---

## Примеры использования на Python

### Полный пример клиента API

```python
import requests
from typing import Optional, Dict, Any

class ShipBotAPI:
    """Клиент для работы с ShipBot API"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:5055"):
        self.base_url = base_url
    
    def create_order(
        self,
        courier_tg_chat_id: int,
        external_id: str,
        client_name: str,
        client_phone: str,
        address: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Создает новый заказ
        
        Args:
            courier_tg_chat_id: Telegram chat ID курьера
            external_id: Уникальный ID заказа
            client_name: Имя клиента
            client_phone: Телефон клиента
            address: Адрес доставки
            **kwargs: Опциональные поля (client_chat_id, client_tg, contact_url,
                      map_url, notes, brand, source, payment_status, is_cash_payment,
                      delivery_time, priority)
        
        Returns:
            Dict с результатом: {"ok": True, "order_id": "...", "external_id": "..."}
        """
        url = f"{self.base_url}/api/orders"
        data = {
            "courier_tg_chat_id": courier_tg_chat_id,
            "external_id": external_id,
            "client_name": client_name,
            "client_phone": client_phone,
            "address": address,
            **kwargs
        }
        response = requests.post(url, json=data)
        response.raise_for_status()
        return response.json()
    
    def update_order(
        self,
        external_id: str,
        payment_status: Optional[str] = None,
        is_cash_payment: Optional[bool] = None,
        delivery_time: Optional[str] = None,
        priority: Optional[int] = None,
        address: Optional[str] = None,
        map_url: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Обновляет существующий заказ
        
        Args:
            external_id: ID заказа для обновления
            payment_status: Статус оплаты (NOT_PAID, PAID, REFUND)
            is_cash_payment: Признак оплаты наличными
            delivery_time: Время доставки
            priority: Приоритет заказа
            address: Адрес доставки
            map_url: Ссылка на карту
            notes: Примечания
        
        Returns:
            Dict с результатом: {"ok": True, "external_id": "..."}
        """
        url = f"{self.base_url}/api/orders/{external_id}"
        data = {}
        if payment_status is not None:
            data["payment_status"] = payment_status
        if is_cash_payment is not None:
            data["is_cash_payment"] = is_cash_payment
        if delivery_time is not None:
            data["delivery_time"] = delivery_time
        if priority is not None:
            data["priority"] = priority
        if address is not None:
            data["address"] = address
        if map_url is not None:
            data["map_url"] = map_url
        if notes is not None:
            data["notes"] = notes
        
        response = requests.patch(url, json=data)
        response.raise_for_status()
        return response.json()

# Использование
api = ShipBotAPI()

# Создать заказ
result = api.create_order(
    courier_tg_chat_id=7960182194,
    external_id="ORDER125",
    client_name="Алексей Смирнов",
    client_phone="+79991234567",
    address="Москва, ул. Ленина, д. 20",
    brand="MegaStore",
    priority=8,
    delivery_time="16:00",
    payment_status="NOT_PAID",
    is_cash_payment=True
)
print(f"Заказ создан: {result}")

# Обновить статус оплаты
result = api.update_order("ORDER125", payment_status="PAID")
print(f"Заказ обновлен: {result}")
```

---

### Полный пример обработчика Webhooks

```python
from flask import Flask, request, jsonify
import logging
from typing import Dict, Any

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebhookHandler:
    """Обработчик webhook-событий от ShipBot"""
    
    @staticmethod
    def handle_shift_start(data: Dict[str, Any]) -> None:
        """Обработка события начала смены"""
        courier_name = data.get('name')
        courier_id = data.get('courier_id')
        shift_id = data.get('shift_id')
        location = data.get('location', {})
        
        logger.info(f"🟢 Курьер {courier_name} начал смену (ID: {shift_id})")
        logger.info(f"📍 Локация: {location.get('lat')}, {location.get('lon')}")
        
        # Ваша логика: обновление статуса в CRM, отправка уведомлений и т.д.
    
    @staticmethod
    def handle_shift_end(data: Dict[str, Any]) -> None:
        """Обработка события окончания смены"""
        courier_name = data.get('name')
        courier_id = data.get('courier_id')
        active_orders = data.get('active_orders_count', 0)
        
        logger.info(f"🔴 Курьер {courier_name} завершил смену")
        logger.info(f"📦 Активных заказов: {active_orders}")
        
        # Ваша логика: закрытие смены, расчет статистики и т.д.
    
    @staticmethod
    def handle_order_accepted(data: Dict[str, Any]) -> None:
        """Обработка события принятия заказа"""
        external_id = data.get('external_id')
        status = data.get('status')  # "stage_delivery_10"
        courier = data.get('courier', {})
        client = data.get('client', {})
        
        logger.info(f"✅ Заказ {external_id} принят курьером {courier.get('name')}")
        logger.info(f"📦 Статус: {status}, Клиент: {client.get('name')}")
        
        # Ваша логика: обновление статуса заказа в CRM
        # Например, обновление статуса на "В доставке"
    
    @staticmethod
    def handle_order_completed(data: Dict[str, Any]) -> None:
        """Обработка события завершения заказа"""
        external_id = data.get('external_id')
        status = data.get('status')  # "stage_delivery_11"
        payment_status = data.get('payment_status')
        courier = data.get('courier', {})
        client = data.get('client', {})
        
        logger.info(f"🎉 Заказ {external_id} выполнен курьером {courier.get('name')}")
        logger.info(f"✅ Статус: {status}, Оплата: {payment_status}")
        
        # Ваша логика: закрытие заказа в CRM, отправка уведомлений клиенту и т.д.

@app.route('/webhook', methods=['POST'])
def webhook():
    """Главный endpoint для приема webhook-событий"""
    try:
        payload = request.json
        
        if not payload:
            logger.warning("Получен пустой payload")
            return jsonify({"status": "error", "message": "Empty payload"}), 400
        
        event_type = payload.get('event_type')
        timestamp = payload.get('timestamp')
        event_data = payload.get('data', {})
        
        logger.info(f"📥 Получен webhook: {event_type} в {timestamp}")
        
        # Обработка событий
        if event_type == 'shift_start':
            WebhookHandler.handle_shift_start(event_data)
        elif event_type == 'shift_end':
            WebhookHandler.handle_shift_end(event_data)
        elif event_type == 'order_accepted':
            WebhookHandler.handle_order_accepted(event_data)
        elif event_type == 'order_completed':
            WebhookHandler.handle_order_completed(event_data)
        else:
            logger.warning(f"Неизвестный тип события: {event_type}")
        
        return jsonify({"status": "ok"}), 200
    
    except Exception as e:
        logger.error(f"Ошибка обработки webhook: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    # Запуск сервера на порту 5000
    app.run(host='0.0.0.0', port=5000, debug=True)
```

---

### Пример с использованием aiohttp (асинхронный)

```python
import aiohttp
import asyncio
from aiohttp import web
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def webhook_handler(request):
    """Асинхронный обработчик webhook"""
    try:
        payload = await request.json()
        
        event_type = payload.get('event_type')
        event_data = payload.get('data', {})
        
        logger.info(f"📥 Получен webhook: {event_type}")
        
        if event_type == 'order_completed':
            external_id = event_data.get('external_id')
            status = event_data.get('status')
            logger.info(f"✅ Заказ {external_id} выполнен, статус: {status}")
        
        return web.json_response({"status": "ok"})
    
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return web.json_response({"status": "error"}, status=500)

async def create_order_async(session, url, data):
    """Асинхронное создание заказа"""
    async with session.post(url, json=data) as response:
        return await response.json()

async def main():
    # Пример создания заказа асинхронно
    async with aiohttp.ClientSession() as session:
        url = "http://127.0.0.1:5055/api/orders"
        data = {
            "courier_tg_chat_id": 7960182194,
            "external_id": "ORDER126",
            "client_name": "Тест Тестов",
            "client_phone": "+79991234567",
            "address": "Москва, ул. Тестовая, д. 1"
        }
        result = await create_order_async(session, url, data)
        print(f"Результат: {result}")
    
    # Запуск webhook сервера
    app = web.Application()
    app.router.add_post('/webhook', webhook_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    await site.start()
    
    logger.info("Webhook сервер запущен на http://0.0.0.0:5000/webhook")
    
    # Держим сервер запущенным
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
```

---

## Статусы заказов

### Статусы доставки (status)
- `waiting` - ожидает принятия курьером
- `in_transit` - курьер в пути (принял заказ)
- `done` - доставлен (курьер отправил фото)
- `cancelled` - отменен

### Статусы оплаты (payment_status)
- `NOT_PAID` - не оплачен
- `PAID` - оплачен
- `REFUND` - возврат

---

## Обработка ошибок

### Пример обработки ошибок API

```python
import requests
from requests.exceptions import RequestException

def create_order_safe(api, **kwargs):
    """Безопасное создание заказа с обработкой ошибок"""
    try:
        result = api.create_order(**kwargs)
        return {"success": True, "data": result}
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return {"success": False, "error": "Курьер не найден"}
        elif e.response.status_code == 409:
            return {"success": False, "error": "Заказ с таким ID уже существует"}
        else:
            return {"success": False, "error": f"HTTP ошибка: {e.response.status_code}"}
    except RequestException as e:
        return {"success": False, "error": f"Ошибка соединения: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Неожиданная ошибка: {str(e)}"}

# Использование
api = ShipBotAPI()
result = create_order_safe(
    api,
    courier_tg_chat_id=7960182194,
    external_id="ORDER127",
    client_name="Тест",
    client_phone="+79991234567",
    address="Москва"
)

if result["success"]:
    print(f"Заказ создан: {result['data']}")
else:
    print(f"Ошибка: {result['error']}")
```

---

## Примечания

1. **Тестовые заказы**: Заказы с отрицательным `external_id` (например, "-123") не вызывают отправку webhook-событий.

2. **Таймауты**: Webhook-запросы отправляются с таймаутом 10 секунд. Если ваш сервер не отвечает в течение этого времени, запрос считается неудачным.

3. **Повторные запросы**: ShipBot не выполняет автоматические повторные попытки при неудачной отправке webhook.

4. **Безопасность**: Рекомендуется использовать HTTPS для webhook URL и проверять подлинность запросов (например, через секретный ключ в заголовках).

5. **Маппинг статусов**: Статусы заказов автоматически преобразуются для webhook:
   - `in_transit` → `stage_delivery_10`
   - `done` → `stage_delivery_11`

---

## Контакты и поддержка

При возникновении вопросов или проблем обращайтесь к разработчикам проекта.

