from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from config import TIMEZONE

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

# Helpers
def utcnow_iso() -> str:
    """Возвращает текущее время в таймзоне Buenos Aires в ISO формате"""
    now = datetime.now(TIMEZONE)
    return now.replace(microsecond=0).isoformat()

ORDER_STATUSES = ("waiting", "in_transit", "done", "cancelled")
PAYMENT_STATUSES = ("NOT_PAID", "PAID", "REFUND")

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
