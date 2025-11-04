# ShipBot API Documentation

## Base URL
```
http://127.0.0.1:5055
```

## Endpoints

### 1. Create Order
Создает новый заказ и назначает его курьеру.

**Endpoint:** `POST /api/orders`

**Request Body:**
```json
{
  "courier_name": "Иван Иванов",
  "external_id": "ORDER123",
  "client_name": "Петр Петров",
  "client_phone": "+79991234567",
  "address": "ул. Ленина, д. 10, кв. 5",
  "map_url": "https://maps.google.com/?q=55.7558,37.6173",
  "notes": "Домофон не работает, звонить",
  "client_tg": "@client_username",
  "contact_url": "tg://user?id=123456789",
  "payment_status": "NOT_PAID",
  "delivery_time": "14:00",
  "priority": 1
}
```

**Required fields:**
- `courier_name` - имя курьера или его tg_chat_id (если число)
- `external_id` - уникальный ID заказа из внешней системы
- `client_name` - имя клиента
- `client_phone` - телефон клиента
- `address` - адрес доставки

**Optional fields:**
- `map_url` - ссылка на карту
- `notes` - примечания к заказу
- `client_tg` - Telegram username клиента
- `contact_url` - deep link на клиента в Telegram
- `payment_status` - статус оплаты: `NOT_PAID`, `PAID`, `REFUND` (default: `NOT_PAID`)
- `delivery_time` - время доставки
- `priority` - приоритет заказа (число, default: 0)

**Response:**
```json
{
  "ok": true,
  "order_id": "507f1f77bcf86cd799439011",
  "external_id": "ORDER123"
}
```

**cURL Example:**
```bash
curl -X POST http://127.0.0.1:5055/api/orders \
  -H "Content-Type: application/json" \
  -d '{
    "courier_name": "7960182194",
    "external_id": "TEST001",
    "client_name": "Тестовый Клиент",
    "client_phone": "+79991234567",
    "address": "Москва, ул. Тверская, д. 1",
    "map_url": "https://maps.google.com/?q=55.7558,37.6173",
    "notes": "Позвонить за 10 минут",
    "payment_status": "NOT_PAID",
    "delivery_time": "15:30",
    "priority": 2
  }'
```

---

### 2. Update Order
Обновляет существующий заказ.

**Endpoint:** `PATCH /api/orders/{external_id}`

**Request Body (все поля опциональны):**
```json
{
  "payment_status": "PAID",
  "delivery_time": "16:00",
  "priority": 3,
  "address": "Новый адрес",
  "map_url": "https://maps.google.com/?q=55.7558,37.6173",
  "notes": "Обновленные примечания"
}
```

**Response:**
```json
{
  "ok": true,
  "external_id": "ORDER123"
}
```

**cURL Examples:**

Обновить статус оплаты:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 \
  -H "Content-Type: application/json" \
  -d '{
    "payment_status": "PAID"
  }'
```

Обновить приоритет и время доставки:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 \
  -H "Content-Type: application/json" \
  -d '{
    "priority": 5,
    "delivery_time": "18:00"
  }'
```

Обновить адрес и примечания:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 \
  -H "Content-Type: application/json" \
  -d '{
    "address": "Москва, ул. Арбат, д. 10",
    "notes": "Новые инструкции для курьера"
  }'
```

Установить возврат:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 \
  -H "Content-Type: application/json" \
  -d '{
    "payment_status": "REFUND"
  }'
```

---

## Order Statuses

### Delivery Status (status)
- `waiting` - ожидает принятия курьером
- `in_transit` - курьер в пути
- `done` - доставлен
- `cancelled` - отменен

### Payment Status (payment_status)
- `NOT_PAID` - не оплачен
- `PAID` - оплачен
- `REFUND` - возврат

---

## Error Responses

**404 Not Found:**
```json
{
  "detail": "Courier not found"
}
```

**409 Conflict:**
```json
{
  "detail": "Order with this external_id already exists"
}
```

---

## Development Notes

### Environment Variables
Создайте `.env` файл:
```env
BOT_TOKEN=your_telegram_bot_token
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=icambio
REDIS_URL=redis://localhost:6379/0
API_HOST=127.0.0.1
API_PORT=5055
MANAGER_CHAT_ID=123456789
```

### Running the API Server
```bash
python api_server.py
```

### Running the Bot
```bash
python bot.py
```

### MongoDB Collections

**couriers:**
```json
{
  "name": "Имя курьера",
  "username": "telegram_username",
  "tg_chat_id": 123456789,
  "is_on_shift": false,
  "shift_started_at": null,
  "last_location": null,
  "current_shift_id": null
}
```

**orders:**
```json
{
  "external_id": "ORDER123",
  "assigned_to": ObjectId("..."),
  "status": "waiting",
  "payment_status": "NOT_PAID",
  "delivery_time": "14:00",
  "priority": 1,
  "created_at": "2025-11-04T00:00:00Z",
  "updated_at": "2025-11-04T00:00:00Z",
  "client": {
    "name": "Клиент",
    "phone": "+79991234567",
    "tg": "@username",
    "contact_url": "tg://user?id=123"
  },
  "address": "Адрес доставки",
  "map_url": "https://maps.google.com/...",
  "notes": "Примечания",
  "photos": []
}
```

**locations:**
```json
{
  "chat_id": 123456789,
  "shift_id": "unique_shift_id",
  "date": "04-11-2025",
  "lat": 55.7558,
  "lon": 37.6173,
  "timestamp": "2025-11-04T00:00:00Z",
  "timestamp_ns": 1730678400000000000
}
```

**actions:**
```json
{
  "user_id": 123456789,
  "action_type": "shift_start",
  "order_id": "ORDER123",
  "details": {},
  "metadata": {},
  "timestamp": "2025-11-04T00:00:00Z"
}
```

### Testing Workflow

1. **Добавить курьера через админку:**
   - Отправить `/admin` боту
   - Нажать "➕ Добавить пользователя"
   - Выбрать пользователя из контактов

2. **Курьер начинает смену:**
   - Отправить `/start` боту
   - Нажать "🟢 Начать смену"
   - Отправить live location на 8+ часов

3. **Создать заказ через API:**
   ```bash
   curl -X POST http://127.0.0.1:5055/api/orders \
     -H "Content-Type: application/json" \
     -d '{"courier_name":"7960182194","external_id":"TEST001","client_name":"Клиент","client_phone":"+79991234567","address":"Адрес"}'
   ```

4. **Курьер получает уведомление и обрабатывает заказ**

5. **Обновить статус оплаты:**
   ```bash
   curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 \
     -H "Content-Type: application/json" \
     -d '{"payment_status":"PAID"}'
   ```

### Quick Test Commands

Создать тестовый заказ:
```bash
curl -X POST http://127.0.0.1:5055/api/orders -H "Content-Type: application/json" -d '{"courier_name":"7960182194","external_id":"TEST001","client_name":"Test","client_phone":"+79991234567","address":"Test Address","payment_status":"NOT_PAID","priority":1}'
```

Обновить на PAID:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"payment_status":"PAID"}'
```

Установить возврат:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"payment_status":"REFUND"}'
```
