import uuid
import os
import io
import base64
import httpx
import qrcode
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter()

_pending_links: dict = {}
_oauth_states: dict = {}

TOKEN_TTL_MINUTES  = 10
LINE_CLIENT_ID     = os.getenv("LINE_CLIENT_ID", "2010354335")
LINE_CLIENT_SECRET = os.getenv("LINE_CLIENT_SECRET", "272a16070d62aa5b11529b75486cf94c")
AUTH_SERVER_URL    = os.getenv("AUTH_SERVER_URL", "http://localhost:5003")


def _make_qr_base64(url: str) -> str:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#06C755", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ─── Step 0: TMS generates a one-time login link ─────────────────────────────

class GenerateLinkRequest(BaseModel):
    company_id:   str
    oa_token:     str
    tms_username: str


@router.post("/line/generate-link")
def generate_link(body: GenerateLinkRequest):
    token      = str(uuid.uuid4()).replace("-", "")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)

    base_url  = os.getenv("AUTH_SERVER_URL", "http://localhost:5003")
    login_url = f"{base_url}/auth/line/login?token={token}&ngrok-skip-browser-warning=true"
    qr_b64    = _make_qr_base64(login_url)

    _pending_links[token] = {
        "company_id":   body.company_id,
        "oa_token":     body.oa_token,
        "tms_username": body.tms_username,
        "expires_at":   expires_at.isoformat(),
        "qr_base64":    qr_b64,
    }

    return {
        "success":        True,
        "login_url":      login_url,
        "qr_code_base64": qr_b64,
        "tms_id":         body.tms_username,
        "expires_at":     expires_at.isoformat(),
        "expires_in":     f"{TOKEN_TTL_MINUTES} minutes",
        "_hint":          'Render QR with: <img src="data:image/png;base64,{qr_code_base64}" />',
    }


# ─── Step 1: Show login page with QR pointing directly to LINE OAuth ─────────

@router.get("/line/login")
def line_login(token: str):
    link = _pending_links.get(token)
    if not link:
        raise HTTPException(status_code=404, detail="Login link not found or already used")

    expires_at = datetime.fromisoformat(link["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        del _pending_links[token]
        raise HTTPException(status_code=410, detail="Login link has expired")

    company_id   = link["company_id"]
    tms_username = link["tms_username"]

    # Generate OAuth state here so QR and button share the same state
    oauth_state = str(uuid.uuid4()).replace("-", "")
    _oauth_states[oauth_state] = token

    callback_url   = f"{AUTH_SERVER_URL}/auth/line/callback"
    line_oauth_url = (
        f"https://access.line.me/oauth2/v2.1/authorize"
        f"?response_type=code"
        f"&client_id={LINE_CLIENT_ID}"
        f"&redirect_uri={callback_url}"
        f"&state={oauth_state}"
        f"&scope=profile%20openid"
    )

    # QR encodes LINE OAuth URL directly — scanning opens LINE login immediately
    qr_b64 = _make_qr_base64(line_oauth_url)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Login with LINE</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #f0f0f0;
                display: flex; align-items: center; justify-content: center;
                min-height: 100vh; padding: 16px;
            }}
            .card {{
                background: white; border-radius: 16px; padding: 32px 28px;
                width: 100%; max-width: 400px;
                box-shadow: 0 4px 24px rgba(0,0,0,0.10); text-align: center;
            }}
            .line-logo {{
                width: 60px; height: 60px; background: #06C755; border-radius: 14px;
                margin: 0 auto 20px; display: flex; align-items: center;
                justify-content: center; padding: 10px;
            }}
            h1 {{ font-size: 20px; font-weight: 700; color: #111; margin-bottom: 6px; }}
            .subtitle {{ font-size: 14px; color: #888; margin-bottom: 20px; }}
            .info-box {{
                background: #f8f8f8; border-radius: 8px;
                padding: 14px; margin-bottom: 20px; text-align: left;
            }}
            .info-row {{
                display: flex; justify-content: space-between;
                font-size: 13px; margin-bottom: 6px;
            }}
            .info-row:last-child {{ margin-bottom: 0; }}
            .info-label {{ color: #888; }}
            .info-value {{ color: #111; font-weight: 600; }}
            .qr-section {{ margin-bottom: 20px; }}
            .qr-label {{
                font-size: 13px; font-weight: 600; color: #333;
                margin-bottom: 6px;
            }}
            .qr-hint {{ font-size: 12px; color: #888; margin-bottom: 10px; }}
            .qr-section img {{
                width: 180px; height: 180px;
                border: 1px solid #e5e5e5; border-radius: 8px; padding: 4px;
            }}
            .divider {{
                display: flex; align-items: center; gap: 10px;
                margin: 20px 0; color: #bbb; font-size: 12px;
            }}
            .divider::before, .divider::after {{
                content: ''; flex: 1; height: 1px; background: #e5e5e5;
            }}
            .btn {{
                display: flex; align-items: center; justify-content: center; gap: 10px;
                width: 100%; padding: 14px; background: #06C755; color: white;
                font-size: 16px; font-weight: 700; border: none; border-radius: 10px;
                cursor: pointer; text-decoration: none;
            }}
            .btn:hover {{ background: #05b34c; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="line-logo">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="40" height="40">
                    <path d="M19.365 9.863c.349 0 .63.285.63.631 0 .345-.281.63-.63.63H17.61v1.125h1.755c.349 0 .63.283.63.63 0 .344-.281.629-.63.629h-2.386c-.345 0-.627-.285-.627-.629V8.108c0-.345.282-.63.627-.63h2.386c.349 0 .63.285.63.63 0 .349-.281.63-.63.63H17.61v1.125h1.755zm-3.855 3.016c0 .27-.174.51-.432.596-.064.021-.133.031-.199.031-.211 0-.391-.09-.51-.25l-2.443-3.317v2.94c0 .344-.279.629-.631.629-.346 0-.626-.285-.626-.629V8.108c0-.27.173-.51.43-.595.06-.023.136-.033.194-.033.195 0 .375.104.495.254l2.462 3.33V8.108c0-.345.282-.63.63-.63.345 0 .63.285.63.63v4.771zm-5.741 0c0 .344-.282.629-.631.629-.345 0-.627-.285-.627-.629V8.108c0-.345.282-.63.627-.63.349 0 .631.285.631.63v4.771zm-2.466.629H4.917c-.345 0-.63-.285-.63-.629V8.108c0-.345.285-.63.63-.63.348 0 .63.285.63.63v4.141h1.756c.348 0 .629.283.629.63 0 .344-.281.629-.629.629M24 10.314C24 4.943 18.615.572 12 .572S0 4.943 0 10.314c0 4.811 4.27 8.842 10.035 9.608.391.082.923.258 1.058.59.12.301.079.766.038 1.08l-.164 1.02c-.045.301-.24 1.186 1.049.645 1.291-.539 6.916-4.070 9.436-6.975C23.176 14.393 24 12.458 24 10.314"/>
                </svg>
            </div>
            <h1>Login with LINE</h1>
            <p class="subtitle">Authorize TMS to send you delivery notifications</p>
            <div class="info-box">
                <div class="info-row">
                    <span class="info-label">Company</span>
                    <span class="info-value">{company_id}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">TMS User</span>
                    <span class="info-value">{tms_username}</span>
                </div>
            </div>
            <div class="qr-section">
                <p class="qr-label">📱 Scan with LINE app to login</p>
                <p class="qr-hint">Open LINE → tap the QR icon in the top-right → scan</p>
                <img src="data:image/png;base64,{qr_b64}" alt="QR Code" />
            </div>
            <div class="divider">or on desktop</div>
            <a class="btn" href="{line_oauth_url}">
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="white">
                    <path d="M19.365 9.863c.349 0 .63.285.63.631 0 .345-.281.63-.63.63H17.61v1.125h1.755c.349 0 .63.283.63.63 0 .344-.281.629-.63.629h-2.386c-.345 0-.627-.285-.627-.629V8.108c0-.345.282-.63.627-.63h2.386c.349 0 .63.285.63.63 0 .349-.281.63-.63.63H17.61v1.125h1.755zm-3.855 3.016c0 .27-.174.51-.432.596-.064.021-.133.031-.199.031-.211 0-.391-.09-.51-.25l-2.443-3.317v2.94c0 .344-.279.629-.631.629-.346 0-.626-.285-.626-.629V8.108c0-.27.173-.51.43-.595.06-.023.136-.033.194-.033.195 0 .375.104.495.254l2.462 3.33V8.108c0-.345.282-.63.63-.63.345 0 .63.285.63.63v4.771zm-5.741 0c0 .344-.282.629-.631.629-.345 0-.627-.285-.627-.629V8.108c0-.345.282-.63.627-.63.349 0 .631.285.631.63v4.771zm-2.466.629H4.917c-.345 0-.63-.285-.63-.629V8.108c0-.345.285-.63.63-.63.348 0 .63.285.63.63v4.141h1.756c.348 0 .629.283.629.63 0 .344-.281.629-.629.629M24 10.314C24 4.943 18.615.572 12 .572S0 4.943 0 10.314c0 4.811 4.27 8.842 10.035 9.608.391.082.923.258 1.058.59.12.301.079.766.038 1.08l-.164 1.02c-.045.301-.24 1.186 1.049.645 1.291-.539 6.916-4.070 9.436-6.975C23.176 14.393 24 12.458 24 10.314"/>
                </svg>
                Login with LINE
            </a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# ─── Step 2: LINE redirects back here with code + state ──────────────────────

@router.get("/line/callback")
async def line_callback(code: str = None, state: str = None, error: str = None):
    if error:
        raise HTTPException(status_code=400, detail=f"LINE OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state from LINE")

    token = _oauth_states.get(state)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    link = _pending_links.get(token)
    if not link:
        raise HTTPException(status_code=400, detail="Login link not found or already used")

    tms_username = link["tms_username"]
    company_id   = link["company_id"]

    callback_url = f"{AUTH_SERVER_URL}/auth/line/callback"
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://api.line.me/oauth2/v2.1/token",
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  callback_url,
                "client_id":     LINE_CLIENT_ID,
                "client_secret": LINE_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )

    if token_resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"LINE token exchange failed: {token_resp.text}")

    access_token = token_resp.json().get("access_token")

    async with httpx.AsyncClient() as client:
        profile_resp = await client.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )

    if profile_resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"LINE profile fetch failed: {profile_resp.text}")

    profile      = profile_resp.json()
    line_user_id = profile.get("userId")
    display_name = profile.get("displayName", "")
    picture_url  = profile.get("pictureUrl", "")

    tms_base_url = os.getenv("TMS_LINE_PROVIDER_URL", "http://tms-line-provider:5002")
    admin_token  = os.getenv("ADMIN_TOKEN", "TEST_TOKEN_12345")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{tms_base_url}/api/line-tms/link",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"tms_id": tms_username, "line_id": line_user_id},
            timeout=10,
        )

    del _oauth_states[state]
    del _pending_links[token]

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Failed to register: {resp.text}")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Authorized</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #f0f0f0;
                display: flex; align-items: center; justify-content: center;
                min-height: 100vh;
            }}
            .card {{
                background: white; border-radius: 16px; padding: 40px 32px;
                width: 100%; max-width: 380px;
                box-shadow: 0 4px 24px rgba(0,0,0,0.10); text-align: center;
            }}
            .avatar {{
                width: 72px; height: 72px; border-radius: 50%;
                margin: 0 auto 16px; object-fit: cover; border: 3px solid #06C755;
            }}
            .check {{
                width: 64px; height: 64px; background: #06C755; border-radius: 50%;
                margin: 0 auto 24px; display: flex; align-items: center;
                justify-content: center; font-size: 32px;
            }}
            h1 {{ font-size: 20px; font-weight: 700; color: #111; margin-bottom: 8px; }}
            .subtitle {{ font-size: 14px; color: #888; margin-bottom: 24px; }}
            .info-box {{
                background: #f8f8f8; border-radius: 8px; padding: 16px; text-align: left;
            }}
            .info-row {{
                display: flex; justify-content: space-between;
                font-size: 13px; margin-bottom: 6px;
            }}
            .info-row:last-child {{ margin-bottom: 0; }}
            .info-label {{ color: #888; }}
            .info-value {{
                color: #111; font-weight: 600;
                word-break: break-all; max-width: 60%; text-align: right;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            {"<img class='avatar' src='" + picture_url + "' />" if picture_url else "<div class='check'>✓</div>"}
            <h1>You're all set, {display_name}!</h1>
            <p class="subtitle">LINE notifications are now enabled for your account.</p>
            <div class="info-box">
                <div class="info-row">
                    <span class="info-label">LINE ID</span>
                    <span class="info-value">{line_user_id}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">TMS ID</span>
                    <span class="info-value">{tms_username}</span>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)