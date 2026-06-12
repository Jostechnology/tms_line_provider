#!/usr/bin/env python3
"""
mock_publisher.py — Dev & test harness for the event consumer.

Usage:
    # Fire one specific event type (--tenant is the OA token):
    python mock_publisher.py --event wo.started --tenant <oa_token>

    # Fire all event types in sequence (smoke test):
    python mock_publisher.py --all --tenant <oa_token>

    # List available event types:
    python mock_publisher.py --list

    # Override target base URL:
    python mock_publisher.py --event eta.slipped --tenant <oa_token> --url http://localhost:5002

Env vars (can also be set in .env):
    CONSUMER_BASE_URL  — default: http://localhost:5002
    MOCK_OA_TOKEN      — OA token to use as --tenant default
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

CONSUMER_BASE_URL = os.getenv("CONSUMER_BASE_URL", "http://localhost:5002")
MOCK_OA_TOKEN     = os.getenv("MOCK_OA_TOKEN", "")

NOW = datetime.now(timezone.utc)


# ─── Sample payloads ─────────────────────────────────────────────────────────
# tenant_id is omitted — the consumer derives it from the OA token in the URL

def make_payloads() -> dict[str, dict]:
    return {
        "wo.started": {
            "event_type":    "wo.started",
            "trip_id":       "TRIP-001",
            "occurred_at":   NOW.isoformat(),
            "customer_code": "W001",
            "driver_name":   "สมชาย ใจดี",
            "vehicle_plate": "กข-1234",
        },
        "stop.arrived": {
            "event_type":    "stop.arrived",
            "trip_id":       "TRIP-001",
            "occurred_at":   NOW.isoformat(),
            "stop_id":       "STOP-001",
            "customer_code": "W001",
            "stop_address":  "123 ถนนสุขุมวิท กรุงเทพฯ",
            "eta_minutes":   -5,
        },
        "stop.delivered": {
            "event_type":     "stop.delivered",
            "trip_id":        "TRIP-001",
            "occurred_at":    NOW.isoformat(),
            "stop_id":        "STOP-001",
            "customer_code":  "W001",
            "stop_address":   "123 ถนนสุขุมวิท กรุงเทพฯ",
            "epod_image_url": "https://example.com/epod/STOP-001.jpg",
        },
        "stop.failed": {
            "event_type":     "stop.failed",
            "trip_id":        "TRIP-001",
            "occurred_at":    NOW.isoformat(),
            "stop_id":        "STOP-002",
            "customer_code":  "W002",
            "stop_address":   "456 ถนนพระราม 4 กรุงเทพฯ",
            "failure_reason": "ไม่มีผู้รับของ",
        },
        "stop.departed": {
            "event_type":    "stop.departed",
            "trip_id":       "TRIP-001",
            "occurred_at":   NOW.isoformat(),
            "stop_id":       "STOP-001",
            "customer_code": "W001",
        },
        "stop.load_start": {
            "event_type":    "stop.load_start",
            "trip_id":       "TRIP-002",
            "occurred_at":   NOW.isoformat(),
            "stop_id":       "STOP-010",
            "customer_code": "W003",
            "stop_address":  "คลังสินค้า A นิคมอมตะซิตี้",
        },
        "stop.load_end": {
            "event_type":    "stop.load_end",
            "trip_id":       "TRIP-002",
            "occurred_at":   NOW.isoformat(),
            "stop_id":       "STOP-010",
            "customer_code": "W003",
            "stop_address":  "คลังสินค้า A นิคมอมตะซิตี้",
        },
        "eta.slipped": {
            "event_type":    "eta.slipped",
            "trip_id":       "TRIP-001",
            "occurred_at":   NOW.isoformat(),
            "stop_id":       "STOP-003",
            "customer_code": "W001",
            "original_eta":  NOW.isoformat(),
            "revised_eta":   (NOW + timedelta(minutes=45)).isoformat(),
            "slip_minutes":  45,
        },
        "stop.projected_miss": {
            "event_type":             "stop.projected_miss",
            "trip_id":                "TRIP-001",
            "occurred_at":            NOW.isoformat(),
            "stop_id":                "STOP-004",
            "customer_code":          "W004",
            "stop_address":           "789 ถนนบางนา-ตราด",
            "projected_eta":          (NOW + timedelta(hours=2)).isoformat(),
            "planned_eta":            (NOW + timedelta(hours=1)).isoformat(),
            "projected_late_minutes": 60,
        },
        "stop.stalled": {
            "event_type":          "stop.stalled",
            "trip_id":             "TRIP-001",
            "occurred_at":         NOW.isoformat(),
            "stop_id":             "STOP-005",
            "customer_code":       "W001",
            "stalled_minutes":     25,
            "last_known_address":  "แยกอโศก กรุงเทพฯ",
        },
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def send_event(payload: dict, base_url: str, oa_token: str) -> None:
    event_type = payload.get("event_type", "unknown")
    url = f"{base_url}/api/events/{oa_token}"

    print(f"\n{'─'*60}")
    print(f"  Firing: {event_type}")
    print(f"  To:     {url}")
    print(f"  Body:   {json.dumps(payload, ensure_ascii=False, indent=4)}")
    print(f"{'─'*60}")

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        status_symbol = "✓" if resp.status_code < 300 else "✗"
        print(f"  {status_symbol} Response [{resp.status_code}]: {resp.text[:300]}")
    except requests.exceptions.ConnectionError:
        print(f"  ✗ Connection refused — is the service running at {base_url}?")
    except Exception as e:
        print(f"  ✗ Error: {e}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Mock event publisher — fires trip events scoped to an OA token."
    )
    parser.add_argument(
        "--event", "-e",
        help="Event type to fire (e.g. stop.delivered)",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Fire all event types in sequence",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available event types and exit",
    )
    parser.add_argument(
        "--url",
        default=CONSUMER_BASE_URL,
        help=f"Base URL of the service (default: {CONSUMER_BASE_URL})",
    )
    parser.add_argument(
        "--tenant",
        default=MOCK_OA_TOKEN,
        required=False,
        help="OA token — identifies which company and OA to fire events for",
    )

    args = parser.parse_args()
    payloads = make_payloads()

    if args.list:
        print("Available event types:")
        for et in payloads:
            print(f"  {et}")
        return

    if not args.tenant and not args.list:
        print("Error: --tenant <oa_token> is required")
        print("Get your OA token from: POST /api/line-oa/list")
        sys.exit(1)

    if args.all:
        print(f"Firing all {len(payloads)} event types to OA token {args.tenant[:16]}… at {args.url}")
        for payload in payloads.values():
            send_event(payload, args.url, args.tenant)
        print("\nDone.")
        return

    if args.event:
        if args.event not in payloads:
            print(f"Unknown event type: {args.event!r}")
            print(f"Run with --list to see available types.")
            sys.exit(1)
        send_event(payloads[args.event], args.url, args.tenant)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
