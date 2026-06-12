"""
message_templates.py — LINE Flex Message bubbles, Thai copy.

Each function returns a dict ready to put directly into the LINE Push API
messages array (type: "flex"). notification_service passes it as-is.

Upgrade path: edit card layouts here only — consumer.py and
notification_service.py are untouched.
"""

import os

from app.schemas.events_schema import (
    WoStartedEvent,
    StopArrivedEvent,
    StopDeliveredEvent,
    StopFailedEvent,
    EtaSlippedEvent,
    StopProjectedMissEvent,
    StopStalledEvent,
    StopDepartedEvent,
    StopLoadStartEvent,
    StopLoadEndEvent,
)


# ─── Builder helpers ──────────────────────────────────────────────────────────

def _text(text: str, size: str = "sm", color: str = "#555555", weight: str = "regular") -> dict:
    return {"type": "text", "text": text, "size": size, "color": color, "weight": weight, "wrap": True}


def _row(label: str, value: str) -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": "#aaaaaa", "flex": 2},
            {"type": "text", "text": value, "size": "sm", "color": "#333333", "flex": 5, "wrap": True},
        ],
        "margin": "sm",
    }


def _header(emoji: str, title: str, color: str = "#1DB954") -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": color,
        "paddingAll": "16px",
        "contents": [
            {
                "type": "text",
                "text": f"{emoji}  {title}",
                "color": "#ffffff",
                "size": "lg",
                "weight": "bold",
                "wrap": True,
            }
        ],
    }


def _tracking_footer(trip_id: str) -> dict:
    base_url = os.getenv("SERVICE_BASE_URL", "http://localhost:5002")
    url = f"{base_url}/tracking?trip_id={trip_id}"
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "12px",
        "contents": [
            {
                "type": "button",
                "action": {
                    "type": "uri",
                    "label": "🗺️ ดูเส้นทางการจัดส่ง",
                    "uri": url,
                },
                "style": "primary",
                "color": "#1a73e8",
                "height": "sm",
            }
        ],
    }


def _bubble(header: dict, rows: list, alt_text: str, trip_id: str = None) -> dict:
    contents = {
        "type": "bubble",
        "size": "kilo",
        "header": header,
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "16px",
            "spacing": "sm",
            "contents": rows,
        },
    }
    if trip_id:
        contents["footer"] = _tracking_footer(trip_id)
    return {
        "type": "flex",
        "altText": alt_text,
        "contents": contents,
    }


# ─── Event templates ──────────────────────────────────────────────────────────

def wo_started(event: WoStartedEvent) -> dict:
    return _bubble(
        header=_header("🚚", "รถออกแล้ว!", color="#1a73e8"),
        rows=[
            _row("พนักงานขับรถ", event.driver_name),
            _row("ทะเบียนรถ", event.vehicle_plate),
            _row("หมายเลขงาน", event.trip_id),
        ],
        alt_text=f"🚚 รถออกแล้ว! พนักงาน: {event.driver_name} ทะเบียน: {event.vehicle_plate}",
        trip_id=event.trip_id,
    )


def stop_arrived(event: StopArrivedEvent) -> dict:
    timing = ""
    if event.eta_minutes is not None:
        if event.eta_minutes < 0:
            timing = f"มาก่อนกำหนด {abs(event.eta_minutes)} นาที"
        elif event.eta_minutes > 0:
            timing = f"ช้ากว่ากำหนด {event.eta_minutes} นาที"
        else:
            timing = "ตรงเวลา"

    rows = [
        _row("สถานที่", event.stop_address),
        _row("หมายเลขงาน", event.trip_id),
    ]
    if timing:
        rows.append(_row("เวลา", timing))

    return _bubble(
        header=_header("📍", "รถมาถึงแล้ว", color="#0f9d58"),
        rows=rows,
        alt_text=f"📍 รถมาถึงแล้ว — {event.stop_address}",
        trip_id=event.trip_id,
    )


def stop_delivered(event: StopDeliveredEvent) -> dict:
    rows = [
        _row("สถานที่", event.stop_address),
        _row("หมายเลขงาน", event.trip_id),
    ]
    if event.epod_image_url:
        rows.append(_row("หลักฐานการส่ง", event.epod_image_url))

    return _bubble(
        header=_header("✅", "ส่งสินค้าเรียบร้อยแล้ว", color="#0f9d58"),
        rows=rows,
        alt_text=f"✅ ส่งสินค้าเรียบร้อย — {event.stop_address}",
        trip_id=event.trip_id,
    )


def stop_failed(event: StopFailedEvent) -> dict:
    return _bubble(
        header=_header("❌", "ไม่สามารถส่งสินค้าได้", color="#d93025"),
        rows=[
            _row("สาเหตุ", event.failure_reason),
            _row("สถานที่", event.stop_address),
            _row("หมายเลขงาน", event.trip_id),
            _text("กรุณาติดต่อเจ้าหน้าที่เพื่อนัดหมายใหม่", size="sm", color="#888888"),
        ],
        alt_text=f"❌ ส่งสินค้าไม่สำเร็จ — {event.failure_reason}",
        trip_id=event.trip_id,
    )


def eta_slipped(event: EtaSlippedEvent) -> dict:
    return _bubble(
        header=_header("⏰", "เวลาจัดส่งล่าช้า", color="#f4a711"),
        rows=[
            _row("ล่าช้าประมาณ", f"{event.slip_minutes} นาที"),
            _row("หมายเลขงาน", event.trip_id),
            _text("ขออภัยในความไม่สะดวก", size="sm", color="#888888"),
        ],
        alt_text=f"⏰ การจัดส่งล่าช้า {event.slip_minutes} นาที — งาน {event.trip_id}",
        trip_id=event.trip_id,
    )


def stop_projected_miss(event: StopProjectedMissEvent) -> dict:
    return _bubble(
        header=_header("⚠️", "คาดว่าการจัดส่งจะล่าช้า", color="#f4a711"),
        rows=[
            _row("ล่าช้าประมาณ", f"{event.projected_late_minutes} นาที"),
            _row("สถานที่", event.stop_address),
            _row("หมายเลขงาน", event.trip_id),
        ],
        alt_text=f"⚠️ คาดว่าจะล่าช้า {event.projected_late_minutes} นาที — {event.stop_address}",
        trip_id=event.trip_id,
    )


def stop_stalled(event: StopStalledEvent) -> dict:
    rows = [
        _row("หยุดนิ่งมาแล้ว", f"{event.stalled_minutes} นาที"),
        _row("หมายเลขงาน", event.trip_id),
    ]
    if event.last_known_address:
        rows.append(_row("ตำแหน่งล่าสุด", event.last_known_address))
    rows.append(_text("กำลังตรวจสอบสถานการณ์", size="sm", color="#888888"))

    return _bubble(
        header=_header("⚠️", "รถหยุดนิ่งผิดปกติ", color="#d93025"),
        rows=rows,
        alt_text=f"⚠️ รถหยุดนิ่ง {event.stalled_minutes} นาที — งาน {event.trip_id}",
        trip_id=event.trip_id,
    )


# ─── Silent events — return None, no push ────────────────────────────────────

def stop_departed(event: StopDepartedEvent) -> None:
    return None


def stop_load_start(event: StopLoadStartEvent) -> None:
    return None


def stop_load_end(event: StopLoadEndEvent) -> None:
    return None
