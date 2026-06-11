"""
Test script for send_notification using real message_templates.
Place this file in: tms_line_provider/ (root, next to main.py)
Run with: python test_notification.py
"""
import sys
import os
from datetime import datetime, timezone

# ─── Config — edit these ──────────────────────────────────────────────────────
LINE_PROVIDER_URL = "http://localhost:5002"
LINE_ADMIN_TOKEN  = "secret123"
WEBHOOK_TOKEN     = "GS-w44R0clqg340LTWVwCA-8PLHc6NVzP2-E-e4ujwU"
TMS_USERNAMES     = ["john.doe", "ghost.user"]

sys.path.insert(0, os.path.dirname(__file__))

from app.services.message_templates import (
    wo_started, stop_arrived, stop_delivered, stop_failed,
    eta_slipped, stop_projected_miss, stop_stalled,
)
from app.schemas.events_schema import (
    WoStartedEvent, StopArrivedEvent, StopDeliveredEvent, StopFailedEvent,
    EtaSlippedEvent, StopProjectedMissEvent, StopStalledEvent,
)

import requests

class _Client:
    def __init__(self, base_url, admin_token):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {admin_token}",
        })

    def _post(self, path, payload):
        r = self.session.post(f"{self.base_url}{path}", json=payload, timeout=30)
        if r.status_code == 200:
            return r.json()
        raise RuntimeError(f"{path} → {r.status_code}: {r.text[:200]}")

    def send_notification(self, tms_usernames, token, payload):
        if not tms_usernames:
            return {"success": True, "message": "no recipients"}
        return self._post("/api/line-oa/notify", {
            "token":         token,
            "tms_usernames": tms_usernames,
            "payload":       payload,
        })


client = _Client(LINE_PROVIDER_URL, LINE_ADMIN_TOKEN)

NOW = datetime.now(timezone.utc)
BASE = dict(tenant_id="3", trip_id="TRIP-001", occurred_at=NOW, customer_code="CUST-001")
STOP = dict(stop_id="STOP-001", stop_address="123 ถนนสุขุมวิท", **BASE)

tests = [
    ("wo_started",          wo_started(WoStartedEvent(**BASE, driver_name="สมชาย", vehicle_plate="กข 1234"))),
    ("stop_arrived",        stop_arrived(StopArrivedEvent(**STOP, eta_minutes=-5))),
    ("stop_delivered",      stop_delivered(StopDeliveredEvent(**STOP, epod_image_url=None))),
    ("stop_failed",         stop_failed(StopFailedEvent(**STOP, failure_reason="ไม่มีคนรับ"))),
    ("eta_slipped",         eta_slipped(EtaSlippedEvent(**BASE, stop_id="STOP-001", original_eta=NOW, revised_eta=NOW, slip_minutes=15))),
    ("stop_projected_miss", stop_projected_miss(StopProjectedMissEvent(**STOP, projected_eta=NOW, planned_eta=NOW, projected_late_minutes=20))),
    ("stop_stalled",        stop_stalled(StopStalledEvent(**BASE, stop_id="STOP-001", stalled_minutes=10, last_known_address="ถนนพระราม 9"))),
]

print(f"\nSending {len(tests)} test notifications to {TMS_USERNAMES}\n")
for name, payload in tests:
    if payload is None:
        print(f"  SKIP  {name} (silent event)")
        continue
    try:
        result = client.send_notification(TMS_USERNAMES, WEBHOOK_TOKEN, payload)
        print(f"  OK    {name} → {result}")
    except Exception as e:
        print(f"  FAIL  {name} → {e}")

print("\nDone.")