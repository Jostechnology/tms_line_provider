from app.extensions import get_center_service

def register_user(customer_code, customer_tax_number, user_id):
    try:
        print(f"Registering {customer_code} {user_id}")
        center_service = get_center_service()
        response = center_service.request(
            method="POST",
            endpoint="/api/customer/register_line_user",
            data={
                "customer_code": customer_code,
                "customer_tax_number": customer_tax_number,
                "user_id": user_id
            }
        )
        data = response["json"]
        return data, response['status_code']
    except Exception:
        raise

def find_user(customer_code):
    try:
        center_service = get_center_service()
        response = center_service.request(
            method="POST",
            endpoint="/api/customer/get_by_code",
            data={
                "customer_code": customer_code,
            }
        )
        data = response["json"]
        return data, response['status_code']
    except Exception:
        raise

def get_customer_route(user_id):
    try:
        center_service = get_center_service()
        response = center_service.request(
            method="POST",
            endpoint="/api/gps/generate-token",
            data={
                "line_user_id": user_id,
            }
        )
        data = response["json"]
        return data, response['status_code']
    except Exception:
        raise