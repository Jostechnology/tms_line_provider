import traceback
from fastapi import APIRouter, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage,
)
from linebot.v3.webhooks import MessageEvent, FollowEvent, UnfollowEvent, PostbackEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

from app.extensions import get_cached_token_data, set_cached_token_data
from app.repositories.token_repository import get_company_by_token
from app.repositories.recipient_repository import upsert_recipient, opt_out
from app.services import customer_service, order_service
from app.config import SERVICE_BASE_URL
from app.uitl import split_into_two

router = APIRouter(tags=["LINE Webhook"])

# ─── In-memory user state ─────────────────────────────────────────────────────

_user_states: dict = {}

def get_user_state(company_id: str, user_id: str) -> dict:
    return _user_states.get(f"{company_id}:{user_id}", {"status": "idle"})

def set_user_state(company_id: str, user_id: str, state_dict: dict):
    _user_states[f"{company_id}:{user_id}"] = state_dict


# ─── Reply helper ─────────────────────────────────────────────────────────────

def reply(reply_token: str, message: str, channel_access_token: str):
    configuration = Configuration(access_token=channel_access_token)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=message)],
        ))


# ─── Webhook route ────────────────────────────────────────────────────────────

@router.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    token_data = get_cached_token_data(token)

    if not token_data:
        token_row = get_company_by_token(token)
        if not token_row:
            raise HTTPException(status_code=404, detail="Unknown token")
        token_data = {
            "company_id":           token_row.company_id,
            "channel_secret":       token_row.channel_secret,
            "channel_access_token": token_row.channel_access_token,
        }
        set_cached_token_data(token, token_data)

    company_id           = token_data["company_id"]
    channel_access_token = token_data["channel_access_token"]

    def _reply(reply_token: str, message: str):
        reply(reply_token, message, channel_access_token)

    handler = WebhookHandler(token_data["channel_secret"])

    @handler.add(FollowEvent)
    def handle_follow(event):
        user_id = event.source.user_id
        set_user_state(company_id, user_id, {"status": "idle"})
        _reply(event.reply_token, "Welcome! 👋 กรุณาเลือกรายการที่ต้องการจากเมนูได้เลยครับ")

    @handler.add(UnfollowEvent)
    def handle_unfollow(event):
        """User blocked or unfollowed — opt them out so we stop pushing."""
        user_id = event.source.user_id
        opt_out(company_id, user_id)
        set_user_state(company_id, user_id, {"status": "idle"})
        print(f"[webhook] unfollow/block company={company_id} user={user_id} — opted out")

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message(event):
        user_id = event.source.user_id
        try:
            text = event.message.text.strip()
            user = get_user_state(company_id, user_id)

            if text == "ลงชื่อใช้งาน":
                user["status"] = "wait_register"
                set_user_state(company_id, user_id, user)
                _reply(event.reply_token,
                    "กรุณาส่งรหัสลูกค้า และเลขประจำตัวผู้เสียภาษีมาในระบบเพื่อยืนยันตัวตน \n"
                    "รูปแบบการส่งคือ CODE,0000000000000"
                )

            elif text == "จ้างงาน":
                user["status"] = "wait_order"
                set_user_state(company_id, user_id, user)
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
                user["status"] = "placing_order"
                set_user_state(company_id, user_id, user)
                _reply(event.reply_token, (
                    "คุณกำลังวางออเดอร์เอง โปรดระบุรหัสลูกค้าที่ต้องการจะวางออเดอร์มาในข้อความถัดไป"
                    "โดยไม่ต้องพิมพ์อะไรเพิ่มเติม เช่น หากรหัสลูกค้า คือ W001 ให้ส่งข้อความมาว่า W001"
                ))

            elif text == "ดูเส้นทางของฉัน":
                data, status_code = customer_service.get_customer_route(user_id)
                t = data["token"]
                expires_at = data["expires_at"]
                formatted_expiry = (
                    expires_at.strftime("%d %B %Y, %H:%M น.")
                    if hasattr(expires_at, "strftime") else str(expires_at)
                )
                _reply(event.reply_token, (
                    f"คุณสามารถดูข้อมูลการจัดส่งและข้อมูลรถได้ที่นี่ : {SERVICE_BASE_URL}/tracking?token={t}\n"
                    f"ลิงก์จะสามารถใช้ได้ถึง : {formatted_expiry}"
                ))

            elif user["status"] == "placing_order":
                data, status_code = customer_service.find_user(text)
                if status_code == 200:
                    user["status"] = "creating_order_customer"
                    user["placing_order_customer"] = data.get("customer_code")
                    set_user_state(company_id, user_id, user)
                    company_name = data.get("data", {}).get("company_name")
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

            elif user["status"] == "creating_order_customer":
                res, status = order_service.make_order(text, user_id, user.get("placing_order_customer"))
                if res.get("success") != True:
                    raise ValueError(res.get("error")) if status == 400 else Exception(res.get("error"))
                user["status"] = "idle"
                user.pop("placing_order_customer", None)
                set_user_state(company_id, user_id, user)
                _reply(event.reply_token, "ระบบทำการวางออเดอร์ให้ท่านเรียบร้อยแล้ว ขณะนี้กำลังรอเจ้าหน้าที่อนุมัติ")

            elif user["status"] == "wait_register":
                customer_code, tax_number = split_into_two(text)
                res, status = customer_service.register_user(customer_code, tax_number, user_id)
                if res.get("success") != True:
                    raise ValueError(res.get("error")) if status == 400 else Exception(res.get("error"))

                # Store oa_token so notifications go back via the correct OA
                upsert_recipient(
                    company_id=company_id,
                    customer_code=customer_code,
                    line_user_id=user_id,
                    oa_token=token,
                )

                user["status"] = "idle"
                set_user_state(company_id, user_id, user)
                _reply(event.reply_token, f'เชื่อมต่อกับข้อมูลของ {res.get("data")} สำเร็จ!')

            elif user["status"] == "wait_order":
                res, status = order_service.make_order(text, user_id)
                if res.get("success") != True:
                    raise ValueError(res.get("error")) if status == 400 else Exception(res.get("error"))
                user["status"] = "idle"
                set_user_state(company_id, user_id, user)
                _reply(event.reply_token, "ระบบทำการวางออเดอร์ให้ท่านเรียบร้อยแล้ว ขณะนี้กำลังรอเจ้าหน้าที่อนุมัติ")

            else:
                user["status"] = "idle"
                set_user_state(company_id, user_id, user)
                _reply(event.reply_token, "ระบบไม่เข้าใจคำสั่ง กรุณาเลือกรายการที่จะทำหรือสอบถามทิ้งไว้ได้เลยครับ 🙏🏻")

        except ValueError as e:
            set_user_state(company_id, user_id, {"status": "idle"})
            _reply(event.reply_token, str(e))
        except Exception as e:
            set_user_state(company_id, user_id, {"status": "idle"})
            traceback.print_exc()
            _reply(event.reply_token, "เกิดข้อผิดพลาด กรุณาตรวจสอบข้อความอีกครั้งหรือลองใหม่ในภายหลัง")

    @handler.add(PostbackEvent)
    def handle_postback(event):
        user_id = event.source.user_id
        data    = event.postback.data
        user    = get_user_state(company_id, user_id)

        if data == "action=enable_x":
            user["x_enabled"] = True
            set_user_state(company_id, user_id, user)
            _reply(event.reply_token, "⚡ Function X enabled!")
        elif data == "action=something_else":
            _reply(event.reply_token, "You clicked something else!")

    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    return "OK"
