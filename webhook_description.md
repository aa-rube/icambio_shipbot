# Webhook API Documentation

## Обзор

ShipBot отправляет webhook уведомления на указанный URL при наступлении следующих событий:

- **shift_start** - курьер выходит на линию (начинает смену)
- **shift_end** - курьер уходит с линии (завершает смену)
- **order_accepted** - курьер берет заказ в работу
- **order_completed** - курьер завершает заказ

## Настройка

Добавьте в `.env` файл:

```env
WEBHOOK_URL=https://your-server.com/api/webhooks/shipbot
```

Если `WEBHOOK_URL` не указан, webhook'и не будут отправляться.

## Формат запроса

Все webhook'и отправляются как `POST` запросы с JSON телом:

```json
{
  "event_type": "shift_start",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    // Данные события
  }
}
```

### Поля запроса

- `event_type` (string) - тип события: `shift_start`, `shift_end`, `order_accepted`, `order_completed`
- `timestamp` (string) - время события в формате ISO 8601 (UTC)
- `data` (object) - полные данные события

## События

### 1. shift_start - Выход на линию

Отправляется когда курьер начинает смену (отправляет live location).

**Формат данных:**

```json
{
  "event_type": "shift_start",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "courier_id": "507f1f77bcf86cd799439011",
    "name": "Иван Петров",
    "username": "ivan_petrov",
    "tg_chat_id": 7960182194,
    "is_on_shift": true,
    "shift_started_at": "2025-01-15T10:30:00Z",
    "current_shift_id": "507f1f77bcf86cd799439012",
    "last_location": {
      "lat": 55.7558,
      "lon": 37.6173,
      "updated_at": "2025-01-15T10:30:00Z"
    },
    "location": {
      "lat": 55.7558,
      "lon": 37.6173,
      "updated_at": "2025-01-15T10:30:00Z"
    },
    "shift_id": "507f1f77bcf86cd799439012",
    "active_orders_count": 0,
    "timestamp": "2025-01-15T10:30:00Z"
  }
}
```

**Поля данных:**

- `courier_id` (string) - MongoDB ObjectId курьера
- `name` (string) - имя курьера
- `username` (string, optional) - Telegram username
- `tg_chat_id` (number) - Telegram chat ID курьера
- `is_on_shift` (boolean) - статус смены (всегда `true` для этого события)
- `shift_started_at` (string) - время начала смены (ISO 8601)
- `current_shift_id` (string) - уникальный ID смены
- `last_location` (object) - последняя известная локация курьера
  - `lat` (number) - широта
  - `lon` (number) - долгота
  - `updated_at` (string) - время обновления
- `location` (object) - локация начала смены (то же что `last_location`)
- `shift_id` (string) - ID смены (то же что `current_shift_id`)
- `active_orders_count` (number) - количество активных заказов курьера
- `timestamp` (string) - время события

---

### 2. shift_end - Уход с линии

Отправляется когда курьер завершает смену.

**Формат данных:**

```json
{
  "event_type": "shift_end",
  "timestamp": "2025-01-15T18:30:00Z",
  "data": {
    "courier_id": "507f1f77bcf86cd799439011",
    "name": "Иван Петров",
    "username": "ivan_petrov",
    "tg_chat_id": 7960182194,
    "is_on_shift": false,
    "shift_started_at": "2025-01-15T10:30:00Z",
    "current_shift_id": null,
    "last_location": {
      "lat": 55.7558,
      "lon": 37.6173,
      "updated_at": "2025-01-15T18:25:00Z"
    },
    "active_orders_count": 0,
    "timestamp": "2025-01-15T18:30:00Z"
  }
}
```

**Поля данных:**

- `courier_id` (string) - MongoDB ObjectId курьера
- `name` (string) - имя курьера
- `username` (string, optional) - Telegram username
- `tg_chat_id` (number) - Telegram chat ID курьера
- `is_on_shift` (boolean) - статус смены (всегда `false` для этого события)
- `shift_started_at` (string, optional) - время начала последней смены
- `current_shift_id` (null) - ID смены (удаляется при завершении)
- `last_location` (object, optional) - последняя известная локация курьера
- `active_orders_count` (number) - количество активных заказов (всегда 0, иначе смена не завершится)
- `timestamp` (string) - время события

**Примечание:** Смена не может быть завершена, если у курьера есть незавершенные заказы (`waiting` или `in_transit`).

---

### 3. order_accepted - Заказ взят в работу

Отправляется когда курьер принимает заказ (нажимает "Взять в работу").

**Формат данных:**

```json
{
  "event_type": "order_accepted",
  "timestamp": "2025-01-15T11:00:00Z",
  "data": {
    "order_id": "507f1f77bcf86cd799439013",
    "external_id": "ORDER123",
    "status": "in_transit",
    "payment_status": "NOT_PAID",
    "delivery_time": "14:00",
    "priority": 5,
    "brand": "SuperShop",
    "source": "Website",
    "created_at": "2025-01-15T10:00:00Z",
    "updated_at": "2025-01-15T11:00:00Z",
    "client": {
      "name": "Иван Сидоров",
      "phone": "+79991234567",
      "chat_id": 123456789,
      "tg": "@ivan_sidorov",
      "contact_url": "tg://user?id=123456789"
    },
    "address": "Moscow, Tverskaya 1, apt 10",
    "map_url": "https://maps.google.com/?q=55.7558,37.6173",
    "notes": "Call 10 minutes before delivery",
    "photos": [],
    "courier": {
      "courier_id": "507f1f77bcf86cd799439011",
      "name": "Иван Петров",
      "username": "ivan_petrov",
      "tg_chat_id": 7960182194
    },
    "timestamp": "2025-01-15T11:00:00Z"
  }
}
```

**Поля данных:**

- `order_id` (string) - MongoDB ObjectId заказа
- `external_id` (string) - внешний ID заказа
- `status` (string) - статус заказа: `"in_transit"` (в пути)
- `payment_status` (string) - статус оплаты: `"NOT_PAID"`, `"PAID"`, `"REFUND"`
- `delivery_time` (string, optional) - время доставки (например, "14:00")
- `priority` (number) - приоритет заказа (0 по умолчанию)
- `brand` (string, optional) - бренд/магазин
- `source` (string, optional) - источник заказа
- `created_at` (string) - время создания заказа (ISO 8601)
- `updated_at` (string) - время последнего обновления (ISO 8601)
- `client` (object) - данные клиента
  - `name` (string) - имя клиента
  - `phone` (string) - телефон клиента
  - `chat_id` (number, optional) - Telegram chat ID клиента
  - `tg` (string, optional) - Telegram username клиента
  - `contact_url` (string, optional) - deep link на клиента
- `address` (string) - адрес доставки
- `map_url` (string, optional) - ссылка на карту
- `notes` (string, optional) - примечания к заказу
- `photos` (array) - массив фото (пустой на этом этапе)
- `courier` (object) - данные курьера
  - `courier_id` (string) - MongoDB ObjectId курьера
  - `name` (string) - имя курьера
  - `username` (string, optional) - Telegram username
  - `tg_chat_id` (number) - Telegram chat ID курьера
- `timestamp` (string) - время события

---

### 4. order_completed - Заказ завершен

Отправляется когда курьер завершает заказ (отправляет фото подтверждения).

**Формат данных:**

```json
{
  "event_type": "order_completed",
  "timestamp": "2025-01-15T12:00:00Z",
  "data": {
    "order_id": "507f1f77bcf86cd799439013",
    "external_id": "ORDER123",
    "status": "done",
    "payment_status": "NOT_PAID",
    "delivery_time": "14:00",
    "priority": 5,
    "brand": "SuperShop",
    "source": "Website",
    "created_at": "2025-01-15T10:00:00Z",
    "updated_at": "2025-01-15T12:00:00Z",
    "client": {
      "name": "Иван Сидоров",
      "phone": "+79991234567",
      "chat_id": 123456789,
      "tg": "@ivan_sidorov",
      "contact_url": "tg://user?id=123456789"
    },
    "address": "Moscow, Tverskaya 1, apt 10",
    "map_url": "https://maps.google.com/?q=55.7558,37.6173",
    "notes": "Call 10 minutes before delivery",
    "photos": [
      {
        "file_id": "AgACAgIAAxkBAAIBY2...",
        "uploaded_at": "2025-01-15T12:00:00Z"
      }
    ],
    "courier": {
      "courier_id": "507f1f77bcf86cd799439011",
      "name": "Иван Петров",
      "username": "ivan_petrov",
      "tg_chat_id": 7960182194
    },
    "timestamp": "2025-01-15T12:00:00Z"
  }
}
```

**Поля данных:**

Те же что и в `order_accepted`, но:

- `status` (string) - статус заказа: `"done"` (выполнен)
- `updated_at` (string) - время завершения заказа
- `photos` (array) - массив фото с подтверждениями
  - `file_id` (string) - Telegram file_id фото
  - `uploaded_at` (string) - время загрузки фото (ISO 8601)

---

## Обработка запросов

### HTTP заголовки

Webhook запросы отправляются с заголовками:

```
Content-Type: application/json
```

### Таймаут

Таймаут запроса: **10 секунд**

### Ожидаемый ответ

Сервер должен возвращать HTTP 200 для успешной обработки. Если получен другой статус код, событие будет залогировано как предупреждение, но не повлияет на работу бота.

### Обработка ошибок

- Если webhook URL не настроен, запросы не отправляются (без ошибок)
- Если запрос не удался (сетевая ошибка, таймаут), ошибка логируется, но не влияет на работу бота
- Ошибки отправки webhook не блокируют выполнение основного функционала

## Примеры обработки

### Node.js (Express)

```javascript
app.post('/api/webhooks/shipbot', async (req, res) => {
  const { event_type, timestamp, data } = req.body;
  
  console.log(`Received ${event_type} at ${timestamp}`);
  
  switch (event_type) {
    case 'shift_start':
      console.log(`Courier ${data.name} started shift`);
      // Обработка начала смены
      break;
      
    case 'shift_end':
      console.log(`Courier ${data.name} ended shift`);
      // Обработка завершения смены
      break;
      
    case 'order_accepted':
      console.log(`Order ${data.external_id} accepted by ${data.courier.name}`);
      // Обработка принятия заказа
      break;
      
    case 'order_completed':
      console.log(`Order ${data.external_id} completed by ${data.courier.name}`);
      // Обработка завершения заказа
      break;
  }
  
  res.status(200).json({ ok: true });
});
```

### Python (Flask)

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/api/webhooks/shipbot', methods=['POST'])
def webhook():
    payload = request.json
    event_type = payload.get('event_type')
    timestamp = payload.get('timestamp')
    data = payload.get('data')
    
    print(f"Received {event_type} at {timestamp}")
    
    if event_type == 'shift_start':
        print(f"Courier {data['name']} started shift")
        # Обработка начала смены
    elif event_type == 'shift_end':
        print(f"Courier {data['name']} ended shift")
        # Обработка завершения смены
    elif event_type == 'order_accepted':
        print(f"Order {data['external_id']} accepted by {data['courier']['name']}")
        # Обработка принятия заказа
    elif event_type == 'order_completed':
        print(f"Order {data['external_id']} completed by {data['courier']['name']}")
        # Обработка завершения заказа
    
    return jsonify({'ok': True}), 200
```

### PHP

```php
<?php
header('Content-Type: application/json');

$payload = json_decode(file_get_contents('php://input'), true);
$eventType = $payload['event_type'];
$timestamp = $payload['timestamp'];
$data = $payload['data'];

error_log("Received {$eventType} at {$timestamp}");

switch ($eventType) {
    case 'shift_start':
        error_log("Courier {$data['name']} started shift");
        // Обработка начала смены
        break;
        
    case 'shift_end':
        error_log("Courier {$data['name']} ended shift");
        // Обработка завершения смены
        break;
        
    case 'order_accepted':
        error_log("Order {$data['external_id']} accepted by {$data['courier']['name']}");
        // Обработка принятия заказа
        break;
        
    case 'order_completed':
        error_log("Order {$data['external_id']} completed by {$data['courier']['name']}");
        // Обработка завершения заказа
        break;
}

http_response_code(200);
echo json_encode(['ok' => true]);
?>
```

## Тестирование

### Локальное тестирование с ngrok

1. Установите ngrok: https://ngrok.com/
2. Запустите локальный сервер на порту 3000
3. Запустите ngrok: `ngrok http 3000`
4. Скопируйте HTTPS URL (например, `https://abc123.ngrok.io`)
5. Добавьте в `.env`: `WEBHOOK_URL=https://abc123.ngrok.io/api/webhooks/shipbot`
6. Перезапустите бота

### Проверка логов

Все попытки отправки webhook логируются:

- Успешная отправка: `INFO: Webhook sent successfully for {event_type}`
- Ошибка: `ERROR: Error sending webhook for {event_type}: {error}`

## Безопасность

Рекомендуется:

1. Использовать HTTPS для webhook URL
2. Проверять подпись запроса (если требуется, можно добавить в будущем)
3. Валидировать входящие данные
4. Ограничить доступ к endpoint с помощью IP whitelist или токена

## Часто задаваемые вопросы

**Q: Что если webhook не доставлен?**  
A: Ошибка логируется, но не влияет на работу бота. Заказ или смена будут обработаны как обычно.

**Q: Можно ли отключить webhook'и?**  
A: Да, просто не указывайте `WEBHOOK_URL` в `.env` или удалите его.

**Q: Как часто отправляются webhook'и?**  
A: Только при наступлении событий (выход/уход с линии, принятие/завершение заказа).

**Q: Можно ли добавить другие события?**  
A: Да, можно расширить функционал, добавив новые типы событий в код.

**Q: Что если сервер недоступен?**  
A: Запрос не будет отправлен, ошибка залогируется. Бот продолжит работу как обычно.

