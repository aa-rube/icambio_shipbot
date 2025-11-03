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
