from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from config import MONGO_URI, MONGO_DB_NAME

_client: Optional[AsyncIOMotorClient] = None

async def get_db() -> AsyncIOMotorDatabase:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URI, uuidRepresentation="standard")
    return _client[MONGO_DB_NAME]

async def init_indexes():
    db = await get_db()
    # Couriers
    await db.couriers.create_index([("tg_chat_id", ASCENDING)], unique=True)
    await db.couriers.create_index([("name", ASCENDING)])
    # Couriers Deliveries
    await db.couriers_deliveries.create_index([("external_id", ASCENDING)], unique=True)
    await db.couriers_deliveries.create_index([("assigned_to", ASCENDING)])
    await db.couriers_deliveries.create_index([("status", ASCENDING)])
    await db.couriers_deliveries.create_index([("created_at", ASCENDING)])
    # Actions
    await db.ship_bot_user_action.create_index([("user_id", ASCENDING)])
    await db.ship_bot_user_action.create_index([("action_type", ASCENDING)])
    await db.ship_bot_user_action.create_index([("timestamp", ASCENDING)])
    await db.ship_bot_user_action.create_index([("order_id", ASCENDING)])
    # Locations
    await db.locations.create_index([("chat_id", ASCENDING), ("date", ASCENDING), ("shift_id", ASCENDING)])
    await db.locations.create_index([("timestamp_ns", DESCENDING)])
    await db.locations.create_index([("shift_id", ASCENDING)])
