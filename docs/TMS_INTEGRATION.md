# TMS ↔ LINE Provider — Integration Guide

How TMS talks to the **LINE Provider** service: register a tenant's LINE OA, link
TMS users to their LINE accounts, and push notifications.

- **Base URL (prod):** `https://tms-line-provider.jostechnology.co.th`
- **Auth:** every endpoint below requires `Authorization: Bearer <ADMIN_TOKEN>`
  (a single shared secret; ask ops for the value). One exception is noted.
- **Content type:** `application/json`.

---

## 1. Mental model (read this first)

This service is a **notification provider**. It does **not** talk to customers
conversationally. It does two things:

1. **Push event cards to customers** of a tenant — driven by trip events you send.
2. **Push internal messages to TMS users** (drivers/staff) — driven by an explicit
   notify call from you.

Two things make LINE non-obvious; the whole design follows from them:

- **A LINE `userId` is unique per *provider*.** The id you'd get from any other
  LINE channel is meaningless to a tenant's OA. The only usable id is the one a
  tenant's **own OA webhook** reports. That's why linking (§3) runs through the OA.
- **You can only push to a user who has added that OA as a friend.** The linking
  flow naturally makes the user a friend, so this takes care of itself.

There are therefore **two delivery paths with two different recipient models**:

| Path | Endpoint | Recipient resolved by | Who registers the recipient |
|------|----------|------------------------|------------------------------|
| Customer event cards | `POST /api/events/{company_id}` | `customer_code` → `recipient_links` | `POST /api/recipients/register` |
| TMS-user push        | `POST /api/line-oa/notify`      | `tms_username` → `line_tms_links`  | Account-linking flow (§3) |

`company_id` is the tenant identifier throughout (TMS group_id). **One OA per
company** is enforced.

---

## 2. One-time setup per tenant — register the OA

Before anything else, a tenant's **Messaging API** OA must be registered so the
service can receive its webhooks and push through it.

`POST /api/line-oa/sync`

```json
{
  "company_id": "128",
  "channel_secret": "<OA Messaging API channel secret>",
  "channel_access_token": "<OA Messaging API long-lived access token>"
}
```

Response includes a `webhook_url`:

```json
{
  "success": true,
  "company_id": "128",
  "oa_name": "Acme Logistics",
  "token": "9sB1Xc9n0Ee...",
  "webhook_url": "https://tms-line-provider.jostechnology.co.th/webhook/9sB1Xc9n0Ee...",
  "message": "Token generated. Paste the webhook_url into your LINE OA Developer Console."
}
```

**Action:** paste `webhook_url` into the OA's **Messaging API → Webhook URL** and
enable "Use webhook". Verify should pass.

Notes:
- `channel_secret` = Messaging API channel **Basic settings → Channel secret**.
- `channel_access_token` = Messaging API channel **Messaging API → Channel access token**.
  These are *different values from different tabs* — do not swap them.
- Re-calling `/sync` with the same credentials is idempotent.
- A **second, different** OA for the same `company_id` is rejected with **409**
  (one OA per company by policy).
- Related ops endpoints: `POST /api/line-oa/list`, `/update`, `/rotate`, `/revoke`.

---

## 3. Link a TMS user to their LINE account

Needed before you can push to a TMS user by username. Linking runs **through the
tenant's OA** so the stored `userId` is scoped correctly.

### Step 1 — TMS asks the provider to start linking

`POST /api/line-oa/link/start`

```json
{ "company_id": "128", "tms_username": "jaoaurai" }
```

Response:

```json
{
  "success": true,
  "company_id": "128",
  "tms_username": "jaoaurai",
  "code": "LINK-9F3A2B",
  "deep_link": "https://line.me/R/oaMessage/@acme/?LINK-9F3A2B",
  "qr_code_base64": "<PNG bytes, base64>",
  "oa_basic_id": "@acme",
  "expires_in": "15 minutes"
}
```

### Step 2 — show it to the user

Render the QR (`<img src="data:image/png;base64,{qr_code_base64}">`) or hand them
the `deep_link`. Tapping it opens the tenant's OA chat with the code pre-filled.

### Step 3 — user taps send

The OA webhook receives the code + the user's OA-scoped `userId`, binds
`tms_username ↔ userId`, and replies in chat:
`เชื่อมต่อบัญชี jaoaurai เรียบร้อยแล้ว ✅`. Linking is now complete.

- Codes are single-use and expire in 15 minutes; mint a fresh one if expired.
- Sending the code also friends the OA (required for push) — no extra step.
- To check a link: `GET /api/line-tms/link?company_id=128&tms_id=jaoaurai`.
- To set a mapping manually (e.g. backfill): `POST /api/line-tms/link`
  `{ "company_id": "128", "tms_id": "...", "line_id": "U...", "oa_token": "..." }`.
  `company_id` is required — a LINE userId is per-channel, so a link is scoped to
  the company's OA. `oa_token` (the channel the id came from) is optional.

---

## 4. Push to TMS users — `POST /api/line-oa/notify`

Send a ready-made LINE message to one or more **linked** TMS users of a tenant.

```json
{
  "company_id": "128",
  "tms_usernames": ["jaoaurai", "somchai"],
  "payload": { "type": "text", "text": "งานใหม่ถูกมอบหมายให้คุณแล้ว" }
}
```

`payload` is a raw [LINE message object](https://developers.line.biz/en/reference/messaging-api/#message-objects)
(text, Flex, etc.), pushed as-is via multicast.

Response:

```json
{ "success": true, "recipients": 2, "unlinked": [] }
```

- `recipients` = number of LINE users actually sent to.
- `unlinked` = usernames with no LINE link yet (they completed no linking flow).
  **These are skipped, not an error** — send them through §3 first.
- `recipients: 0` with a `200` means nobody was linked. That is the #1 "it
  returned OK but nothing arrived" cause — check `unlinked`.
- Each delivered recipient is recorded in `delivery_logs` (`event_type =
  line-oa.notify`); see §6.

---

## 5. Push customer event cards — `POST /api/events/{company_id}`

Send a trip event; the provider renders a card and pushes it to the customer tied
to `customer_code`.

`POST /api/events/128` — header `Authorization: Bearer <ADMIN_TOKEN>`.

```json
{
  "event_type": "stop.delivered",
  "trip_id": "WO-2026-0001",
  "occurred_at": "2026-06-12T08:30:00Z",
  "stop_id": "STOP-002",
  "customer_code": "W001",
  "stop_address": "456 ถนนพระราม 4 กรุงเทพฯ"
}
```

- `tenant_id` is derived from the `{company_id}` in the URL — you don't need to
  send it (any value in the body is ignored).
- Unknown `company_id` (no registered OA) → **404**.
- The customer must already be a **recipient** for that `customer_code` (see §5.1),
  else the event is logged as `no_recipient` and nothing is sent.

### Event types & required fields

All events share: `event_type`, `trip_id`, `occurred_at` (UTC ISO-8601),
`customer_code`.

| `event_type` | Extra required fields |
|--------------|------------------------|
| `wo.started` | `driver_name`, `vehicle_plate` |
| `stop.arrived` | `stop_id`, `stop_address`, `eta_minutes?` |
| `stop.delivered` | `stop_id`, `stop_address`, `epod_image_url?` |
| `stop.failed` | `stop_id`, `stop_address`, `failure_reason` |
| `stop.departed` | `stop_id` |
| `stop.load_start` | `stop_id`, `stop_address` |
| `stop.load_end` | `stop_id`, `stop_address` |
| `eta.slipped` | `stop_id`, `original_eta`, `revised_eta`, `slip_minutes` |
| `stop.projected_miss` | `stop_id`, … |
| `stop.stalled` | `stop_id`, … |

(`?` = optional. `stop.departed`, `stop.load_start`, `stop.load_end` are accepted
but currently informational — no customer push.)

### 5.1 Register a customer recipient

`POST /api/recipients/register`

```json
{ "company_id": "128", "customer_code": "W001", "line_user_id": "U...", "tms_username": "..." }
```

The `line_user_id` must be that customer's **OA-scoped** userId (same rule as §1).

---

## 6. Delivery logs (observability)

- `GET /api/logs/tenant?company_id=128&limit=100` — recent push attempts for a tenant.
- `GET /api/logs/trip?trip_id=WO-2026-0001&company_id=128` — attempts for one trip.

Each row has `status` (`sent` | `failed` | `no_recipient`), `event_type`,
`customer_code`, `line_user_id`, `error_detail`, timestamps. TMS-user pushes from
§4 appear with `event_type = line-oa.notify` and `customer_code = <tms_username>`.

---

## 7. Auth & error reference

- **Auth header:** `Authorization: Bearer <ADMIN_TOKEN>` on every endpoint here.
- `401` — missing/invalid token.
- `404` — unknown `company_id` (no OA registered) or no mapping found.
- `409` — second OA for a company (one-OA-per-company policy).
- `502` — upstream LINE call failed (multicast / token check); body has detail.
- `400` — malformed event payload (missing required field, bad enum).

---

## 8. Gotchas (the ones that cost us days)

1. **`userId` is per-provider.** Never reuse a userId obtained anywhere except the
   tenant's own OA. This is why §3 links through the OA and there is no central
   LINE-Login OAuth.
2. **Multicast returns `200` even when it reaches nobody.** A `200` from `/notify`
   is *not* proof of delivery — check `recipients`/`unlinked`, and confirm the user
   friended the OA.
3. **`/notify` with `recipients: 0`** → those usernames aren't linked. Run §3.
4. **One OA per company.** Registering a different OA under an existing
   `company_id` is a `409`.
5. **Event with no recipient** → logged `no_recipient`, no push. Register the
   customer (§5.1) first.
