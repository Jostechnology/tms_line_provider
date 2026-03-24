from app.config import CENTER_ACCESS_KEY, LINE_CHANNEL_SECRET
from functools import wraps
from flask import request, jsonify, g

def verify_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if "Authorization" in request.headers:
            parts = request.headers["Authorization"].split(" ")
            if len(parts) == 2 and parts[0] == "Bearer":
                token = parts[1]

        if not token:
            try:
                body = request.get_json(silent=True)
                if body and "token" in body:
                    token = body["token"]
            except Exception:
                pass

        if not token:
            return jsonify({"message": "Missing token"}), 401
        
        if token == LINE_CHANNEL_SECRET:
            g.username = "SYSTEM_CENTER"
            return f(*args, **kwargs)
        else:
            return jsonify({"message": "Invalid or expired token"}), 401

    return decorated