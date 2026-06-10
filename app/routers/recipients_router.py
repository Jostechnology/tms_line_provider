from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.auth import verify_required
from app.repositories.recipient_repository import (
    upsert_recipient,
    get_recipient,
    get_recipients_by_user,
    opt_out,
)
from app.database import SessionLocal, RecipientLink

router = APIRouter(prefix="/api/recipients", tags=["Recipients"])


# ─── Request / Response models ────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    company_id:    str
    line_user_id:  str
    customer_code: Optional[str] = None   # optional — LINE OAuth flow won't have it
    oa_token:      Optional[str] = None   # OA the user registered through
    tms_username:  Optional[str] = None   # TMS account


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/register", dependencies=[Depends(verify_required)])
async def register_recipient(body: RegisterRequest):
    """
    Create or update a LINE user ↔ company ↔ OA ↔ TMS account link.
    Idempotent — calling again with same company_id + customer_code (or tms_username) updates the row.
    """
    row = upsert_recipient(
        company_id=body.company_id,
        line_user_id=body.line_user_id,
        customer_code=body.customer_code,
        oa_token=body.oa_token,
        tms_username=body.tms_username,
    )
    return {
        "success":       True,
        "company_id":    row.company_id,
        "line_user_id":  row.line_user_id,
        "customer_code": row.customer_code,
        "oa_token":      row.oa_token,
        "tms_username":  row.tms_username,
        "opted_in":      row.opted_in,
    }


@router.get("", dependencies=[Depends(verify_required)])
async def list_recipients(
    company_id: str = Query(...),
    limit:      int = Query(100, ge=1, le=500),
):
    with SessionLocal() as db:
        rows = (
            db.query(RecipientLink)
            .filter(
                RecipientLink.company_id == company_id,
                RecipientLink.opted_in   == True,
            )
            .order_by(RecipientLink.created_at.desc())
            .limit(limit)
            .all()
        )
    return {
        "success":    True,
        "company_id": company_id,
        "count":      len(rows),
        "recipients": [
            {
                "id":            r.id,
                "line_user_id":  r.line_user_id,
                "customer_code": r.customer_code,
                "oa_token":      r.oa_token,
                "tms_username":  r.tms_username,
                "opted_in":      r.opted_in,
                "created_at":    r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/{line_user_id}", dependencies=[Depends(verify_required)])
async def get_recipient_by_user(
    line_user_id: str,
    company_id:   str = Query(...),
):
    rows = get_recipients_by_user(company_id, line_user_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No links found for this user")
    return {
        "success":      True,
        "line_user_id": line_user_id,
        "company_id":   company_id,
        "links": [
            {
                "id":            r.id,
                "customer_code": r.customer_code,
                "oa_token":      r.oa_token,
                "tms_username":  r.tms_username,
                "opted_in":      r.opted_in,
            }
            for r in rows
        ],
    }


@router.delete("", dependencies=[Depends(verify_required)])
async def remove_recipient(
    company_id:   str = Query(...),
    line_user_id: str = Query(...),
):
    success = opt_out(company_id, line_user_id)
    if not success:
        raise HTTPException(status_code=404, detail="No links found for this user")
    return {"success": True, "message": "User opted out successfully"}
