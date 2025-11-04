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
  "courier_tg_chat_id": 7960182194,
  "external_id": "ORDER123",
  "client_name": "Client Name",
  "client_phone": "+79991234567",
  "client_chat_id": 123456789,
  "client_tg": "@client_username",
  "contact_url": "tg://user?id=123456789",
  "address": "Moscow, Lenina 10, apt 5",
  "map_url": "https://maps.google.com/?q=55.7558,37.6173",
  "notes": "Call before delivery",
  "brand": "Brand Name",
  "source": "Website",
  "payment_status": "NOT_PAID",
  "delivery_time": "14:00",
  "priority": 1
}
```

**Required fields:**
- `courier_tg_chat_id` - Telegram chat ID курьера (число)
- `external_id` - уникальный ID заказа из внешней системы
- `client_name` - имя клиента
- `client_phone` - телефон клиента
- `address` - адрес доставки

**Optional fields:**
- `client_chat_id` - Telegram chat ID клиента (число)
- `client_tg` - Telegram username клиента
- `contact_url` - deep link на клиента в Telegram
- `map_url` - ссылка на карту
- `notes` - примечания к заказу
- `brand` - бренд/магазин
- `source` - источник заказа
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

**cURL Examples (Git Bash/Windows):**

Минимальный заказ:
```bash
curl -X POST http://127.0.0.1:5055/api/orders -H "Content-Type: application/json" -d '{"courier_tg_chat_id":7960182194,"external_id":"TEST001","client_name":"Test Client","client_phone":"+79991234567","address":"Moscow, Tverskaya 1"}'
```

Полный заказ со всеми полями:
```bash
curl -X POST http://127.0.0.1:5055/api/orders -H "Content-Type: application/json" -d '{"courier_tg_chat_id":7960182194,"external_id":"TEST002","client_name":"John Doe","client_phone":"+79991234567","client_chat_id":123456789,"client_tg":"@johndoe","contact_url":"tg://user?id=123456789","address":"Moscow, Tverskaya 1, apt 10","map_url":"https://maps.google.com/?q=55.7558,37.6173","notes":"Call 10 minutes before delivery","brand":"SuperShop","source":"Website","payment_status":"NOT_PAID","delivery_time":"15:30","priority":5}'
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
  "address": "New address",
  "map_url": "https://maps.google.com/?q=55.7558,37.6173",
  "notes": "Updated notes"
}
```

**Response:**
```json
{
  "ok": true,
  "external_id": "ORDER123"
}
```

**cURL Examples (Git Bash/Windows):**

Обновить статус оплаты:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"payment_status":"PAID"}'
```

Обновить приоритет и время доставки:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"priority":5,"delivery_time":"18:00"}'
```

Обновить адрес:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"address":"Moscow, Arbat 10"}'
```

Обновить примечания:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"notes":"New delivery instructions"}'
```

Установить возврат:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"payment_status":"REFUND"}'
```

Обновить несколько полей:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"payment_status":"PAID","priority":5,"delivery_time":"18:00"}'
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
  "name": "Courier Name",
  "username": "telegram_username",
  "tg_chat_id": 123456789,
  "is_on_shift": false,
  "shift_started_at": null,
  "last_location": null,
  "current_shift_id": null
}
```

**couriers_deliveries:**
```json
{
  "external_id": "ORDER123",
  "courier_tg_chat_id": 7960182194,
  "assigned_to": ObjectId("..."),
  "status": "waiting",
  "payment_status": "NOT_PAID",
  "delivery_time": "14:00",
  "priority": 1,
  "brand": "Brand Name",
  "source": "Website",
  "created_at": "2025-11-04T00:00:00Z",
  "updated_at": "2025-11-04T00:00:00Z",
  "client": {
    "name": "Client",
    "phone": "+79991234567",
    "chat_id": 123456789,
    "tg": "@username",
    "contact_url": "tg://user?id=123"
  },
  "address": "Delivery address",
  "map_url": "https://maps.google.com/...",
  "notes": "Notes",
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
   curl -X POST http://127.0.0.1:5055/api/orders -H "Content-Type: application/json" -d '{"courier_tg_chat_id":7960182194,"external_id":"TEST001","client_name":"Client","client_phone":"+79991234567","address":"Address"}'
   ```

4. **Курьер получает уведомление и обрабатывает заказ**

5. **Обновить статус оплаты:**
   ```bash
   curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"payment_status":"PAID"}'
   ```

### Quick Test Commands

Создать минимальный заказ:
```bash
curl -X POST http://127.0.0.1:5055/api/orders -H "Content-Type: application/json" -d '{"courier_tg_chat_id":7960182194,"external_id":"TEST001","client_name":"Test Client","client_phone":"+79991234567","address":"Test Address"}'
```

Создать заказ с приоритетом и брендом:
```bash
curl -X POST http://127.0.0.1:5055/api/orders -H "Content-Type: application/json" -d '{"courier_tg_chat_id":7960182194,"external_id":"TEST003","client_name":"Jane Smith","client_phone":"+79991234567","address":"Moscow, Arbat 5","brand":"MegaStore","source":"Mobile App","priority":8,"delivery_time":"16:00"}'
```

Создать заказ со всеми данными клиента:
```bash
curl -X POST http://127.0.0.1:5055/api/orders -H "Content-Type: application/json" -d '{"courier_tg_chat_id":7960182194,"external_id":"TEST004","client_name":"Alex Brown","client_phone":"+79991234567","client_chat_id":987654321,"client_tg":"@alexbrown","contact_url":"tg://user?id=987654321","address":"Moscow, Lenina 20","map_url":"https://maps.google.com/?q=55.7558,37.6173","notes":"Ring the bell twice","brand":"ShopX","source":"Instagram","payment_status":"NOT_PAID","delivery_time":"14:30","priority":3}'
```

Обновить статус на PAID:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"payment_status":"PAID"}'
```

Установить возврат:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"payment_status":"REFUND"}'
```

Обновить приоритет:
```bash
curl -X PATCH http://127.0.0.1:5055/api/orders/TEST001 -H "Content-Type: application/json" -d '{"priority":10}'
```

### Telegram Message Format

Курьер получает сообщение в формате (HTML):
```
⏳ Статус: Ожидает

Moscow, Tverskaya 1, apt 10  (моноширинный шрифт)

🗺 Карта (ссылка)

💳 NOT_PAID | 🔴 Приоритет: 5
⏰ 15:30
👤 John Doe | 📞 +79991234567
@johndoe

📝 Call 10 minutes before delivery

🏷 SuperShop | 📊 Website
```

Адрес отображается моноширинным шрифтом (&lt;code&gt;) для копирования одним тапом.
