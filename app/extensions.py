from typing import Optional
import json
import redis
from app.config import REDIS_URL

# ─── Redis ────────────────────────────────────────────────────────────────────

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def get_cached_token_data(token: str) -> Optional[dict]:
    data = redis_client.get(f"token:{token}")
    return json.loads(data) if data else None

def set_cached_token_data(token: str, data: dict):
    redis_client.set(f"token:{token}", json.dumps(data))

def delete_cached_token(token: str):
    redis_client.delete(f"token:{token}")
