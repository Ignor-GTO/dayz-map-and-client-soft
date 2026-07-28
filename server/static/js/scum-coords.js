/**
 * SCUM game ↔ pixel ↔ Leaflet helpers.
 * Calibration from PauloPedreiro/Scum-maps-Index (MIT), scaled to mustard tile
 * space (16×1280 = 20480 px at Leaflet max zoom 4 / folder zoom 6).
 */
const SCUM_COORDS = (() => {
  const MAP_PX = 20480;
  const TILE_SIZE = 1280;
  const MIN_ZOOM = 0;
  const MAX_ZOOM = 4;
  const ZOOM_OFFSET = 2;
  const CENTER_X = -142798.922;
  const CENTER_Y = -142780.359;
  const BASE_MAP = 1080;
  const BASE_CENTER_PX = 540;
  const SCALE_X_1080 = 0.0007086597262557765;
  const SCALE_Y_1080 = -0.0007086778791895953;
  const SCALE = MAP_PX / BASE_MAP;
  const CENTER_PX = BASE_CENTER_PX * SCALE;
  const CENTER_PY = BASE_CENTER_PX * SCALE;
  const SCALE_X = SCALE_X_1080 * SCALE;
  const SCALE_Y = SCALE_Y_1080 * SCALE;

  const BOUNDS = {
    min_x: -920000,
    max_x: 640000,
    min_y: -920000,
    max_y: 640000,
  };

  function gameToPixel(gx, gy) {
    const calcX = CENTER_PX + (Number(gx) - CENTER_X) * SCALE_X;
    const calcY = CENTER_PY + (Number(gy) - CENTER_Y) * SCALE_Y;
    const px = MAP_PX - calcX;
    const py = calcY;
    return {
      x: Math.max(0, Math.min(MAP_PX, px)),
      y: Math.max(0, Math.min(MAP_PX, py)),
    };
  }

  function pixelToGame(px, py) {
    const calcX = MAP_PX - Number(px);
    const calcY = Number(py);
    return {
      x: CENTER_X + (calcX - CENTER_PX) / SCALE_X,
      y: CENTER_Y + (calcY - CENTER_PY) / SCALE_Y,
    };
  }

  function parseClipboard(text) {
    const raw = String(text || "").trim();
    if (!raw) return null;
    const m = raw.match(/X\s*=\s*(-?\d+(?:\.\d+)?)\s*Y\s*=\s*(-?\d+(?:\.\d+)?)/i);
    if (!m) return null;
    const x = Number(m[1]);
    const y = Number(m[2]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return { x, y };
  }

  return {
    MAP_PX,
    TILE_SIZE,
    MIN_ZOOM,
    MAX_ZOOM,
    ZOOM_OFFSET,
    BOUNDS,
    CENTER_X,
    CENTER_Y,
    gameToPixel,
    pixelToGame,
    parseClipboard,
  };
})();
