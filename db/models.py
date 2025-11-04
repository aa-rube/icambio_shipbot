from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

# --- Pydantic schemas for FastAPI input ---
class IncomingOrder(BaseModel):
    courier_name: str = Field(..., description="Имя курьера (для поиска в Mongo)")
    external_id: str = Field(..., description="Внешний номер заказа — присваивается внешней системой")
    client_name: str
    client_phone: str
    address: str
    map_url: Optional[str] = None
    notes: Optional[str] = None
    client_tg: Optional[str] = None
    contact_url: Optional[str] = None

# Helpers
def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

ORDER_STATUSES = ("waiting", "in_transit", "done", "cancelled")

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
        await db.actions.insert_one(action)
