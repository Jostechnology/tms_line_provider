from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.auth import verify_required

from app.routers import line_oa, routers_webhook, tracking, recipients_router, line_tms_router, line_connect
from app.events.consumer import router as events_router
from app.repositories.delivery_log_repository import get_logs_by_tenant, get_logs_by_trip



@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="TMS LINE Provider",
    description="Notification & Tracking Service — LINE OA registry, webhook intake, event consumer",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(line_oa.router)
app.include_router(routers_webhook.router)
app.include_router(events_router)
app.include_router(tracking.router)
app.include_router(recipients_router.router)
app.include_router(line_tms_router.router)
app.include_router(line_connect.router)



@app.get("/health")
async def health():
    return {"status": "ok", "success" : True}


# ─── Delivery log endpoints ───────────────────────────────────────────────────

@app.get("/api/logs/tenant", dependencies=[Depends(verify_required)])
async def logs_by_tenant(
    company_id: str = Query(...),
    limit:      int = Query(100, ge=1, le=500),
):
    """Last N push attempts for a tenant. Useful for ops dashboards."""
    rows = get_logs_by_tenant(company_id, limit=limit)
    return {
        "success":    True,
        "company_id": company_id,
        "count":      len(rows),
        "logs": [
            {
                "id":            r.id,
                "trip_id":       r.trip_id,
                "event_type":    r.event_type,
                "customer_code": r.customer_code,
                "line_user_id":  r.line_user_id,
                "status":        r.status,
                "error_detail":  r.error_detail,
                "occurred_at":   r.occurred_at.isoformat() if r.occurred_at else None,
                "pushed_at":     r.pushed_at.isoformat() if r.pushed_at else None,
            }
            for r in rows
        ],
    }


@app.get("/api/logs/trip", dependencies=[Depends(verify_required)])
async def logs_by_trip(
    trip_id:    str = Query(...),
    company_id: str = Query(...),
):
    """All push attempts for a specific trip. Useful for debugging a single delivery."""
    rows = get_logs_by_trip(trip_id, company_id)
    return {
        "success":    True,
        "trip_id":    trip_id,
        "company_id": company_id,
        "count":      len(rows),
        "logs": [
            {
                "id":            r.id,
                "event_type":    r.event_type,
                "customer_code": r.customer_code,
                "line_user_id":  r.line_user_id,
                "status":        r.status,
                "error_detail":  r.error_detail,
                "occurred_at":   r.occurred_at.isoformat() if r.occurred_at else None,
                "pushed_at":     r.pushed_at.isoformat() if r.pushed_at else None,
            }
            for r in rows
        ],
    }
