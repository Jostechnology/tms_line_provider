import traceback
from typing import List, Optional
import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import verify_required
from app.config import SERVICE_BASE_URL
from app.repositories.token_repository import (
    get_company_by_token,
    register_company_token,
    update_company_token,
    rotate_token,
    revoke_token,
    get_tokens_by_company,
)
from app.repositories.line_tms_repository import get_line_ids_by_tms_ids
from app.extensions import redis_client, set_cached_token_data, delete_cached_token

LINE_MULTICAST_URL = "https://api.line.me/v2/bot/message/multicast"

router = APIRouter(prefix="/api/line-oa", tags=["LINE OA Registry"])


# ─── Request models ───────────────────────────────────────────────────────────

class SyncRequest(BaseModel):
    company_id:           str
    channel_secret:       str
    channel_access_token: str

class UpdateRequest(BaseModel):
    token:                str
    channel_secret:       str
    channel_access_token: str

class TokenRequest(BaseModel):
    token: str

class CompanyRequest(BaseModel):
    company_id: str

class NotifyRequest(BaseModel):
    company_id:    str            # TMS group_id; resolved to the tenant's OA
    tms_usernames: List[str]      # resolved to LINE user ids via line_tms_links
    payload:       dict           # a LINE message object (Flex), pushed as-is


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_line_bot_info(channel_access_token: str) -> Optional[dict]:
    try:
        res = http_requests.get(
            "https://api.line.me/v2/bot/info",
            headers={"Authorization": f"Bearer {channel_access_token}"},
            timeout=10,
        )
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/sync", dependencies=[Depends(verify_required)])
async def sync_line_oa(body: SyncRequest):
    bot_info = get_line_bot_info(body.channel_access_token)
    if not bot_info:
        raise HTTPException(status_code=400, detail="Invalid LINE credentials. Please check your channel_access_token.")

    try:
        row, created = register_company_token(
            company_id=str(body.company_id),
            channel_secret=body.channel_secret,
            channel_access_token=body.channel_access_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    set_cached_token_data(row.token, {
        "company_id":           row.company_id,
        "channel_secret":       body.channel_secret,
        "channel_access_token": body.channel_access_token,
    })

    return {
        "success":      True,
        "company_id":   body.company_id,
        "oa_name":      bot_info.get("displayName"),
        "oa_basic_id":  bot_info.get("basicId"),
        "token":        row.token,
        "webhook_url":  f"{SERVICE_BASE_URL}/webhook/{row.token}",
        "message":      "Token generated. Paste the webhook_url into your LINE OA Developer Console.",
    }


@router.post("/update", dependencies=[Depends(verify_required)])
async def update_line_oa(body: UpdateRequest):
    bot_info = get_line_bot_info(body.channel_access_token)
    if not bot_info:
        raise HTTPException(status_code=400, detail="Invalid LINE credentials. Please check your channel_access_token.")

    row = update_company_token(body.token, body.channel_secret, body.channel_access_token)
    if not row:
        raise HTTPException(status_code=404, detail="Token not found.")

    set_cached_token_data(body.token, {
        "company_id":           row.company_id,
        "channel_secret":       body.channel_secret,
        "channel_access_token": body.channel_access_token,
    })

    return {
        "success":     True,
        "company_id":  row.company_id,
        "token":       body.token,
        "webhook_url": f"{SERVICE_BASE_URL}/webhook/{body.token}",
        "message":     "Credentials updated. Your webhook_url remains the same.",
    }


@router.post("/rotate", dependencies=[Depends(verify_required)])
async def rotate_line_oa_token(body: TokenRequest):
    delete_cached_token(body.token)

    new_token = rotate_token(body.token)
    if new_token is None:
        raise HTTPException(status_code=404, detail="Token not found. Call /api/line-oa/sync first.")

    return {
        "success":     True,
        "token":       new_token,
        "webhook_url": f"{SERVICE_BASE_URL}/webhook/{new_token}",
        "message":     "Token rotated. Update the webhook_url in your LINE OA Developer Console.",
    }


@router.post("/revoke", dependencies=[Depends(verify_required)])
async def revoke_line_oa(body: TokenRequest):
    delete_cached_token(body.token)
    success = revoke_token(body.token)

    if not success:
        raise HTTPException(status_code=404, detail="Token not found.")

    return {"success": True, "message": "OA registration removed."}


@router.post("/list", dependencies=[Depends(verify_required)])
async def list_line_oas(body: CompanyRequest):
    rows = get_tokens_by_company(str(body.company_id))

    oas = []
    for row in rows:
        # Live LINE lookup so the settings page can show *which* OA is connected
        # (name + avatar), and whether the stored credentials are still valid.
        info = get_line_bot_info(row.channel_access_token)
        oas.append({
            "token":          row.token,
            "webhook_url":    f"{SERVICE_BASE_URL}/webhook/{row.token}",
            "created_at":     row.created_at.isoformat() if row.created_at else None,
            "oa_name":        info.get("displayName") if info else None,
            "oa_basic_id":    info.get("basicId") if info else None,
            "oa_picture_url": info.get("pictureUrl") if info else None,
            # False ⇒ credentials no longer authenticate with LINE (re-sync needed).
            "active":         info is not None,
        })

    return {
        "success":    True,
        "company_id": body.company_id,
        "oas":        oas,
        "count":      len(rows),
    }


@router.post("/notify", dependencies=[Depends(verify_required)])
def notify(body: NotifyRequest):
    """Internal-user push: deliver a pre-rendered LINE message to a tenant's TMS users.

    TMS owns recipient selection + rendering and sends us company_id (group_id),
    the target tms_usernames, and a ready LINE message object. We resolve
    company_id → the tenant's OA channel token, usernames → LINE user ids (via
    line_tms_links), and multicast. Unlinked usernames are skipped, not an error
    — they simply haven't completed the LINE account-linking flow yet.

    (Customer-facing delivery cards go through POST /api/events/{company_id},
    which resolves by customer_code and renders provider-side — a separate path.)
    """
    # group_id → the tenant's OA channel token (one OA per company by policy).
    oas = get_tokens_by_company(str(body.company_id))
    if not oas:
        raise HTTPException(status_code=404, detail="Unknown company_id — no registered OA")
    channel_access_token = oas[0].channel_access_token

    # usernames → LINE user ids.
    line_id_by_user = get_line_ids_by_tms_ids(body.tms_usernames)
    unlinked = [u for u in body.tms_usernames if u not in line_id_by_user]
    line_ids = list(set(line_id_by_user.values()))

    if not line_ids:
        return {"success": True, "recipients": 0, "unlinked": unlinked,
                "message": "no linked LINE recipients"}

    # LINE multicast caps `to` at 500 ids per call.
    sent = 0
    for i in range(0, len(line_ids), 500):
        batch = line_ids[i:i + 500]
        resp = http_requests.post(
            LINE_MULTICAST_URL,
            headers={
                "Authorization": f"Bearer {channel_access_token}",
                "Content-Type":  "application/json",
            },
            json={"to": batch, "messages": [body.payload]},
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"LINE multicast failed: {resp.status_code} {resp.text[:200]}",
            )
        sent += len(batch)

    return {"success": True, "recipients": sent, "unlinked": unlinked}
