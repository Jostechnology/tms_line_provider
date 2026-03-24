from app.extensions import get_center_service

def make_order(text, user_id, customer_code = None):
    try:
        center_service = get_center_service()
        response = center_service.request(
            method="POST",
            endpoint="/api/ai/bot_make_order",
            data={
                "text" : text,
                "user_id": user_id,
                "customer_code" : customer_code
            }
        )
        data = response["json"]
        return data, response['status_code']
    except Exception:
        raise