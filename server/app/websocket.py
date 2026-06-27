import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._channels[channel].add(websocket)

    async def subscribe(self, channel: str, websocket: WebSocket) -> None:
        """Subscribe an already-accepted websocket to an additional channel."""
        async with self._lock:
            self._channels[channel].add(websocket)

    async def disconnect(self, channel: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._channels[channel].discard(websocket)
            if not self._channels[channel]:
                del self._channels[channel]

    async def broadcast(self, channel: str, message: dict) -> None:
        async with self._lock:
            sockets = list(self._channels.get(channel, []))
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._channels[channel].discard(ws)

    async def send_to_user(self, user_id: int, message: dict) -> None:
        """Send a message only to the specific user's browser tab(s)."""
        await self.broadcast(f"user:{user_id}", message)


manager = ConnectionManager()
