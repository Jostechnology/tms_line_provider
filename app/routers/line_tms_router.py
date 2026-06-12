from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import verify_required
from app.database import SessionLocal, LineTmsLink

router = APIRouter(prefix="/api/line-tms", tags=["LINE TMS Mapping"])


# ─── Request model ────────────────────────────────────────────────────────────

class LinkRequest(BaseModel):
    company_id: str
    tms_id:     str
    line_id:    str
    oa_token:   Optional[str] = None


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/link", dependencies=[Depends(verify_required)])
async def link_tms_line(body: LinkRequest):
    """
    Create or update the mapping between a TMS user and a LINE user ID, scoped to
    the company's OA channel. Backfill/manual path (the live path is the OA
    webhook). Idempotent on (company_id, tms_id).

    line_id is per-channel — supplying the wrong company_id here binds an id that
    can't be pushed to. oa_token, if given, records the channel it belongs to.
    """
    with SessionLocal() as db:
        row = db.query(LineTmsLink).filter(
            LineTmsLink.company_id == body.company_id,
            LineTmsLink.tms_id == body.tms_id,
        ).first()

        if row:
            row.line_id = body.line_id
            if body.oa_token is not None:
                row.oa_token = body.oa_token
        else:
            row = LineTmsLink(
                company_id=body.company_id,
                tms_id=body.tms_id,
                line_id=body.line_id,
                oa_token=body.oa_token,
            )
            db.add(row)

        db.commit()
        db.refresh(row)

    return {
        "success":    True,
        "company_id": row.company_id,
        "tms_id":     row.tms_id,
        "line_id":    row.line_id,
    }


@router.get("/link", dependencies=[Depends(verify_required)])
async def get_link(company_id: str = Query(...), tms_id: str = Query(...)):
    """Get the LINE user ID mapped to a TMS user within a company's OA channel."""
    with SessionLocal() as db:
        row = db.query(LineTmsLink).filter(
            LineTmsLink.company_id == company_id,
            LineTmsLink.tms_id == tms_id,
        ).first()

    if not row:
        raise HTTPException(status_code=404, detail="No LINE ID linked for this TMS user")

    return {
        "success":    True,
        "company_id": row.company_id,
        "tms_id":     row.tms_id,
        "line_id":    row.line_id,
    }
