from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.admin_routes import router as admin_router
from app.auth import channel_key, get_current_user_from_ws
from app.config import CLIENT_DOWNLOAD_URL
from app.database import SessionLocal, init_db
from app.routes import router
from app.poi_upload import ensure_upload_dir
from app.radiation_upload import ensure_overlay_dir
from app.websocket import manager

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_upload_dir()
    ensure_overlay_dir()
    await init_db()
    yield


app = FastAPI(title="DayZ Map", lifespan=lifespan)
app.include_router(router)
app.include_router(admin_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


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
        ch = channel_key(user.room.map_id, user.room_id)

    await manager.connect(ch, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(ch, websocket)


app.mount("/uploads", StaticFiles(directory=ensure_upload_dir()), name="uploads")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
