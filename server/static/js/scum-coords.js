/**
 * SCUM game ↔ pixel ↔ Leaflet helpers.
 *
 * Projection matches scum-map.com ScumMapCoordsHelper
 * (gameLngLeft=619200, gameWholeLng=1524000, map 0..320 → scaled to 20480 px).
 * Tiles: mustard/scum-map 16×1280 at Leaflet max zoom 4 (folder zoom 6).
 * Sector grid: 5×5 (D4–Z0) + 3×3 keypad (K1–K9), same as scum-map.com.
 */
const SCUM_COORDS = (() => {
  const MAP_PX = 20480;
  const TILE_SIZE = 1280;
  const MIN_ZOOM = 0;
  const MAX_ZOOM = 4;
  const ZOOM_OFFSET = 2;

  // scum-map.com ScumMapCoordsHelper constants
  const GAME_LNG_LEFT = 619200; // west edge (max X)
  const GAME_LAT_TOP = 619199.9375; // north edge (max Y)
  const GAME_WHOLE_LNG = 1524000;
  const GAME_WHOLE_LAT = 1523999.9375;
  const MAP_MAX = 320; // scum-map CRS units; we scale to MAP_PX
  const SECTOR_AMOUNT = 5;
  const SECTOR_WIDTH = MAP_MAX / SECTOR_AMOUNT; // 64
  const KEYPAD_DIV = 15; // 5 sectors × 3 keypad
  const KEYPAD_WIDTH = MAP_MAX / KEYPAD_DIV; // 21.333…
  const SECTOR_LETTERS = ["D", "C", "B", "A", "Z"];

  const CENTER_X = GAME_LNG_LEFT - GAME_WHOLE_LNG / 2;
  const CENTER_Y = GAME_LAT_TOP - GAME_WHOLE_LAT / 2;

  const BOUNDS = {
    min_x: GAME_LNG_LEFT - GAME_WHOLE_LNG,
    max_x: GAME_LNG_LEFT,
    min_y: GAME_LAT_TOP - GAME_WHOLE_LAT,
    max_y: GAME_LAT_TOP,
  };

  function mapToPixel(mapX, mapY) {
    return {
      x: (Number(mapX) / MAP_MAX) * MAP_PX,
      y: (Number(mapY) / MAP_MAX) * MAP_PX,
    };
  }

  function gameToMap(gx, gy) {
    return {
      x: (MAP_MAX * (GAME_LNG_LEFT - Number(gx))) / GAME_WHOLE_LNG,
      y: (MAP_MAX * (GAME_LAT_TOP - Number(gy))) / GAME_WHOLE_LAT,
    };
  }

  function mapToGame(mapX, mapY) {
    return {
      x: GAME_LNG_LEFT - (GAME_WHOLE_LNG * Number(mapX)) / MAP_MAX,
      y: GAME_LAT_TOP - (GAME_WHOLE_LAT * Number(mapY)) / MAP_MAX,
    };
  }

  function gameToPixel(gx, gy) {
    const m = gameToMap(gx, gy);
    const p = mapToPixel(m.x, m.y);
    return {
      x: Math.max(0, Math.min(MAP_PX, p.x)),
      y: Math.max(0, Math.min(MAP_PX, p.y)),
    };
  }

  function pixelToGame(px, py) {
    const mapX = (Number(px) / MAP_PX) * MAP_MAX;
    const mapY = (Number(py) / MAP_PX) * MAP_MAX;
    const g = mapToGame(mapX, mapY);
    return {
      x: Math.round(g.x * 1e6) / 1e6,
      y: Math.round(g.y * 1e6) / 1e6,
    };
  }

  /** Phone keypad cell number for row/col in 1..3 (matches scum-map calculateKeypad). */
  function keypadNumber(row, col) {
    const table = [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, 9],
    ];
    return table[row - 1][col - 1];
  }

  function sectorLetterForKeypadRow(n) {
    if (n >= 1 && n <= 3) return "D";
    if (n >= 4 && n <= 6) return "C";
    if (n >= 7 && n <= 9) return "B";
    if (n >= 10 && n <= 12) return "A";
    if (n >= 13 && n <= 15) return "Z";
    return "?";
  }

  /** Sector code like B4K1 for game coords (scum-map calculateSectorLocation). */
  function sectorCode(gx, gy) {
    const m = gameToMap(gx, gy);
    if (!Number.isFinite(m.x) || !Number.isFinite(m.y)) return "??";
    if (m.x < 0 || m.x > MAP_MAX || m.y < 0 || m.y > MAP_MAX) return "??";

    const r = KEYPAD_WIDTH;
    for (let n = 1; n <= KEYPAD_DIV; n += 1) {
      for (let o = 1; o <= SECTOR_AMOUNT; o += 1) {
        const i = SECTOR_WIDTH * (o - 1);
        for (let c = 1; c <= 3; c += 1) {
          const left = i + (c - 1) * r;
          const right = i + c * r;
          const top = (n - 1) * r;
          const bottom = n * r;
          if (m.x >= left && m.x <= right && m.y >= top && m.y <= bottom) {
            const colNum = 5 - o;
            const keyRow = 3 - ((n - 1) % 3);
            const key = keypadNumber(keyRow, c);
            return `${sectorLetterForKeypadRow(n)}${colNum}K${key}`;
          }
        }
      }
    }
    return "??";
  }

  /** Major sector label (D4…Z0) without keypad. */
  function sectorMajor(gx, gy) {
    const code = sectorCode(gx, gy);
    if (!code || code === "??") return "??";
    return code.replace(/K\d$/, "");
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

  /** UE rotation_z → CSS degrees for live-player heading (cone default points south). */
  function gameYawToCssDeg(yaw) {
    const n = Number(yaw);
    if (!Number.isFinite(n)) return null;
    return 90 - n;
  }

  return {
    MAP_PX,
    TILE_SIZE,
    MIN_ZOOM,
    MAX_ZOOM,
    ZOOM_OFFSET,
    MAP_MAX,
    SECTOR_AMOUNT,
    SECTOR_WIDTH,
    KEYPAD_DIV,
    KEYPAD_WIDTH,
    SECTOR_LETTERS,
    BOUNDS,
    CENTER_X,
    CENTER_Y,
    GAME_LNG_LEFT,
    GAME_LAT_TOP,
    GAME_WHOLE_LNG,
    GAME_WHOLE_LAT,
    mapToPixel,
    mapToGame,
    gameToMap,
    gameToPixel,
    pixelToGame,
    sectorCode,
    sectorMajor,
    parseClipboard,
    gameYawToCssDeg,
  };
})();
