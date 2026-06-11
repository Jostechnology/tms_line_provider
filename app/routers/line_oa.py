import traceback
from typing import Optional
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
from app.extensions import redis_client, set_cached_token_data, delete_cached_token
from app.database import SessionLocal, RecipientLink

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
    token:    str
    tms_usernames: list[str]
    payload:  dict


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

    row, created = register_company_token(
        company_id=str(body.company_id),
        channel_secret=body.channel_secret,
        channel_access_token=body.channel_access_token,
    )

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
    return {
        "success":    True,
        "company_id": body.company_id,
        "oas": [
            {
                "token":       row.token,
                "webhook_url": f"{SERVICE_BASE_URL}/webhook/{row.token}",
                "created_at":  row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "count": len(rows),
    }

@router.post("/notify", dependencies=[Depends(verify_required)])
async def notify_line_oa(body: NotifyRequest):
    """Resolve TMS usernames → LINE user IDs, then multicast a Flex Message via LINE API."""
    if not body.tms_usernames:
        return {"success": True, "message": "no recipients"}

    row = get_company_by_token(body.token)
    if not row:
        raise HTTPException(status_code=404, detail="Token not found.")

    # Resolve tms_usernames → line_user_ids via RecipientLink
    with SessionLocal() as db:
        links = (
            db.query(RecipientLink)
            .filter(
                RecipientLink.tms_username.in_(body.tms_usernames),
                RecipientLink.opted_in == True,
            )
            .all()
        )

    line_ids = [link.line_user_id for link in links if link.line_user_id]

    if not line_ids:
        return {"success": True, "message": "no linked LINE accounts found for given usernames"}

    try:
        res = http_requests.post(
            "https://api.line.me/v2/bot/message/multicast",
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {row.channel_access_token}",
            },
            json={
                "to":       line_ids,
                "messages": [body.payload],
            },
            timeout=10,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LINE multicast unreachable: {e}")

    if res.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"LINE multicast failed ({res.status_code}): {res.text[:200]}",
        )

    return {
        "success":    True,
        "recipients": len(line_ids),
        "unlinked":   [u for u in body.tms_usernames if u not in {l.tms_username for l in links}],
    }