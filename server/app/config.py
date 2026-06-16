import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR / 'dayz_map.db'}")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
SESSION_COOKIE = "dayz_map_session"

# Pripyat world bounds for coordinate → map pixel mapping (tune if needed)
MAP_BOUNDS = {
    "min_x": float(os.getenv("MAP_MIN_X", "0")),
    "max_x": float(os.getenv("MAP_MAX_X", "15360")),
    "min_y": float(os.getenv("MAP_MIN_Y", "0")),
    "max_y": float(os.getenv("MAP_MAX_Y", "15360")),
}

SERVER_PUBLIC_URL = os.getenv("SERVER_PUBLIC_URL", "https://dayz-map.gto-team.uz")
CLIENT_DOWNLOAD_URL = os.getenv(
    "CLIENT_DOWNLOAD_URL",
    "https://github.com/Ignor-GTO/dayz-map-and-client-soft/releases/latest/download/DayZMapClient.exe",
)
