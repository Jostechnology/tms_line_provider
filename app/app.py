import traceback
from app.auth import verify_required
from app.config import CENTER_ACCESS_KEY, CENTER_URL, LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from app.extensions import init_center_service
from app.services import customer_service, order_service
from flask import Flask, request, jsonify, g, send_from_directory
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

# --- LINE config ---
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# In-memory store — swap with your DB later
user_store = {}  # { line_user_id: { name, phone, state, x_enabled } }

# ─── Your existing routes ────────────────────────────────────────────

# @app.route("/api/register_customer", methods=["POST"])
# @verify_required
# def extract_word():
#     try:
#         data = request.get_json()
#         text = data.get("text")
#         return jsonify({"data": "", "success": True}), 200
#     except Exception as e:
#         traceback.print_exc()
#         return jsonify({"error": str(e), "success": False}), 500

# @app.route("/api/search_customer", methods=["POST"])  # fixed typo: mothods → methods
# @verify_required
# def search_customer_api():
#     try:
#         data = request.get_json()
#         customer_code = data.get("customer_code")
#         res = customer_service.find_customer_by_customer_code(customer_code)
#         return jsonify({"data": res, "success": True}), 200
#     except Exception as e:
#         traceback.print_exc()
#         return jsonify({"error": str(e), "success": False}), 500


# ─── LINE Webhook route ───────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
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


# ─── LINE Event Handlers ──────────────────────────────────────────────

@handler.add(FollowEvent)
def handle_follow(event):
    """Triggered when user adds your bot"""
    user_id = event.source.user_id
    user_store[user_id] = {'state': 'awaiting_name'}
    reply(event.reply_token, 'Welcome! 👋 Please tell me your name.')

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    try:
        user_id = event.source.user_id
        text = event.message.text.strip()
        user = user_store.get(user_id)
        if not user:
            user_store[user_id] = {'status' : 'idle'}
            user = user_store.get(user_id)

        if text == 'ลงชื่อใช้งาน':
            user['status'] = "wait_register"
            reply(event.reply_token, 'กรุณาส่งรหัสลูกค้า และเลขประจำตัวผู้เสียภาษีมาในระบบเพื่อยืนยันตัวตน \n รูปแบบการส่งคือ CODE,0000000000000')

        elif text == "จ้างงาน":
            user['status'] = "wait_order"
            reply(event.reply_token,(
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
                )
            )
        
        elif text == "วางออเดอร์":
            user['status'] = "placing_order"
            reply(event.reply_token,(
                    "คุณกำลังวางออเดอร์เอง โปรดระบุรหัสลูกค้าที่ต้องการจะวางออเดอร์มาในข้อความถัดไป"
                    "โดยไม่ต้องพิมพ์อะไรเพิ่มเติม เช่น หากรหัสลูกค้า คือ W001 ให้ส่งข้อความมาว่า W001"
                )
            )
        
        elif text == "ดูเส้นทางของฉัน":
            data, status_code = customer_service.get_customer_route(user_id)
            token = data['token']
            expires_at = data['expires_at']
            
            formatted_expiry = expires_at.strftime("%d %B %Y, %H:%M น.")

            reply(event.reply_token, (
                f"คุณสามารถดูข้อมูลการจัดส่งและข้อมูลรถได้ที่นี่ : http://localhost:5173/customer_checks?token={token}\n"
                f"ลิงก์จะสามารถใช้ได้ถึง : {formatted_expiry}"
            ))
        
        elif user and user['status'] == "placing_order":
            data, status_code = customer_service.find_user(text)
            if status_code == 200:
                user['status'] = "creating_order_customer"
                user['placing_order_customer'] = data.get("customer_code")
                data = data.get("data")
                reply(event.reply_token, (
                    f"กำลังเปิดออเดอร์ให้ {data.get('company_name')}\n"
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
            
        
        elif user and user['status'] == "creating_order_customer":
            res, status = order_service.make_order(text, user_id, user['placing_order_customer'])
            if res['success'] != True:
                if status == 400:
                    raise ValueError(res['error'])
                raise Exception(res['error'])
            reply(event.reply_token, f'ระบบทำการวางออเดอร์ให้ท่านเรียบร้อยแล้ว ขณะนี้กำลังรอเจ้าหน้าที่อนุมัติ')
        
        elif user and user['status'] == "wait_register":
            customer_code, tax_number = split_into_two(text)
            res, status = customer_service.register_user(customer_code, tax_number, user_id)
            if res['success'] != True:
                if status == 400:
                    raise ValueError(res['error'])
                raise Exception(res['error'])
            
            reply(event.reply_token, f'เชื่อมต่อกับข้อมูลของ {res["data"]} สำเร็จ!')
        
        elif user and user['status'] == "wait_order":
            res, status = order_service.make_order(text, user_id)
            if res['success'] != True:
                if status == 400:
                    raise ValueError(res['error'])
                raise Exception(res['error'])
            reply(event.reply_token, f'ระบบทำการวางออเดอร์ให้ท่านเรียบร้อยแล้ว ขณะนี้กำลังรอเจ้าหน้าที่อนุมัติ')
            
        else:
            user['status'] = 'idle'
            reply(event.reply_token, f'ระบบไม่เข้าใจคำสั่ง กรุณาเลือกรายการที่จะทำหรือสอบถามทิ้งไว้ได้เลยครับ 🙏🏻')
    except ValueError as e:
        user['status'] = 'idle'
        reply(event.reply_token, str(e))
    except Exception as e:
        user['status'] = 'idle'
        traceback.print_exc()
        print(f"Failure : Text [{text}] User [{user_id}] Error {str(e)}")
        reply(event.reply_token, f'เกิดข้อผิดพลาด กรุณาตรวจสอบข้อความอีกครั้งหรือลองใหม่ในภายหลัง')

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data  # this is "action=enable_x"
    user = user_store.get(user_id, {'state': 'idle'})

    if data == 'action=enable_x':
        user['x_enabled'] = True
        user_store[user_id] = user
        reply(event.reply_token, '⚡ Function X enabled! Send your next message.')

    elif data == 'action=something_else':
        reply(event.reply_token, 'You clicked something else!')


# ─── Helpers ──────────────────────────────────────────────────────────

def reply(reply_token, message):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=message)]
        ))

def your_custom_service(message, user_id):
    # Call your own logic, external API, etc.
    return f'Processed "{message}" for user {user_id}'