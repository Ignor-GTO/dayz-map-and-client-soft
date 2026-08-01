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

    def send_marker(self, x: float, y: float, marker_type: str = "marker") -> tuple[bool, str]:
        try:
            r = httpx.post(
                f"{self.base}/api/client/marker",
                json={"x": x, "y": y, "type": marker_type},
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

    def send_command(self, action: str) -> tuple[bool, str]:
        try:
            r = httpx.post(
                f"{self.base}/api/client/command",
                json={"action": action},
                headers=self.headers,
                timeout=5,
            )
            if r.status_code == 200:
                return True, ""
            return False, f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            return False, f"Ошибка сети: {e}"

    def set_steam_id(self, steam_id: str) -> tuple[bool, str]:
        try:
            r = httpx.post(
                f"{self.base}/api/client/steam-id",
                json={"steam_id": steam_id},
                headers=self.headers,
                timeout=10,
            )
            if r.status_code == 200:
                return True, ""
            try:
                detail = r.json().get("detail") or r.text
            except Exception:
                detail = r.text
            return False, f"HTTP {r.status_code}: {detail}"
        except httpx.HTTPError as e:
            return False, f"Ошибка сети: {e}"

    def create_overlay_handoff(self, map_slug: str = "scum") -> tuple[str | None, str]:
        """Return absolute overlay-enter URL that sets the browser session cookie."""
        try:
            r = httpx.post(
                f"{self.base}/api/auth/overlay-handoff",
                json={"map_slug": map_slug},
                headers=self.headers,
                timeout=10,
            )
            if r.status_code != 200:
                try:
                    detail = r.json().get("detail") or r.text
                except Exception:
                    detail = r.text
                return None, f"HTTP {r.status_code}: {detail}"
            data = r.json()
            path = (data.get("url") or data.get("path") or "").strip()
            if not path:
                return None, "Сервер не вернул URL оверлея"
            if path.startswith("http://") or path.startswith("https://"):
                return path, ""
            return f"{self.base}{path if path.startswith('/') else '/' + path}", ""
        except httpx.HTTPError as e:
            return None, f"Ошибка сети: {e}"
