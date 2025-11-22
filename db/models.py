from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from config import TIMEZONE

# --- Order Document Structure ---
# Заказ в MongoDB (коллекция couriers_deliveries) содержит следующие поля:
# - courier_message_ids: List[int] = [] - массив message_id сообщений с заказом, 
#   отправленных курьеру в Telegram. Используется для последующего удаления 
#   всех сообщений о заказе из чата курьера.

# --- Pydantic schemas for FastAPI input ---
class IncomingOrder(BaseModel):
    courier_tg_chat_id: int = Field(..., description="Telegram chat ID курьера")
    external_id: str = Field(..., description="Внешний номер заказа — присваивается внешней системой")
    client_name: str
    client_phone: str
    client_chat_id: Optional[int] = None
    client_tg: Optional[str] = None
    contact_url: Optional[str] = None
    address: str
    map_url: Optional[str] = None
    notes: Optional[str] = None
    brand: Optional[str] = None
    source: Optional[str] = None
    payment_status: str = Field(default="NOT_PAID", description="NOT_PAID, PAID, REFUND")
    is_cash_payment: bool = Field(default=False, description="Признак оплаты заказа наличными")
    delivery_time: Optional[str] = None
    priority: int = Field(default=0, description="Приоритет заказа")

class UpdateOrder(BaseModel):
    payment_status: Optional[str] = None
    is_cash_payment: Optional[bool] = None
    delivery_time: Optional[str] = None
    priority: Optional[int] = None
    address: Optional[str] = None
    map_url: Optional[str] = None
    notes: Optional[str] = None

# --- Admin API Models ---

class CourierOrdersStats(BaseModel):
    total_today: int
    delivered_today: int
    waiting: int

class CourierOnShift(BaseModel):
    chat_id: int
    name: str
    username: Optional[str] = None
    status: str
    orders: CourierOrdersStats
    shift_started_at: Optional[str] = None
    shift_started_at_readable: str

class CouriersOnShiftResponse(BaseModel):
    ok: bool = True
    couriers: List[CourierOnShift]

class LocationData(BaseModel):
    lat: float
    lon: float
    maps_url: str
    timestamp: Optional[str] = None

class CourierLocationResponse(BaseModel):
    ok: bool = True
    chat_id: int
    location: LocationData

class RouteTimeRange(BaseModel):
    start: str
    end: str

class RouteData(BaseModel):
    maps_url: str
    points_count: int
    time_range: RouteTimeRange

class CourierRouteResponse(BaseModel):
    ok: bool = True
    chat_id: int
    route: RouteData

class PaginationInfo(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int

class ActiveOrdersResponse(BaseModel):
    ok: bool = True
    orders: List[Dict[str, Any]]
    pagination: PaginationInfo

class AssignCourierRequest(BaseModel):
    courier_chat_id: int

class CloseShiftRequest(BaseModel):
    transfer_to_chat_id: Optional[int] = None

class OrderCompleteResponse(BaseModel):
    ok: bool = True
    external_id: str
    status: str = "done"

class OrderDeleteResponse(BaseModel):
    ok: bool = True
    external_id: str

class OrderAssignResponse(BaseModel):
    ok: bool = True
    external_id: str
    courier_chat_id: int

class CloseShiftResponse(BaseModel):
    ok: bool = True
    chat_id: int
    message: str

# Helpers
def utcnow_iso() -> str:
    """Возвращает текущее время в таймзоне Buenos Aires в ISO формате"""
    now = datetime.now(TIMEZONE)
    return now.replace(microsecond=0).isoformat()

ORDER_STATUSES = ("waiting", "in_transit", "done", "cancelled")
PAYMENT_STATUSES = ("NOT_PAID", "PAID", "REFUND")

def get_status_history_update(order: Dict[str, Any], new_status: Optional[str] = None, new_payment_status: Optional[str] = None) -> Dict[str, Any]:
    """
    Создает обновление для MongoDB с записью статуса и времени в историю заказа.
    
    Args:
        order: Текущий документ заказа из БД
        new_status: Новый статус заказа (waiting, in_transit, done, cancelled)
        new_payment_status: Новый статус оплаты (NOT_PAID, PAID, REFUND)
    
    Returns:
        Словарь с обновлением для MongoDB ($set операция)
    """
    # Получаем текущую историю статусов или создаем новую
    status_history = order.get("status_history", {})
    current_time = utcnow_iso()
    
    # Если передан новый статус заказа, записываем его
    if new_status and new_status in ORDER_STATUSES:
        status_history[new_status] = current_time
    
    # Если передан новый статус оплаты, маппим его и записываем
    if new_payment_status and new_payment_status in PAYMENT_STATUSES:
        # Маппинг: NOT_PAID -> un_paid, PAID -> paid, REFUND -> paid (отмена заказа тоже считается как paid)
        if new_payment_status == "NOT_PAID":
            payment_status_key = "un_paid"
        else:  # PAID или REFUND
            payment_status_key = "paid"
        status_history[payment_status_key] = current_time
    
    # Возвращаем обновление для MongoDB
    return {"status_history": status_history}

# Action types
ACTION_TYPES = (
    "user_start",           # /start
    "shift_start",          # начало смены
    "shift_end",            # конец смены
    "location_sent",        # отправка геолокации
    "order_viewed",         # просмотр заказов
    "order_accepted",       # принял заказ (в пути)
    "order_postponed",      # отложил заказ
    "order_completed",      # завершил заказ
    "order_problem",        # проблема с заказом
    "photo_sent",           # отправил фото
    "payment_accepted",     # принял оплату
    "payment_photo_sent",  # отправил фото оплаты
    "message_sent",         # отправил сообщение
    "admin_add_user",       # админ добавил пользователя
    "admin_del_user",       # админ удалил пользователя
    "admin_broadcast",      # админ сделал рассылку
)

class Action:
    """Модель для логирования действий пользователей"""
    
    @staticmethod
    def create(
        user_id: int,
        action_type: str,
        details: Optional[Dict[str, Any]] = None,
        order_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Создает документ действия для записи в БД"""
        return {
            "user_id": user_id,
            "action_type": action_type,
            "order_id": order_id,
            "details": details or {},
            "metadata": metadata or {},
            "timestamp": utcnow_iso()
        }
    
    @staticmethod
    async def log(db, user_id: int, action_type: str, **kwargs):
        """Быстрое логирование действия"""
        action = Action.create(user_id, action_type, **kwargs)
        await db.ship_bot_user_action.insert_one(action)

class ShiftHistory:
    """Модель для истории смен курьеров"""
    
    @staticmethod
    def create(
        courier_tg_chat_id: int,
        event: str,
        shift_id: Optional[str] = None,
        total_orders: int = 0,
        complete_orders: int = 0,
        shift_started_at: Optional[str] = None
    ) -> dict:
        """
        Создает документ истории смены для записи в БД
        
        Args:
            courier_tg_chat_id: Telegram chat ID курьера
            event: "shift_started" или "shift_ended"
            shift_id: ID смены (опционально)
            total_orders: Общее количество заказов за смену
            complete_orders: Количество завершенных заказов
            shift_started_at: Время начала смены (ISO формат)
        """
        now = datetime.now(TIMEZONE)
        timestamp = now.replace(microsecond=0).isoformat()
        time_readable = now.strftime("%d.%m.%Y %H:%M")
        
        return {
            "courier_tg_chat_id": courier_tg_chat_id,
            "event": event,
            "shift_id": shift_id,
            "total_orders": total_orders,
            "complete_orders": complete_orders,
            "timestamp": timestamp,
            "time": time_readable,
            "shift_started_at": shift_started_at
        }
    
    @staticmethod
    async def log(db, courier_tg_chat_id: int, event: str, **kwargs):
        """Быстрое логирование истории смены"""
        shift_history = ShiftHistory.create(courier_tg_chat_id, event, **kwargs)
        await db.shift_history.insert_one(shift_history)
