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
from app.repositories.recipient_repository import opt_out

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
            # Provider role: this service notifies/tracks, it does not converse with
            # customers. Inbound free-text gets a passive acknowledgement.
            set_user_state(company_id, user_id, {"status": "idle"})
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
