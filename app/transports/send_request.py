import requests
from typing import Any, Dict, Optional

class CenterService:
    _instance = None

    def __new__(cls, base_url: str = None, token: str = None, timeout: int = 360):
        if cls._instance is None:
            if not base_url or not token:
                raise ValueError("CenterService must be initialized with base_url and token")

            cls._instance = super(CenterService, cls).__new__(cls)

            # Initialize only once
            cls._instance.base_url = base_url.rstrip("/")
            cls._instance.token = token
            cls._instance.timeout = timeout

            cls._instance.session = requests.Session()
            cls._instance.session.headers.update({
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            })

        return cls._instance

    def request(
        self,
        method: str,
        endpoint: str,
        data=None,
        headers=None,
    ):

        url = f"{self.base_url}{endpoint}"
        print(f"Url : {url}")

        response = self.session.request(
            method=method,
            url=url,
            json=data,
            headers=headers,
            timeout=self.timeout,
        )
        
        print(f"Done sending order : {response.status_code}")

        return {
            "status_code": response.status_code,
            "json": response.json() if response.content else None,
            "text": response.text,
            "headers": dict(response.headers),
        }

