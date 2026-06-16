import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR / 'dayz_map.db'}")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
SESSION_COOKIE = "dayz_map_session"

MAP_SIZE = float(os.getenv("MAP_SIZE", "20480"))
MAP_MAX_NATIVE_ZOOM = int(os.getenv("MAP_MAX_NATIVE_ZOOM", "7"))
MAP_EXTRA_ZOOM = int(os.getenv("MAP_EXTRA_ZOOM", "3"))

MAP_TILES_SATELLITE = os.getenv(
    "MAP_TILES_SATELLITE",
    "https://static.xam.nu/dayz/maps/pripyat/19.08/satellite/{z}/{x}/{y}.jpg",
)
MAP_TILES_TOPOGRAPHIC = os.getenv(
    "MAP_TILES_TOPOGRAPHIC",
    "https://static.xam.nu/dayz/maps/pripyat/19.08/topographic/{z}/{x}/{y}.jpg",
)
MAP_ATTRIBUTION = os.getenv("MAP_ATTRIBUTION", "Tiles © Xam.nu")

MAP_BOUNDS = {
    "min_x": float(os.getenv("MAP_MIN_X", "0")),
    "max_x": float(os.getenv("MAP_MAX_X", str(int(MAP_SIZE)))),
    "min_y": float(os.getenv("MAP_MIN_Y", "0")),
    "max_y": float(os.getenv("MAP_MAX_Y", str(int(MAP_SIZE)))),
}

DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "9029902901")
CLIENT_DOWNLOAD_URL = os.getenv(
    "CLIENT_DOWNLOAD_URL",
    "https://github.com/Ignor-GTO/dayz-map-and-client-soft/releases/latest/download/DayZMapClient.exe",
)

SERVER_PUBLIC_URL = os.getenv("SERVER_PUBLIC_URL", "https://dayz-map.gto-team.uz")
