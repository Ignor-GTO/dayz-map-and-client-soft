import httpx


class MapClient:
    def __init__(self, server_url: str, client_key: str) -> None:
        self.base = server_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {client_key}"}

    def send_position(self, x: float, y: float) -> tuple[bool, str]:
        try:
            r = httpx.post(
                f"{self.base}/api/client/position",
                json={"x": x, "y": y},
                headers=self.headers,
                timeout=10,
            )
            if r.status_code == 200:
                return True, ""
            return False, f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            return False, f"Ошибка сети: {e}"

    def send_marker(self, x: float, y: float) -> tuple[bool, str]:
        try:
            r = httpx.post(
                f"{self.base}/api/client/marker",
                json={"x": x, "y": y},
                headers=self.headers,
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                print(f"[Метка] id={data.get('id')} → {x:.0f} / {y:.0f}")
                return True, ""
            return False, f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            return False, f"Ошибка сети: {e}"
