import traceback
import json
import redis
import requests as http_requests
from app.auth import verify_required
from app.config import CENTER_ACCESS_KEY, CENTER_URL, SERVICE_BASE_URL, REDIS_URL
from app.database import init_db
from app.extensions import init_center_service
from app.repositories.token_repository import (
    get_company_by_token,
    register_company_token,
    update_company_token,
    rotate_token,
    revoke_token,
    get_tokens_by_company
)
from app.services import customer_service, order_service
from flask import Flask, request, jsonify, g
from flask_cors import CORS

# --- LINE imports ---
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, FollowEvent, PostbackEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

from app.uitl import split_into_two

app = Flask(__name__)
CORS(app)

init_center_service(CENTER_ACCESS_KEY, CENTER_URL)
init_db()

# ─── Redis Setup ──────────────────────────────────────────────────────
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# ─── In-memory User State ─────────────────────────────────────────────
_user_states: dict = {}

def get_user_state(company_id: str, user_id: str) -> dict:
    return _user_states.get(f"{company_id}:{user_id}", {'status': 'idle'})

def set_user_state(company_id: str, user_id: str, state_dict: dict):
    _user_states[f"{company_id}:{user_id}"] = state_dict

# ─── Redis Token Cache Helpers ────────────────────────────────────────
def get_cached_token_data(token: str) -> dict:
    data = redis_client.get(f"token:{token}")
    if data:
        return json.loads(data)
    return None

def set_cached_token_data(token: str, data: dict):
    redis_client.set(f"token:{token}", json.dumps(data))

def delete_cached_token(token: str):
    redis_client.delete(f"token:{token}")

# ─── LINE Helpers ─────────────────────────────────────────────────────
def get_line_bot_info(channel_access_token: str) -> dict:
    """Call LINE API to get bot info. Returns dict or None on failure."""
    try:
        res = http_requests.get(
            "https://api.line.me/v2/bot/info",
            headers={"Authorization": f"Bearer {channel_access_token}"},
            timeout=10
        )
        if res.status_code == 200:
            return res.json()
        return None
    except Exception:
        return None

def reply(reply_token: str, message: str, channel_access_token: str):
    """Reply to a LINE message using the company's own access token."""
    configuration = Configuration(access_token=channel_access_token)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=message)]
        ))

def _reply(reply_token: str, message: str):
    """Internal helper — uses the company's access token from request context."""
    reply(reply_token, message, g.channel_access_token)


# ─── LINE OA Sync endpoint ────────────────────────────────────────────
@app.route("/api/line-oa/sync", methods=["POST"])
@verify_required
def sync_line_oa():
    """
    Register a new LINE OA for a company.
    Always creates a new token — same company can have multiple OAs.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body is required", "success": False}), 400

        company_id           = data.get("company_id")
        channel_secret       = data.get("channel_secret")
        channel_access_token = data.get("channel_access_token")

        if not company_id:
            return jsonify({"error": "company_id is required", "success": False}), 400
        if not channel_secret:
            return jsonify({"error": "channel_secret is required", "success": False}), 400
        if not channel_access_token:
            return jsonify({"error": "channel_access_token is required", "success": False}), 400

        # Validate credentials against LINE API
        bot_info = get_line_bot_info(channel_access_token)
        if not bot_info:
            return jsonify({
                "error": "Invalid LINE credentials. Please check your channel_access_token.",
                "success": False
            }), 400

        row, created = register_company_token(
            company_id=str(company_id),
            channel_secret=channel_secret,
            channel_access_token=channel_access_token
        )

        set_cached_token_data(row.token, {
            "company_id": row.company_id,
            "channel_secret": channel_secret,
            "channel_access_token": channel_access_token
        })

        webhook_url = f"{SERVICE_BASE_URL}/webhook/{row.token}"

        return jsonify({
            "success": True,
            "company_id": company_id,
            "oa_name": bot_info.get("displayName"),
            "oa_basic_id": bot_info.get("basicId"),
            "token": row.token,
            "webhook_url": webhook_url,
            "message": "Token generated. Paste the webhook_url into your LINE OA Developer Console."
        }), 201

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "success": False}), 500


# ─── Update credentials endpoint ─────────────────────────────────────
@app.route("/api/line-oa/update", methods=["POST"])
@verify_required
def update_line_oa():
    """
    Update credentials for an existing OA token.
    Webhook URL stays the same.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body is required", "success": False}), 400

        token                = data.get("token")
        channel_secret       = data.get("channel_secret")
        channel_access_token = data.get("channel_access_token")

        if not token:
            return jsonify({"error": "token is required", "success": False}), 400
        if not channel_secret:
            return jsonify({"error": "channel_secret is required", "success": False}), 400
        if not channel_access_token:
            return jsonify({"error": "channel_access_token is required", "success": False}), 400

        bot_info = get_line_bot_info(channel_access_token)
        if not bot_info:
            return jsonify({
                "error": "Invalid LINE credentials. Please check your channel_access_token.",
                "success": False
            }), 400

        row = update_company_token(token, channel_secret, channel_access_token)
        if not row:
            return jsonify({"error": "Token not found.", "success": False}), 404

        # Update cache
        set_cached_token_data(token, {
            "company_id": row.company_id,
            "channel_secret": channel_secret,
            "channel_access_token": channel_access_token
        })

        webhook_url = f"{SERVICE_BASE_URL}/webhook/{token}"
        return jsonify({
            "success": True,
            "company_id": row.company_id,
            "token": token,
            "webhook_url": webhook_url,
            "message": "Credentials updated. Your webhook_url remains the same."
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "success": False}), 500


# ─── Rotate token endpoint ────────────────────────────────────────────
@app.route("/api/line-oa/rotate", methods=["POST"])
@verify_required
def rotate_line_oa_token():
    """Generate a new webhook token, invalidating the old webhook URL."""
    try:
        data = request.get_json()
        token = data.get("token") if data else None

        if not token:
            return jsonify({"error": "token is required", "success": False}), 400

        delete_cached_token(token)

        new_token = rotate_token(token)
        if new_token is None:
            return jsonify({
                "error": "Token not found. Call /api/line-oa/sync first.",
                "success": False
            }), 404

        webhook_url = f"{SERVICE_BASE_URL}/webhook/{new_token}"
        return jsonify({
            "success": True,
            "token": new_token,
            "webhook_url": webhook_url,
            "message": "Token rotated. Update the webhook_url in your LINE OA Developer Console."
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "success": False}), 500


# ─── Revoke endpoint ──────────────────────────────────────────────────
@app.route("/api/line-oa/revoke", methods=["POST"])
@verify_required
def revoke_line_oa():
    """Remove an OA registration entirely."""
    try:
        data = request.get_json()
        token = data.get("token") if data else None

        if not token:
            return jsonify({"error": "token is required", "success": False}), 400

        delete_cached_token(token)
        success = revoke_token(token)

        if not success:
            return jsonify({"error": "Token not found.", "success": False}), 404

        return jsonify({
            "success": True,
            "message": "OA registration removed."
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "success": False}), 500


# ─── List OAs for a company ───────────────────────────────────────────
@app.route("/api/line-oa/list", methods=["POST"])
@verify_required
def list_line_oas():
    """List all OA registrations for a company."""
    try:
        data = request.get_json()
        company_id = data.get("company_id") if data else None

        if not company_id:
            return jsonify({"error": "company_id is required", "success": False}), 400

        rows = get_tokens_by_company(str(company_id))
        return jsonify({
            "success": True,
            "company_id": company_id,
            "oas": [
                {
                    "token": row.token,
                    "webhook_url": f"{SERVICE_BASE_URL}/webhook/{row.token}",
                    "created_at": row.created_at.isoformat() if row.created_at else None
                }
                for row in rows
            ],
            "count": len(rows)
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "success": False}), 500


# ─── LINE Webhook route ───────────────────────────────────────────────
@app.route("/webhook/<token>", methods=["POST"])
def webhook(token):
    token_data = get_cached_token_data(token)

    if not token_data:
        token_row = get_company_by_token(token)
        if not token_row:
            return jsonify({"error": "Unknown token"}), 404

        token_data = {
            "company_id": token_row.company_id,
            "channel_secret": token_row.channel_secret,
            "channel_access_token": token_row.channel_access_token
        }
        set_cached_token_data(token, token_data)

    g.company_id           = token_data["company_id"]
    g.channel_access_token = token_data["channel_access_token"]

    handler = WebhookHandler(token_data["channel_secret"])

    @handler.add(FollowEvent)
    def handle_follow(event):
        user_id = event.source.user_id
        set_user_state(g.company_id, user_id, {'status': 'idle'})
        _reply(event.reply_token, 'Welcome! 👋 กรุณาเลือกรายการที่ต้องการจากเมนูได้เลยครับ')

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message(event):
        user_id = event.source.user_id
        try:
            text = event.message.text.strip()
            user = get_user_state(g.company_id, user_id)

            if text == 'ลงชื่อใช้งาน':
                user['status'] = "wait_register"
                set_user_state(g.company_id, user_id, user)
                _reply(event.reply_token,
                    'กรุณาส่งรหัสลูกค้า และเลขประจำตัวผู้เสียภาษีมาในระบบเพื่อยืนยันตัวตน \n'
                    'รูปแบบการส่งคือ CODE,0000000000000'
                )

            elif text == "จ้างงาน":
                user['status'] = "wait_order"
                set_user_state(g.company_id, user_id, user)
                _reply(event.reply_token, (
                    "📋 กรุณาระบุรายละเอียดงานได้เลยครับ\n"
                    "หากเป็นไปได้ แนะนำให้ส่งในรูปแบบด้านล่าง หรือใกล้เคียง\n"
                    "เพื่อให้เจ้าหน้าที่ดำเนินการได้รวดเร็วมากขึ้น 🚚\n\n"
                    "ตัวอย่าง:\n"
                    "ประเภทรถ: 6 ล้อ\n"
                    "วันที่ขึ้นสินค้า: วันนี้\n"
                    "ขึ้น: สวนผึ้ง ราชบุรี\n"
                    "ลง: วังน้ำเขียว โคราช\n"
                    "ราคา: 5,500 บาท\n"
                    "เบอร์โทร: 086xxxxxxx\n\n"
                    "ขอบคุณครับ 🙏"
                ))

            elif text == "วางออเดอร์":
                user['status'] = "placing_order"
                set_user_state(g.company_id, user_id, user)
                _reply(event.reply_token, (
                    "คุณกำลังวางออเดอร์เอง โปรดระบุรหัสลูกค้าที่ต้องการจะวางออเดอร์มาในข้อความถัดไป"
                    "โดยไม่ต้องพิมพ์อะไรเพิ่มเติม เช่น หากรหัสลูกค้า คือ W001 ให้ส่งข้อความมาว่า W001"
                ))

            elif text == "ดูเส้นทางของฉัน":
                data, status_code = customer_service.get_customer_route(user_id)
                t = data['token']
                expires_at = data['expires_at']
                formatted_expiry = expires_at.strftime("%d %B %Y, %H:%M น.") if hasattr(expires_at, 'strftime') else str(expires_at)
                _reply(event.reply_token, (
                    f"คุณสามารถดูข้อมูลการจัดส่งและข้อมูลรถได้ที่นี่ : http://localhost:5173/customer_checks?token={t}\n"
                    f"ลิงก์จะสามารถใช้ได้ถึง : {formatted_expiry}"
                ))

            elif user['status'] == "placing_order":
                data, status_code = customer_service.find_user(text)
                if status_code == 200:
                    user['status'] = "creating_order_customer"
                    user['placing_order_customer'] = data.get("customer_code")
                    set_user_state(g.company_id, user_id, user)
                    company_name = data.get("data", {}).get('company_name')
                    _reply(event.reply_token, (
                        f"กำลังเปิดออเดอร์ให้ {company_name}\n"
                        "📋 กรุณาระบุรายละเอียดงานได้เลยครับ\n"
                        "หากเป็นไปได้ แนะนำให้ส่งในรูปแบบด้านล่าง หรือใกล้เคียง\n"
                        "เพื่อให้เจ้าหน้าที่ดำเนินการได้รวดเร็วมากขึ้น 🚚\n\n"
                        "ตัวอย่าง:\n"
                        "ประเภทรถ: 6 ล้อ\n"
                        "วันที่ขึ้นสินค้า: วันนี้\n"
                        "ขึ้น: สวนผึ้ง ราชบุรี\n"
                        "ลง: วังน้ำเขียว โคราช\n"
                        "ราคา: 5,500 บาท\n"
                        "เบอร์โทร: 086xxxxxxx\n\n"
                        "ขอบคุณครับ 🙏"
                    ))

            elif user['status'] == "creating_order_customer":
                res, status = order_service.make_order(text, user_id, user.get('placing_order_customer'))
                if res.get('success') != True:
                    raise ValueError(res.get('error')) if status == 400 else Exception(res.get('error'))

                user['status'] = 'idle'
                user.pop('placing_order_customer', None)
                set_user_state(g.company_id, user_id, user)
                _reply(event.reply_token, 'ระบบทำการวางออเดอร์ให้ท่านเรียบร้อยแล้ว ขณะนี้กำลังรอเจ้าหน้าที่อนุมัติ')

            elif user['status'] == "wait_register":
                customer_code, tax_number = split_into_two(text)
                res, status = customer_service.register_user(customer_code, tax_number, user_id)
                if res.get('success') != True:
                    raise ValueError(res.get('error')) if status == 400 else Exception(res.get('error'))

                user['status'] = 'idle'
                set_user_state(g.company_id, user_id, user)
                _reply(event.reply_token, f'เชื่อมต่อกับข้อมูลของ {res.get("data")} สำเร็จ!')

            elif user['status'] == "wait_order":
                res, status = order_service.make_order(text, user_id)
                if res.get('success') != True:
                    raise ValueError(res.get('error')) if status == 400 else Exception(res.get('error'))

                user['status'] = 'idle'
                set_user_state(g.company_id, user_id, user)
                _reply(event.reply_token, 'ระบบทำการวางออเดอร์ให้ท่านเรียบร้อยแล้ว ขณะนี้กำลังรอเจ้าหน้าที่อนุมัติ')

            else:
                user['status'] = 'idle'
                set_user_state(g.company_id, user_id, user)
                _reply(event.reply_token, 'ระบบไม่เข้าใจคำสั่ง กรุณาเลือกรายการที่จะทำหรือสอบถามทิ้งไว้ได้เลยครับ 🙏🏻')

        except ValueError as e:
            set_user_state(g.company_id, user_id, {'status': 'idle'})
            _reply(event.reply_token, str(e))
        except Exception as e:
            set_user_state(g.company_id, user_id, {'status': 'idle'})
            traceback.print_exc()
            _reply(event.reply_token, 'เกิดข้อผิดพลาด กรุณาตรวจสอบข้อความอีกครั้งหรือลองใหม่ในภายหลัง')

    @handler.add(PostbackEvent)
    def handle_postback(event):
        user_id = event.source.user_id
        data    = event.postback.data
        user    = get_user_state(g.company_id, user_id)

        if data == 'action=enable_x':
            user['x_enabled'] = True
            set_user_state(g.company_id, user_id, user)
            _reply(event.reply_token, '⚡ Function X enabled!')
        elif data == 'action=something_else':
            _reply(event.reply_token, 'You clicked something else!')

    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return jsonify({"error": "Invalid signature"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    return 'OK', 200
