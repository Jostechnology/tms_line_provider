"""One-time codes for linking a TMS user to their LINE userId *through the
customer's own OA*.

Why this exists: a LINE userId is unique per provider. To push to a user via an
OA you need their userId as the OA's provider sees it — which only the OA's own
webhook can produce. So linking rides the OA: TMS mints a code here, the user
sends it to the OA, and the webhook binds tms_id ↔ userId with the correct id.

Codes are company-scoped so a code minted for one tenant can't be redeemed
through another tenant's OA.
"""
import secrets
from typing import Optional

from app.extensions import redis_client

_CODE_PREFIX = "link:code:"
CODE_TTL_SECONDS = 15 * 60


def _key(company_id: str, code: str) -> str:
    return f"{_CODE_PREFIX}{company_id}:{code}"


def mint_link_code(company_id: str, tms_username: str) -> str:
    """Create a short, single-use code bound to (company_id, tms_username)."""
    code = "LINK-" + secrets.token_hex(3).upper()   # e.g. LINK-9F3A2B
    redis_client.setex(_key(company_id, code), CODE_TTL_SECONDS, tms_username)
    return code


def consume_link_code(company_id: str, code: str) -> Optional[str]:
    """Redeem a code for its tms_username and burn it. None if unknown/expired."""
    key = _key(company_id, code)
    tms_username = redis_client.get(key)
    if tms_username:
        redis_client.delete(key)
    return tms_username
