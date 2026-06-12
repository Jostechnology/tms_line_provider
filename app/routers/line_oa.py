import base64
import traceback
from datetime import datetime, timezone
from io import BytesIO
from typing import List, Optional
from urllib.parse import quote

import qrcode
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
from app.repositories.delivery_log_repository import log_push
from app.services.account_link import mint_link_code, CODE_TTL_SECONDS
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

class LinkStartRequest(BaseModel):
    company_id:   str
    tms_username: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _qr_base64(data: str) -> str:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=3)
    qr.add_data(data)
    qr.make(fit=True)
    buf = BytesIO()
    qr.make_image(fill_color="#06C755", back_color="white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


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

    # usernames → LINE user ids, scoped to this tenant (line_ids are per-channel).
    line_id_by_user = get_line_ids_by_tms_ids(str(body.company_id), body.tms_usernames)
    unlinked = [u for u in body.tms_usernames if u not in line_id_by_user]
    line_ids = list(set(line_id_by_user.values()))

    print(
        f"[notify] company={body.company_id} requested={len(body.tms_usernames)} "
        f"linked={len(line_ids)} unlinked={unlinked}"
    )

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

    # One delivery_logs row per linked recipient. trip_id/event_type are synthetic
    # — this is a TMS-user push, not an event-driven customer card. Best-effort:
    # a logging failure must not fail an already-delivered notify.
    now = datetime.now(timezone.utc)
    for tms_username, line_id in line_id_by_user.items():
        try:
            log_push(
                company_id=str(body.company_id),
                trip_id="-",
                event_type="line-oa.notify",
                customer_code=tms_username,
                line_user_id=line_id,
                status="sent",
                occurred_at=now,
            )
        except Exception as e:
            print(f"[notify] log_push failed user={tms_username}: {e}")

    return {"success": True, "recipients": sent, "unlinked": unlinked}


@router.post("/link/start", dependencies=[Depends(verify_required)])
def link_start(body: LinkStartRequest):
    """Begin account-linking for a TMS user *through the tenant's own OA*.

    A LINE userId is per-provider, so the only id usable for pushing via the
    customer's OA is the one that OA's webhook reports. We mint a one-time code,
    and the user sends it to the OA (the deep link pre-fills it). The webhook
    then binds tms_username ↔ userId with the correctly-scoped id.

    Returns the code, a LINE deep link into the OA chat (pre-filled), and a QR of
    that link. TMS shows whichever fits its UI.
    """
    oas = get_tokens_by_company(str(body.company_id))
    if not oas:
        raise HTTPException(status_code=404, detail=f"Unknown company_id — no registered OA for Linking : Your group={(str(body.company_id))}")

    info = get_line_bot_info(oas[0].channel_access_token)
    if not info or not info.get("basicId"):
        raise HTTPException(status_code=502, detail="OA credentials invalid; re-sync the OA")
    basic_id = info["basicId"]   # e.g. "@123abcd"

    code = mint_link_code(str(body.company_id), body.tms_username)
    # Deep link opens the OA 1:1 chat with the code pre-filled as the message.
    deep_link = f"https://line.me/R/oaMessage/{basic_id}/?{quote(code)}"

    return {
        "success":        True,
        "company_id":     body.company_id,
        "tms_username":   body.tms_username,
        "code":           code,
        "deep_link":      deep_link,
        "qr_code_base64": _qr_base64(deep_link),
        "oa_basic_id":    basic_id,
        "expires_in":     f"{CODE_TTL_SECONDS // 60} minutes",
    }
