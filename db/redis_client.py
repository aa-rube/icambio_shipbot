from typing import Optional
from redis.asyncio import Redis
from config import REDIS_URL

_redis: Optional[Redis] = None

def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis
