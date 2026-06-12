from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import verify_required
from app.database import SessionLocal, LineTmsLink

router = APIRouter(prefix="/api/line-tms", tags=["LINE TMS Mapping"])


# ─── Request model ────────────────────────────────────────────────────────────

class LinkRequest(BaseModel):
    tms_id:  str
    line_id: str


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/link", dependencies=[Depends(verify_required)])
async def link_tms_line(body: LinkRequest):
    """
    Create or update the mapping between a TMS user ID and a LINE user ID.
    Called by the mock auth server (and real LINE OAuth server) after authorization.
    Idempotent — calling again with same tms_id updates the line_id.
    """
    with SessionLocal() as db:
        row = db.query(LineTmsLink).filter(LineTmsLink.tms_id == body.tms_id).first()

        if row:
            row.line_id = body.line_id
        else:
            row = LineTmsLink(
                tms_id=body.tms_id,
                line_id=body.line_id,
            )
            db.add(row)

        db.commit()
        db.refresh(row)

    return {
        "success": True,
        "tms_id":  row.tms_id,
        "line_id": row.line_id,
    }


@router.get("/link", dependencies=[Depends(verify_required)])
async def get_link(tms_id: str):
    """Get the LINE user ID mapped to a TMS user ID."""
    with SessionLocal() as db:
        row = db.query(LineTmsLink).filter(LineTmsLink.tms_id == tms_id).first()

    if not row:
        raise HTTPException(status_code=404, detail="No LINE ID linked for this TMS user")

    return {
        "success": True,
        "tms_id":  row.tms_id,
        "line_id": row.line_id,
    }
