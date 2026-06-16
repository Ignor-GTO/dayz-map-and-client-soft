from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import get_current_user_from_ws
from app.config import (
    CLIENT_DOWNLOAD_URL,
    MAP_ATTRIBUTION,
    MAP_BOUNDS,
    MAP_EXTRA_ZOOM,
    MAP_MAX_NATIVE_ZOOM,
    MAP_SIZE,
    MAP_TILES_SATELLITE,
    MAP_TILES_TOPOGRAPHIC,
    SERVER_PUBLIC_URL,
)
from app.database import SessionLocal, init_db
from app.routes import router
from app.websocket import manager

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="DayZ Pripyat Map", lifespan=lifespan)
app.include_router(router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/map/config")
async def map_config():
    return {
        "bounds": MAP_BOUNDS,
        "map_size": MAP_SIZE,
        "max_native_zoom": MAP_MAX_NATIVE_ZOOM,
        "extra_zoom": MAP_EXTRA_ZOOM,
        "tiles_satellite": MAP_TILES_SATELLITE,
        "tiles_topographic": MAP_TILES_TOPOGRAPHIC,
        "attribution": MAP_ATTRIBUTION,
        "server_url": SERVER_PUBLIC_URL,
        "client_download_url": CLIENT_DOWNLOAD_URL,
    }


@app.get("/api/download/client")
async def download_client():
    return RedirectResponse(url=CLIENT_DOWNLOAD_URL, status_code=302)


@app.websocket("/ws/map")
async def map_websocket(websocket: WebSocket):
    token = websocket.cookies.get("dayz_map_session")
    async with SessionLocal() as db:
        user = await get_current_user_from_ws(db, token)
        if not user:
            await websocket.close(code=4401)
            return
        room_id = user.room_id

    await manager.connect(room_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(room_id, websocket)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
