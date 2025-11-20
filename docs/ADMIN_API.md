# ShipBot Admin API - Документация

## Содержание
1. [Общая информация](#общая-информация)
2. [Аутентификация](#аутентификация)
3. [Endpoints](#endpoints)
   - [Список курьеров на смене](#1-список-курьеров-на-смене)
   - [Локация курьера](#2-локация-курьера)
   - [Маршрут курьера](#3-маршрут-курьера)
   - [Активные заказы курьера](#4-активные-заказы-курьера)
   - [Детали курьера](#5-детали-курьера)
   - [Завершить заказ](#6-завершить-заказ)
   - [Удалить заказ](#7-удалить-заказ)
   - [Назначить курьера на заказ](#8-назначить-курьера-на-заказ)
   - [Закрыть смену курьера](#9-закрыть-смену-курьера)
4. [Примеры использования](#примеры-использования)
5. [Коды ошибок](#коды-ошибок)

---

## Общая информация

Admin API предоставляет REST endpoints для управления курьерами на смене и их заказами через веб-интерфейс. Все функции, доступные в Telegram боте под кнопкой "Курьеры на смене", теперь доступны через API.

### Base URL
```
http://127.0.0.1:5055
```

### Формат данных
Все запросы и ответы используют JSON формат. Content-Type: `application/json`

---

## Аутентификация

Все Admin API endpoints требуют аутентификации через заголовок `X-Admin-User-ID`.

### Заголовок
```
X-Admin-User-ID: <telegram_user_id>
```

Где `telegram_user_id` - это Telegram ID пользователя с правами `SUPER_ADMIN` в системе.

### Проверка прав
Система проверяет права доступа через функцию `is_super_admin()`, которая проверяет наличие пользователя в коллекции `bot_super_admins` с типом `SUPER_ADMIN`.

### Ошибка доступа
Если пользователь не имеет прав администратора, возвращается ошибка:
```json
{
  "detail": "Access denied. Super admin rights required."
}
```
HTTP Status Code: `403 Forbidden`

---

## Endpoints

### 1. Список курьеров на смене

**Endpoint:** `GET /api/admin/couriers/on-shift`

Возвращает список всех курьеров, которые сейчас на смене (`is_on_shift: true`), с полной информацией о каждом курьере.

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры
Нет

#### Пример запроса
```bash
curl -X GET "http://127.0.0.1:5055/api/admin/couriers/on-shift" \
  -H "X-Admin-User-ID: 123456789"
```

#### Пример ответа
```json
{
  "ok": true,
  "couriers": [
    {
      "chat_id": 123456789,
      "name": "Иван Иванов",
      "username": "ivan_ivanov",
      "status": "В пути (ORDER-123)",
      "orders": {
        "total_today": 5,
        "delivered_today": 3,
        "waiting": 2
      },
      "shift_started_at": "2024-01-15T08:30:00-03:00",
      "shift_started_at_readable": "15 янв. 08:30"
    },
    {
      "chat_id": 987654321,
      "name": "Петр Петров",
      "username": null,
      "status": "Есть заказы",
      "orders": {
        "total_today": 2,
        "delivered_today": 1,
        "waiting": 1
      },
      "shift_started_at": "2024-01-15T09:00:00-03:00",
      "shift_started_at_readable": "15 янв. 09:00"
    }
  ]
}
```

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `couriers` (array) - массив объектов курьеров
  - `chat_id` (int) - Telegram chat ID курьера
  - `name` (str) - имя курьера
  - `username` (str|null) - Telegram username курьера (может быть null)
  - `status` (str) - статус курьера:
    - `"В пути (ORDER-123)"` - курьер в пути с указанием номера заказа
    - `"Есть заказы"` - есть заказы в ожидании
    - `"Нет заказов"` - нет активных заказов
  - `orders` (object) - статистика заказов:
    - `total_today` (int) - всего заказов за сегодня
    - `delivered_today` (int) - доставлено за сегодня
    - `waiting` (int) - ожидают выполнения (waiting + in_transit)
  - `shift_started_at` (str|null) - время начала смены в ISO формате
  - `shift_started_at_readable` (str) - время начала смены в читаемом формате (например, "15 янв. 08:30")

---

### 2. Локация курьера

**Endpoint:** `GET /api/admin/couriers/{chat_id}/location`

Возвращает последнюю известную локацию курьера с ссылкой на Google Maps.

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры пути
- `chat_id` (int) - Telegram chat ID курьера

#### Пример запроса
```bash
curl -X GET "http://127.0.0.1:5055/api/admin/couriers/123456789/location" \
  -H "X-Admin-User-ID: 123456789"
```

#### Пример ответа
```json
{
  "ok": true,
  "chat_id": 123456789,
  "location": {
    "lat": -34.603722,
    "lon": -58.381592,
    "maps_url": "https://maps.google.com/?q=-34.603722,-58.381592",
    "timestamp": "2024-01-15T10:30:00-03:00"
  }
}
```

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `chat_id` (int) - Telegram chat ID курьера
- `location` (object) - данные локации:
  - `lat` (float) - широта
  - `lon` (float) - долгота
  - `maps_url` (str) - прямая ссылка на Google Maps с координатами
  - `timestamp` (str|null) - время последнего обновления локации в ISO формате

#### Ошибки
- `404 Not Found` - локация не найдена (курьер не отправлял геолокацию)

---

### 3. Маршрут курьера

**Endpoint:** `GET /api/admin/couriers/{chat_id}/route`

Возвращает маршрут курьера за последние 72 часа с ссылкой на Google Maps. Маршрут строится из точек локации, ограничен до 50 точек для совместимости с Google Maps.

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры пути
- `chat_id` (int) - Telegram chat ID курьера

#### Пример запроса
```bash
curl -X GET "http://127.0.0.1:5055/api/admin/couriers/123456789/route" \
  -H "X-Admin-User-ID: 123456789"
```

#### Пример ответа
```json
{
  "ok": true,
  "chat_id": 123456789,
  "route": {
    "maps_url": "https://www.google.com/maps/dir/-34.603722,-58.381592/-34.604722,-58.382592/...",
    "points_count": 45,
    "time_range": {
      "start": "2024-01-13T10:30:00-03:00",
      "end": "2024-01-15T10:30:00-03:00"
    }
  }
}
```

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `chat_id` (int) - Telegram chat ID курьера
- `route` (object) - данные маршрута:
  - `maps_url` (str) - ссылка на Google Maps с маршрутом (может быть сокращена через сервис сокращения ссылок)
  - `points_count` (int) - количество точек в маршруте (максимум 50)
  - `time_range` (object) - временной диапазон маршрута:
    - `start` (str) - время первой точки в ISO формате
    - `end` (str) - время последней точки в ISO формате

#### Примечания
- Маршрут строится из локаций за последние 72 часа
- Последняя точка должна быть не старше 24 часов
- Если точек больше 50, выбираются равномерно распределенные точки (первая, последняя и промежуточные)
- Если точек меньше 2, возвращается ссылка на единственную точку

#### Ошибки
- `404 Not Found` - недостаточно данных для построения маршрута

---

### 4. Активные заказы курьера

**Endpoint:** `GET /api/admin/couriers/{chat_id}/orders/active`

Возвращает список активных заказов курьера (статусы `waiting` и `in_transit`) с пагинацией.

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры пути
- `chat_id` (int) - Telegram chat ID курьера

#### Query параметры
- `page` (int, опционально) - номер страницы (начиная с 0, по умолчанию: 0)
- `per_page` (int, опционально) - количество заказов на странице (1-100, по умолчанию: 10)

#### Пример запроса
```bash
curl -X GET "http://127.0.0.1:5055/api/admin/couriers/123456789/orders/active?page=0&per_page=10" \
  -H "X-Admin-User-ID: 123456789"
```

#### Пример ответа
```json
{
  "ok": true,
  "orders": [
    {
      "_id": "65a1b2c3d4e5f6g7h8i9j0k1",
      "external_id": "ORDER-123",
      "courier_tg_chat_id": 123456789,
      "status": "waiting",
      "payment_status": "NOT_PAID",
      "is_cash_payment": false,
      "address": "Av. Corrientes 1234, Buenos Aires",
      "client": {
        "name": "Juan Perez",
        "phone": "+5491123456789",
        "tg": "@juanperez"
      },
      "created_at": "2024-01-15T10:00:00-03:00",
      "updated_at": "2024-01-15T10:00:00-03:00"
    }
  ],
  "pagination": {
    "page": 0,
    "per_page": 10,
    "total": 15,
    "total_pages": 2
  }
}
```

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `orders` (array) - массив объектов заказов (полная структура заказа из БД)
- `pagination` (object) - информация о пагинации:
  - `page` (int) - текущая страница
  - `per_page` (int) - количество элементов на странице
  - `total` (int) - общее количество заказов
  - `total_pages` (int) - общее количество страниц

#### Примечания
- Заказы сортируются по приоритету (убывание), затем по времени создания (возрастание)
- Поля `_id` и `assigned_to` преобразуются в строки для JSON

---

### 5. Детали курьера

**Endpoint:** `GET /api/admin/couriers/{chat_id}`

Возвращает полную информацию о курьере, объединяя данные из нескольких endpoints (статистика, локация, время смены).

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры пути
- `chat_id` (int) - Telegram chat ID курьера

#### Пример запроса
```bash
curl -X GET "http://127.0.0.1:5055/api/admin/couriers/123456789" \
  -H "X-Admin-User-ID: 123456789"
```

#### Пример ответа
```json
{
  "ok": true,
  "chat_id": 123456789,
  "name": "Иван Иванов",
  "username": "ivan_ivanov",
  "is_on_shift": true,
  "status": "В пути (ORDER-123)",
  "orders": {
    "total_today": 5,
    "delivered_today": 3,
    "waiting": 2
  },
  "shift_started_at": "2024-01-15T08:30:00-03:00",
  "shift_started_at_readable": "15 янв. 08:30",
  "location": {
    "lat": -34.603722,
    "lon": -58.381592,
    "maps_url": "https://maps.google.com/?q=-34.603722,-58.381592",
    "timestamp": "2024-01-15T10:30:00-03:00"
  }
}
```

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `chat_id` (int) - Telegram chat ID курьера
- `name` (str) - имя курьера
- `username` (str|null) - Telegram username курьера
- `is_on_shift` (bool) - находится ли курьер на смене
- `status` (str) - статус курьера (см. endpoint "Список курьеров на смене")
- `orders` (object) - статистика заказов
- `shift_started_at` (str|null) - время начала смены в ISO формате
- `shift_started_at_readable` (str) - время начала смены в читаемом формате
- `location` (object|null) - данные локации (если доступна)

#### Ошибки
- `404 Not Found` - курьер не найден

---

### 6. Завершить заказ

**Endpoint:** `POST /api/admin/orders/{external_id}/complete`

Завершает заказ (меняет статус на `done`), отправляет webhook, уведомляет курьера в Telegram.

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры пути
- `external_id` (str) - внешний ID заказа

#### Тело запроса
Нет (пустое тело)

#### Пример запроса
```bash
curl -X POST "http://127.0.0.1:5055/api/admin/orders/ORDER-123/complete" \
  -H "X-Admin-User-ID: 123456789" \
  -H "Content-Type: application/json"
```

#### Пример ответа
```json
{
  "ok": true,
  "external_id": "ORDER-123",
  "status": "done"
}
```

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `external_id` (str) - ID заказа
- `status` (str) - новый статус заказа (всегда `"done"`)

#### Примечания
- Заказ должен существовать и быть в статусе `waiting` или `in_transit`
- После завершения отправляется webhook `order_completed` (если заказ не тестовый)
- Курьер получает уведомление в Telegram
- В заказе сохраняется `closed_by_admin_id` - ID администратора, который закрыл заказ

#### Ошибки
- `400 Bad Request` - заказ не может быть завершен (уже закрыт, не найден и т.д.)
- `404 Not Found` - заказ не найден

---

### 7. Удалить заказ

**Endpoint:** `DELETE /api/admin/orders/{external_id}`

Удаляет заказ из системы и уведомляет курьера в Telegram.

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры пути
- `external_id` (str) - внешний ID заказа

#### Пример запроса
```bash
curl -X DELETE "http://127.0.0.1:5055/api/admin/orders/ORDER-123" \
  -H "X-Admin-User-ID: 123456789"
```

#### Пример ответа
```json
{
  "ok": true,
  "external_id": "ORDER-123"
}
```

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `external_id` (str) - ID удаленного заказа

#### Примечания
- Заказ удаляется из базы данных полностью
- Курьер получает уведомление в Telegram об удалении заказа
- Webhook не отправляется

#### Ошибки
- `404 Not Found` - заказ не найден

---

### 8. Назначить курьера на заказ

**Endpoint:** `PATCH /api/admin/orders/{external_id}/assign`

Назначает заказ другому курьеру. Старый курьер получает уведомление о переназначении, новый курьер получает полную информацию о заказе.

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры пути
- `external_id` (str) - внешний ID заказа

#### Тело запроса
```json
{
  "courier_chat_id": 987654321
}
```

#### Пример запроса
```bash
curl -X PATCH "http://127.0.0.1:5055/api/admin/orders/ORDER-123/assign" \
  -H "X-Admin-User-ID: 123456789" \
  -H "Content-Type: application/json" \
  -d '{"courier_chat_id": 987654321}'
```

#### Пример ответа
```json
{
  "ok": true,
  "external_id": "ORDER-123",
  "courier_chat_id": 987654321
}
```

#### Описание полей запроса
- `courier_chat_id` (int, обязательно) - Telegram chat ID нового курьера

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `external_id` (str) - ID заказа
- `courier_chat_id` (int) - ID нового курьера

#### Примечания
- Заказ должен существовать и быть в статусе `waiting` или `in_transit`
- Новый курьер должен существовать в системе
- Заказ обновляется в Odoo (если настроена интеграция)
- Старый курьер получает уведомление о переназначении
- Новый курьер получает полную информацию о заказе с кнопками управления

#### Ошибки
- `400 Bad Request` - заказ не может быть переназначен (уже закрыт и т.д.)
- `404 Not Found` - заказ или курьер не найден

---

### 9. Закрыть смену курьера

**Endpoint:** `POST /api/admin/couriers/{chat_id}/close-shift`

Закрывает смену курьера. Если у курьера есть активные заказы, их можно передать другому курьеру.

#### Заголовки
- `X-Admin-User-ID` (обязательно) - Telegram ID администратора

#### Параметры пути
- `chat_id` (int) - Telegram chat ID курьера

#### Тело запроса
```json
{
  "transfer_to_chat_id": 987654321
}
```

Или (если нет активных заказов):
```json
{}
```

#### Пример запроса (с передачей заказов)
```bash
curl -X POST "http://127.0.0.1:5055/api/admin/couriers/123456789/close-shift" \
  -H "X-Admin-User-ID: 123456789" \
  -H "Content-Type: application/json" \
  -d '{"transfer_to_chat_id": 987654321}'
```

#### Пример запроса (без активных заказов)
```bash
curl -X POST "http://127.0.0.1:5055/api/admin/couriers/123456789/close-shift" \
  -H "X-Admin-User-ID: 123456789" \
  -H "Content-Type: application/json" \
  -d '{}'
```

#### Пример ответа
```json
{
  "ok": true,
  "chat_id": 123456789,
  "message": "Shift closed successfully. 2 orders transferred to courier 987654321"
}
```

#### Описание полей запроса
- `transfer_to_chat_id` (int, опционально) - Telegram chat ID курьера, на которого передать активные заказы. Обязателен, если у курьера есть активные заказы.

#### Описание полей ответа
- `ok` (bool) - всегда `true` при успешном запросе
- `chat_id` (int) - ID курьера, смена которого закрыта
- `message` (str) - сообщение о результате операции

#### Примечания
- Если у курьера есть активные заказы (`waiting` или `in_transit`) и не указан `transfer_to_chat_id`, возвращается ошибка 400
- Все активные заказы передаются новому курьеру
- Заказы обновляются в Odoo (если настроена интеграция)
- Новый курьер получает уведомления о переданных заказах
- Статус курьера обновляется в Odoo (`is_online: false`)
- Данные смены удаляются из Redis
- Записывается история смены с подсчетом заказов
- Курьер получает уведомление в Telegram о закрытии смены

#### Ошибки
- `400 Bad Request` - у курьера есть активные заказы, но не указан `transfer_to_chat_id`
- `404 Not Found` - курьер или курьер для передачи не найден

---

## Примеры использования

### Python

#### Получить список курьеров на смене
```python
import requests

url = "http://127.0.0.1:5055/api/admin/couriers/on-shift"
headers = {
    "X-Admin-User-ID": "123456789"
}

response = requests.get(url, headers=headers)
data = response.json()

for courier in data["couriers"]:
    print(f"{courier['name']}: {courier['status']}")
    print(f"  Заказов сегодня: {courier['orders']['total_today']}")
    print(f"  Доставлено: {courier['orders']['delivered_today']}")
    print(f"  Ожидают: {courier['orders']['waiting']}")
```

#### Получить локацию курьера
```python
import requests

chat_id = 123456789
url = f"http://127.0.0.1:5055/api/admin/couriers/{chat_id}/location"
headers = {
    "X-Admin-User-ID": "123456789"
}

response = requests.get(url, headers=headers)
data = response.json()

location = data["location"]
print(f"Координаты: {location['lat']}, {location['lon']}")
print(f"Карта: {location['maps_url']}")
```

#### Завершить заказ
```python
import requests

external_id = "ORDER-123"
url = f"http://127.0.0.1:5055/api/admin/orders/{external_id}/complete"
headers = {
    "X-Admin-User-ID": "123456789",
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers)
data = response.json()

if data["ok"]:
    print(f"Заказ {external_id} завершен")
```

#### Назначить курьера на заказ
```python
import requests

external_id = "ORDER-123"
new_courier_id = 987654321
url = f"http://127.0.0.1:5055/api/admin/orders/{external_id}/assign"
headers = {
    "X-Admin-User-ID": "123456789",
    "Content-Type": "application/json"
}
payload = {
    "courier_chat_id": new_courier_id
}

response = requests.patch(url, headers=headers, json=payload)
data = response.json()

if data["ok"]:
    print(f"Заказ {external_id} назначен курьеру {new_courier_id}")
```

#### Закрыть смену курьера
```python
import requests

chat_id = 123456789
transfer_to_id = 987654321
url = f"http://127.0.0.1:5055/api/admin/couriers/{chat_id}/close-shift"
headers = {
    "X-Admin-User-ID": "123456789",
    "Content-Type": "application/json"
}
payload = {
    "transfer_to_chat_id": transfer_to_id
}

response = requests.post(url, headers=headers, json=payload)
data = response.json()

if data["ok"]:
    print(f"Смена курьера {chat_id} закрыта")
    print(data["message"])
```

### JavaScript (fetch)

#### Получить список курьеров на смене
```javascript
const response = await fetch('http://127.0.0.1:5055/api/admin/couriers/on-shift', {
  headers: {
    'X-Admin-User-ID': '123456789'
  }
});

const data = await response.json();

data.couriers.forEach(courier => {
  console.log(`${courier.name}: ${courier.status}`);
  console.log(`  Заказов сегодня: ${courier.orders.total_today}`);
});
```

#### Завершить заказ
```javascript
const externalId = 'ORDER-123';
const response = await fetch(`http://127.0.0.1:5055/api/admin/orders/${externalId}/complete`, {
  method: 'POST',
  headers: {
    'X-Admin-User-ID': '123456789',
    'Content-Type': 'application/json'
  }
});

const data = await response.json();
if (data.ok) {
  console.log(`Заказ ${externalId} завершен`);
}
```

---

## Коды ошибок

### HTTP Status Codes

- `200 OK` - запрос выполнен успешно
- `400 Bad Request` - некорректный запрос (неверные параметры, заказ не может быть выполнен и т.д.)
- `403 Forbidden` - доступ запрещен (пользователь не является администратором)
- `404 Not Found` - ресурс не найден (курьер, заказ и т.д.)
- `409 Conflict` - конфликт (например, заказ с таким external_id уже существует)
- `500 Internal Server Error` - внутренняя ошибка сервера

### Формат ошибки

Все ошибки возвращаются в следующем формате:

```json
{
  "detail": "Описание ошибки"
}
```

### Примеры ошибок

#### Ошибка доступа
```json
{
  "detail": "Access denied. Super admin rights required."
}
```
Status: `403 Forbidden`

#### Ресурс не найден
```json
{
  "detail": "Courier not found"
}
```
Status: `404 Not Found`

#### Некорректный запрос
```json
{
  "detail": "Courier has 2 active orders. Please specify transfer_to_chat_id to transfer orders."
}
```
Status: `400 Bad Request`

---

## Примечания

1. **Временная зона**: Все временные метки возвращаются в таймзоне `America/Argentina/Buenos_Aires` (UTC-3)

2. **Лимиты**: 
   - Максимум 50 точек в маршруте (для совместимости с Google Maps)
   - Максимум 100 заказов на страницу в пагинации

3. **Webhooks**: Webhooks отправляются только для реальных заказов (не тестовых). Тестовые заказы определяются по отрицательному `external_id`.

4. **Интеграция с Odoo**: Некоторые операции (назначение курьера, закрытие смены) обновляют данные в Odoo, если настроена интеграция.

5. **Уведомления**: Курьеры получают уведомления в Telegram при изменении их заказов или статуса смены.

---

## Поддержка

При возникновении проблем проверьте:
1. Правильность заголовка `X-Admin-User-ID`
2. Наличие прав `SUPER_ADMIN` у пользователя
3. Корректность формата запроса (JSON, параметры пути)
4. Логи сервера для детальной информации об ошибках

