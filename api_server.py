import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from aiogram import Bot
from db.mongo import get_db, init_indexes
from db.redis_client import get_redis
from db.models import IncomingOrder, UpdateOrder, utcnow_iso
from keyboards.orders_kb import new_order_kb
from utils.logger import setup_logging
from config import BOT_TOKEN, API_HOST, API_PORT
from bson import ObjectId

app = FastAPI(title="Courier Local API")
bot = Bot(BOT_TOKEN)

@app.on_event("startup")
async def on_startup():
    setup_logging()
    await init_indexes()

@app.post("/api/orders")
async def create_order(payload: IncomingOrder):
    import logging
    logger = logging.getLogger(__name__)
    db = await get_db()
    redis = get_redis()

    # Find courier by tg_chat_id
    courier = await db.couriers.find_one({"tg_chat_id": payload.courier_tg_chat_id})
    if not courier:
        logger.warning(f"Courier not found: {payload.courier_tg_chat_id}")
        raise HTTPException(status_code=404, detail="Courier not found")

    # Ensure external order id uniqueness (also enforced by unique index)
    if await db.couriers_deliveries.find_one({"external_id": payload.external_id}):
        raise HTTPException(status_code=409, detail="Order with this external_id already exists")

    order_doc = {
        "external_id": payload.external_id,
        "courier_tg_chat_id": payload.courier_tg_chat_id,
        "assigned_to": courier["_id"],
        "status": "waiting",
        "payment_status": payload.payment_status,
        "delivery_time": payload.delivery_time,
        "priority": payload.priority,
        "brand": payload.brand,
        "source": payload.source,
        "created_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
        "client": {
            "name": payload.client_name,
            "phone": payload.client_phone,
            "chat_id": payload.client_chat_id,
            "tg": payload.client_tg,
            "contact_url": payload.contact_url,
        },
        "address": payload.address,
        "map_url": payload.map_url,
        "notes": payload.notes,
        "photos": [],
    }
    res = await db.couriers_deliveries.insert_one(order_doc)
    order_doc["_id"] = res.inserted_id

    # If courier on shift -> push Telegram message
    is_on = await redis.get(f"courier:shift:{courier['tg_chat_id']}")
    if is_on == "on":
        priority_emoji = "🔴" if payload.priority >= 5 else "🟡" if payload.priority >= 3 else "⚪"
        
        text = f"⏳ Статус: Ожидает\n\n"
        text += f"<code>{payload.address}</code>\n\n"
        
        if payload.map_url:
            text += f"🗺 <a href='{payload.map_url}'>Карта</a>\n\n"
        
        text += f"💳 {payload.payment_status} | {priority_emoji} Приоритет: {payload.priority}\n"
        
        if payload.delivery_time:
            text += f"⏰ {payload.delivery_time}\n"
        
        text += f"👤 {payload.client_name} | 📞 {payload.client_phone}\n"
        
        if payload.client_tg:
            text += f"@{payload.client_tg.lstrip('@')}\n"
        
        if payload.notes:
            text += f"\n📝 {payload.notes}\n"
        
        if payload.brand or payload.source:
            text += "\n"
            if payload.brand:
                text += f"🏷 {payload.brand}"
            if payload.source:
                text += f" | 📊 {payload.source}"

        try:
            await bot.send_message(
                courier["tg_chat_id"],
                text,
                parse_mode="HTML",
                reply_markup=new_order_kb(payload.external_id)
            )
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            pass

    return JSONResponse({"ok": True, "order_id": str(order_doc["_id"]), "external_id": payload.external_id})

@app.patch("/api/orders/{external_id}")
async def update_order(external_id: str, payload: UpdateOrder):
    import logging
    logger = logging.getLogger(__name__)
    db = await get_db()
    
    order = await db.couriers_deliveries.find_one({"external_id": external_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    update_data = {"updated_at": utcnow_iso()}
    if payload.payment_status is not None:
        update_data["payment_status"] = payload.payment_status
    if payload.delivery_time is not None:
        update_data["delivery_time"] = payload.delivery_time
    if payload.priority is not None:
        update_data["priority"] = payload.priority
    if payload.address is not None:
        update_data["address"] = payload.address
    if payload.map_url is not None:
        update_data["map_url"] = payload.map_url
    if payload.notes is not None:
        update_data["notes"] = payload.notes
    
    await db.couriers_deliveries.update_one({"external_id": external_id}, {"$set": update_data})
    logger.info(f"Order {external_id} updated: {update_data}")
    
    return JSONResponse({"ok": True, "external_id": external_id})

if __name__ == "__main__":
    uvicorn.run("api_server:app", host=API_HOST, port=API_PORT, reload=False)
