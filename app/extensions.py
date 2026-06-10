from typing import Optional
import json
import redis
from app.config import REDIS_URL
from app.transports.send_request import CenterService

# ─── Center Service ───────────────────────────────────────────────────────────

_center_service = None

def init_center_service(center_access_key, center_url):
    global _center_service
    _center_service = CenterService(base_url=center_url, token=center_access_key)
    print(f"Center Service : {_center_service}")

def get_center_service():
    if _center_service is None:
        raise RuntimeError("CenterService not initialized")
    return _center_service


# ─── Redis ────────────────────────────────────────────────────────────────────

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def get_cached_token_data(token: str) -> Optional[dict]:
    data = redis_client.get(f"token:{token}")
    return json.loads(data) if data else None

def set_cached_token_data(token: str, data: dict):
    redis_client.set(f"token:{token}", json.dumps(data))

def delete_cached_token(token: str):
    redis_client.delete(f"token:{token}")
