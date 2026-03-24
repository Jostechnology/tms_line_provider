from app.transports.send_request import CenterService

_center_service = None

def init_center_service(CENTER_ACCESS_KEY, CENTER_URL):
    global _center_service
    _center_service = CenterService(
        base_url=CENTER_URL,
        token=CENTER_ACCESS_KEY
    )
    print(f"Center Service : {_center_service}")

def get_center_service():
    if _center_service is None:
        raise RuntimeError("CenterService not initialized")
    return _center_service