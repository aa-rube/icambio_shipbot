from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING
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
    # Orders
    await db.orders.create_index([("external_id", ASCENDING)], unique=True)
    await db.orders.create_index([("assigned_to", ASCENDING)])
    await db.orders.create_index([("status", ASCENDING)])
    await db.orders.create_index([("created_at", ASCENDING)])
