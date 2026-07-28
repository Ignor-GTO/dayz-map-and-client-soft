const state = {
  map: null,
  tileLayer: null,
  layerType: "satellite",
  config: null,
  scumBounds: null,
  me: null,
  clientKey: null,
  userAvatars: new Map(),
  liveMarkers: new Map(),
  pinMarkers: new Map(),
  poiMarkers: new Map(),
  locationLayer: null,
  locationEntries: [],
  radiationLayer: null,
  psiLayer: null,
  radiationOverlay: null,
  // Roads & Navigator
  roadLayer: null,          // L.layerGroup for road polylines
  buildingLayer: null,      // L.layerGroup for server building footprints
  navActive: false,         // navigator mode on/off
  navStep: "from",          // "from" | "to"
  navFrom: null,            // {x, y} game coords
  navTo: null,              // {x, y} game coords
  navFromMarker: null,
  navToMarker: null,
  navRouteLayer: null,      // L.polyline of computed route
  navRoutePoints: [],
  navRouteManeuvers: [],
  navSimInterval: null,
  navSimPathIndex: 0,
  navSimDistanceCovered: 0,
  navSimMarker: null,
  coordLookupMarker: null,
  contextMenuCoords: null,
  lastMouseGameCoords: null,
  navLastAnnouncedIndex: -1,
  navLastAnnouncedPrepIndex: -1,
  navAnnouncedRadZones: new Set(),
  radiationData: null,
  filters: {
    labels: true,
    cities: true,
    military: true,
    local: true,
    water: true,
    terrain: true,
    players: true,
    markers: true,
    stashes: false,
    mutants: true,
    hunting: true,
    poi: true,
    radiation: true,
    psi: true,
    roads: false,
    buildings: true,
  },
  draw: {
    mode: null, // null | "point" | "circle" | "line"
    linePoints: [],
    tempLayer: null,
  },
  geoEdit: {
    markerId: null,
    kind: null, // null | "circle" | "line"
    center: null, // {x, y}
    radius: null,
    points: [],
    handles: [],
    previewLayer: null,
  },
  commandZoomAnchor: null,
  commandZoomApplying: false,
  zoneHoverTooltip: null,
  ws: null,
};

const FILTER_PREFS_KEY = "dayz_map_filters_v1";
const MAP_VIEW_PREFS_KEY_PREFIX = "dayz_map_view_v1_";

function loadFilterPrefs() {
  try {
    const raw = localStorage.getItem(FILTER_PREFS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveFilterPrefs() {
  try {
    const prefs = {};
    Object.entries(state.filters).forEach(([key, value]) => {
      if (typeof value === "boolean") {
        prefs[key] = value;
      }
    });
    localStorage.setItem(
      FILTER_PREFS_KEY,
      JSON.stringify(prefs),
    );
  } catch {
    // ignore storage failures (private mode / quota)
  }
}

function hydrateFilterPrefs() {
  const prefs = loadFilterPrefs();
  Object.entries(prefs).forEach(([key, value]) => {
    if (typeof value === "boolean") {
      state.filters[key] = value;
    }
  });
}

hydrateFilterPrefs();

function mapViewStorageKey() {
  const slug = state.me?.map_slug || "default";
  return `${MAP_VIEW_PREFS_KEY_PREFIX}${slug}`;
}

function saveMapView() {
  if (!state.map || !state.me) return;
  const center = state.map.getCenter();
  const game = latLngToGame(center);
  try {
    localStorage.setItem(
      mapViewStorageKey(),
      JSON.stringify({
        x: Number(game.x.toFixed(2)),
        y: Number(game.y.toFixed(2)),
        zoom: state.map.getZoom(),
      }),
    );
  } catch {
    // ignore storage failures
  }
}

function restoreMapView() {
  if (!state.map || !state.me) return false;
  try {
    const raw = localStorage.getItem(mapViewStorageKey());
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    if (
      typeof parsed?.x !== "number"
      || typeof parsed?.y !== "number"
      || typeof parsed?.zoom !== "number"
    ) {
      return false;
    }
    const minZoom = state.map.getMinZoom();
    const maxZoom = state.map.getMaxZoom();
    const zoom = Math.max(minZoom, Math.min(maxZoom, parsed.zoom));
    state.map.setView(gameToLatLng(parsed.x, parsed.y), zoom, { animate: false });
    return true;
  } catch {
    return false;
  }
}


const TILE_BOUNDS = L.latLngBounds(L.latLng(0, 0), L.latLng(-256, 256));
const MAP_MAX_BOUNDS = TILE_BOUNDS;

function isScumConfig(config = state.config) {
  return (config?.coord_system || "").toLowerCase() === "scum";
}

function activeMapBounds(config = state.config) {
  if (isScumConfig(config) && state.scumBounds) return state.scumBounds;
  return TILE_BOUNDS;
}

function mapSize(config) {
  return config.map_size || config.bounds?.max_x || 20480;
}

function gameToLatLng(x, y, config = state.config) {
  if (isScumConfig(config)) {
    if (!state.map || typeof SCUM_COORDS === "undefined") {
      return L.latLng(0, 0);
    }
    const pixel = SCUM_COORDS.gameToPixel(x, y);
    return state.map.unproject([pixel.x, pixel.y], SCUM_COORDS.MAX_ZOOM);
  }
  const size = mapSize(config);
  const ratio = size / 256;
  return L.latLng(y / ratio - 256, x / ratio);
}

function gameBoundsToLatLng(bounds, config = state.config) {
  const x1 = bounds.x1 ?? config?.bounds?.min_x ?? 0;
  const y1 = bounds.y1 ?? config?.bounds?.min_y ?? 0;
  const x2 = bounds.x2 ?? config?.bounds?.max_x ?? mapSize(config);
  const y2 = bounds.y2 ?? config?.bounds?.max_y ?? mapSize(config);
  return L.latLngBounds(
    gameToLatLng(x1, y2, config),
    gameToLatLng(x2, y1, config),
  );
}

function gameRadiusToLeaflet(radius, config = state.config) {
  if (isScumConfig(config)) {
    if (!state.map || typeof SCUM_COORDS === "undefined") return 0;
    const origin = SCUM_COORDS.gameToPixel(SCUM_COORDS.CENTER_X, SCUM_COORDS.CENTER_Y);
    const edge = SCUM_COORDS.gameToPixel(SCUM_COORDS.CENTER_X + Number(radius || 0), SCUM_COORDS.CENTER_Y);
    const a = state.map.unproject([origin.x, origin.y], SCUM_COORDS.MAX_ZOOM);
    const b = state.map.unproject([edge.x, edge.y], SCUM_COORDS.MAX_ZOOM);
    return state.map.distance(a, b);
  }
  const ratio = mapSize(config) / 256;
  return radius / ratio;
}

function setTileLayer(type) {
  if (!state.map || !state.config) return;
  state.layerType = type;
  const url = type === "topographic"
    ? state.config.tiles_topographic
    : state.config.tiles_satellite;
  const maxNative = state.config.max_native_zoom || 7;
  const maxZoom = maxNative + (state.config.extra_zoom || 0);
  const minZoom = state.config.min_zoom ?? 0;
  const tileSize = state.config.tile_size || 256;
  const bounds = activeMapBounds(state.config);

  if (state.tileLayer) state.map.removeLayer(state.tileLayer);

  state.tileLayer = L.tileLayer(url, {
    tileSize,
    noWrap: true,
    minZoom,
    maxNativeZoom: maxNative,
    maxZoom,
    zoomOffset: state.config.zoom_offset || 0,
    bounds,
    attribution: state.config.attribution || "Tiles © Xam.nu",
  }).addTo(state.map);

  document.getElementById("btn-layer-sat")?.classList.toggle("active", type === "satellite");
  document.getElementById("btn-layer-topo")?.classList.toggle("active", type === "topographic");
  if (isScumConfig(state.config)) {
    document.getElementById("btn-layer-topo")?.classList.add("hidden");
  } else {
    document.getElementById("btn-layer-topo")?.classList.remove("hidden");
  }
}

function updateMinZoom() {
  if (!state.map) return;
  if (isScumConfig(state.config)) {
    state.map.setMinZoom(state.config.min_zoom ?? SCUM_COORDS?.MIN_ZOOM ?? 2);
    return;
  }
  const boundsZoom = state.map.getBoundsZoom(TILE_BOUNDS, false);
  state.map.setMinZoom(boundsZoom);
}

const PLAYER_COLORS = [
  "#ff4757", "#2ed573", "#1e90ff", "#ffa502", "#a55eea",
  "#ff6b81", "#70a1ff", "#7bed9f", "#eccc68", "#5352ed",
];

function colorForUser(userId) {
  return PLAYER_COLORS[userId % PLAYER_COLORS.length];
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = res.ok ? await res.json().catch(() => ({})) : null;
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (data?.detail) {
      msg = Array.isArray(data.detail)
        ? data.detail.map((d) => d.msg || d).join(", ")
        : data.detail;
    }
    throw new Error(msg);
  }
  return data;
}

function showLogin() {
  document.getElementById("login-view").classList.remove("hidden");
  document.getElementById("map-view").classList.add("hidden");
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
}

function showMap() {
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("map-view").classList.remove("hidden");
}

function waitForLayout() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

function refreshMapLayout() {
  if (!state.map) return;
  state.map.invalidateSize({ animate: false });
  updateMinZoom();
  const bounds = activeMapBounds(state.config);
  state.map.fitBounds(bounds, { animate: false });
  if (state.config) {
    const center = mapCenterLatLng(state.config);
    state.map.setView(center, state.map.getZoom(), { animate: false });
  }
}

function mapCenterLatLng(config = state.config) {
  if (isScumConfig(config) && typeof SCUM_COORDS !== "undefined") {
    return gameToLatLng(SCUM_COORDS.CENTER_X, SCUM_COORDS.CENTER_Y, config);
  }
  return gameToLatLng(mapSize(config) / 2, mapSize(config) / 2, config);
}

function showKeyModal(key) {
  state.clientKey = key;
  document.getElementById("client-key-display").textContent = key;
  document.getElementById("key-modal").classList.remove("hidden");
}

async function ensureClientKey() {
  if (state.clientKey) return state.clientKey;
  try {
    const data = await api("/api/auth/client-key");
    if (data?.client_key) {
      state.clientKey = data.client_key;
      return state.clientKey;
    }
  } catch {
    /* key not in session */
  }
  return null;
}

function initMapPanes(map) {
  if (!map.getPane("radiationPane")) {
    map.createPane("radiationPane");
    map.getPane("radiationPane").style.zIndex = 340;
  }
  if (!map.getPane("userShapesPane")) {
    map.createPane("userShapesPane");
    map.getPane("userShapesPane").style.zIndex = 430;
  }
  if (!map.getPane("labelsPane")) {
    map.createPane("labelsPane");
    map.getPane("labelsPane").style.zIndex = 480;
  }
  if (!map.getPane("buildingsPane")) {
    map.createPane("buildingsPane");
    map.getPane("buildingsPane").style.zIndex = 360;
  }
}

function initLeaflet(config) {
  const maxNative = config.max_native_zoom || 7;
  const maxZoom = maxNative + (config.extra_zoom || 0);
  const minZoom = config.min_zoom ?? 0;
  const scum = isScumConfig(config);

  state.map = L.map("map", {
    crs: L.CRS.Simple,
    minZoom,
    maxZoom,
    maxBounds: scum ? undefined : MAP_MAX_BOUNDS,
    maxBoundsViscosity: 1.0,
    zoomControl: true,
    attributionControl: true,
  });

  if (scum && typeof SCUM_COORDS !== "undefined") {
    const sw = state.map.unproject([0, SCUM_COORDS.MAP_PX], SCUM_COORDS.MAX_ZOOM);
    const ne = state.map.unproject([SCUM_COORDS.MAP_PX, 0], SCUM_COORDS.MAX_ZOOM);
    state.scumBounds = L.latLngBounds(sw, ne);
    state.map.setMaxBounds(state.scumBounds.pad(0.08));
  } else {
    state.scumBounds = null;
  }

  initMapPanes(state.map);
  state.locationLayer = L.layerGroup().addTo(state.map);
  state.radiationLayer = L.layerGroup().addTo(state.map);
  state.psiLayer = L.layerGroup().addTo(state.map);
  state.roadLayer = L.layerGroup().addTo(state.map);
  state.buildingLayer = L.layerGroup().addTo(state.map);
  state.map.on("zoomend", updateLocationVisibility);
  state.map.on("moveend", () => {
    // Keep anchor synced with where user is currently looking
    // unless this movement came from a programmatic client zoom step.
    if (!state.commandZoomApplying) {
      rememberCommandZoomAnchor(state.map.getCenter());
    }
    saveMapView();
  });
  state.map.on("zoomend", saveMapView);

  state.map.on("click", (e) => {
    closeMapContextMenu();
    rememberCommandZoomAnchor(e.latlng);
    const gameCoords = latLngToGame(e.latlng);
    if (state.draw.mode) {
      handleDrawMapClick(gameCoords.x, gameCoords.y);
      return;
    }
    if (state.navActive) {
      navSetPoint(gameCoords.x, gameCoords.y);
      return;
    }
    const matches = collectZonesAtGamePoint(gameCoords.x, gameCoords.y);
    if (matches.radiation.length || matches.psi.length) {
      L.popup({ maxWidth: 320 })
        .setLatLng(e.latlng)
        .setContent(zonesInfoHtml(matches, false))
        .openOn(state.map);
    }
  });
  state.map.on("mousemove", (e) => {
    updateMouseCoordsDisplay(e.latlng);
    if (state.draw.mode || state.navActive) {
      hideZoneHoverTooltip();
      return;
    }
    updateZoneHoverTooltip(e.latlng);
  });
  state.map.on("mouseout", () => {
    hideZoneHoverTooltip();
    updateMouseCoordsDisplay(null);
  });
  state.map.on("contextmenu", (e) => {
    L.DomEvent.preventDefault(e);
    const gameCoords = latLngToGame(e.latlng);
    showMapContextMenu(e.originalEvent.clientX, e.originalEvent.clientY, gameCoords);
  });

  // Handle popup action button clicks
  state.map.on("popupopen", (e) => {
    const container = e.popup.getElement();
    if (!container) return;

    const deleteBtn = container.querySelector(".marker-delete");
    if (deleteBtn) {
      deleteBtn.onclick = () => deleteMarker(Number(deleteBtn.dataset.id));
    }

    const editBtn = container.querySelector(".marker-edit-btn");
    if (editBtn) {
      editBtn.onclick = () => {
        e.popup.close();
        openMarkerEditModal(Number(editBtn.dataset.id));
      };
    }

    const geoEditBtn = container.querySelector(".marker-geo-edit-btn");
    if (geoEditBtn) {
      geoEditBtn.onclick = () => {
        e.popup.close();
        startGeometryEdit(Number(geoEditBtn.dataset.id));
      };
    }

    const routeBtn = container.querySelector(".marker-route");
    if (routeBtn) {
      routeBtn.onclick = () => {
        const x = Number(routeBtn.dataset.x);
        const y = Number(routeBtn.dataset.y);
        navRouteTo(x, y);
        e.popup.close();
      };
    }

    const poiEditBtn = container.querySelector(".poi-edit-btn");
    if (poiEditBtn) {
      poiEditBtn.onclick = () => {
        e.popup.close();
        openPoiEditModal(Number(poiEditBtn.dataset.id));
      };
    }

    const poiDeleteBtn = container.querySelector(".poi-delete-btn");
    if (poiDeleteBtn) {
      poiDeleteBtn.onclick = () => deletePoi(Number(poiDeleteBtn.dataset.id));
    }

    const popupImg = container.querySelector(".marker-popup-img");
    if (popupImg) {
      popupImg.onclick = () => {
        const full = popupImg.getAttribute("data-full") || popupImg.getAttribute("src");
        openMarkerImageModal(full);
      };
    }
  });

  setTileLayer("satellite");
  state.map.fitBounds(activeMapBounds(config));

  const center = mapCenterLatLng(config);
  state.map.setView(center, isScumConfig(config) ? 3 : 3);
  restoreMapView();
  updateMapCursor();
  initMapDragCursor();
}

function upsertLive(pos) {
  if (!state.filters.players) return;
  const latlng = gameToLatLng(pos.x, pos.y);
  const color = colorForUser(pos.user_id);
  let marker = state.liveMarkers.get(pos.user_id);

  const isMe = state.me && pos.user_id === state.me.user_id;
  const routeBtn = isMe
    ? ""
    : `<div class="marker-popup-actions"><button class="marker-route" data-x="${pos.x}" data-y="${pos.y}">Маршрут</button></div>`;
  const popup = `<b>${markerEscapeHtml(pos.nickname)}</b><br>Live: ${Math.round(pos.x)} / ${Math.round(pos.y)}${routeBtn}`;

  const avatarSrc = resolveUserAvatarUrl(pos.user_id, pos.avatar_url);
  const iconHtml = `
    <div class="live-player-pin">
      <div class="live-player-avatar-wrap" style="border-color:${color}">
        <img class="live-player-avatar" src="${markerEscapeHtml(avatarSrc)}" alt="" onerror="this.onerror=null;this.src='${(window.ProfileUi?.DEFAULT_AVATAR_URL || '/img/default-avatar.svg?v=2').replace(/'/g, '')}'">
      </div>
      <div class="live-player-name">${markerEscapeHtml(pos.nickname)}</div>
    </div>
  `;

  const icon = L.divIcon({
    className: "live-player-icon",
    html: iconHtml,
    iconSize: [200, 24],
    iconAnchor: [12, 12],
  });

  if (marker && typeof marker.setIcon !== "function") {
    state.map.removeLayer(marker);
    marker = null;
  }

  if (marker) {
    marker.setLatLng(latlng);
    marker.setIcon(icon);
    marker.setPopupContent(popup);
    marker._playerMeta = pos;
  } else {
    marker = L.marker(latlng, { icon }).addTo(state.map);
    marker.bindPopup(popup);
    marker._playerMeta = pos;
    state.liveMarkers.set(pos.user_id, marker);
  }

  // Для текущего пользователя двигаем карту как навигатор.
  if (state.me && pos.user_id === state.me.user_id && state.map) {
    state.map.panTo(latlng, { animate: true, duration: 0.6 });
    trackPlayerOnRoute(pos.x, pos.y);
  }
  updatePlayersList();
}

function markerEscapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function resolveUserAvatarUrl(userId, avatarUrl) {
  if (avatarUrl !== undefined && avatarUrl !== null) {
    state.userAvatars.set(userId, avatarUrl);
  }
  const cached = state.userAvatars.get(userId);
  const url = avatarUrl !== undefined && avatarUrl !== null ? avatarUrl : cached;
  return window.ProfileUi?.resolveAvatarUrl?.(url) || url || "/img/default-avatar.svg?v=2";
}

function userAvatarHtml(userId, avatarUrl, size = 22, className = "sidebar-avatar") {
  const src = resolveUserAvatarUrl(userId, avatarUrl);
  const fallback = (window.ProfileUi?.DEFAULT_AVATAR_URL || "/img/default-avatar.svg?v=2").replace(/"/g, "&quot;");
  return `<img class="${className}" src="${markerEscapeHtml(src)}" alt="" width="${size}" height="${size}" loading="lazy" onerror="this.onerror=null;this.src='${fallback}'">`;
}

function refreshUserAvatars(userId) {
  const live = state.liveMarkers.get(userId);
  if (live?._playerMeta) upsertLive(live._playerMeta);
  state.pinMarkers.forEach((layer, markerId) => {
    const meta = layer._markerMeta;
    if (meta?.user_id === userId) upsertPin(meta);
  });
  updatePlayersList();
  updateMarkersList();
}

function collectZonesAtGamePoint(x, y) {
  const out = { radiation: [], psi: [] };
  const data = state.radiationData || {};
  (data.zones || []).forEach((zone) => {
    const dx = Number(x) - Number(zone.x || 0);
    const dy = Number(y) - Number(zone.y || 0);
    const radius = Number(zone.radius || 0);
    if (radius > 0 && dx * dx + dy * dy <= radius * radius) {
      out.radiation.push(zone);
    }
  });
  (data.psi_zones || []).forEach((zone) => {
    const dx = Number(x) - Number(zone.x || 0);
    const dy = Number(y) - Number(zone.y || 0);
    const radius = Number(zone.radius || 0);
    if (radius > 0 && dx * dx + dy * dy <= radius * radius) {
      out.psi.push(zone);
    }
  });
  return out;
}

function zonesInfoHtml(matches, compact = false) {
  const parts = [];
  if (!compact) parts.push("<b>Зоны в этой точке</b>");
  if (matches.radiation.length) {
    const radLines = matches.radiation.map((z) => {
      const dose = String(z.label || "").trim() || "уровень не указан";
      return `☢ ${markerEscapeHtml(dose)} · R:${Math.round(Number(z.radius || 0))}`;
    });
    parts.push(radLines.join("<br>"));
  }
  if (matches.psi.length) {
    const psiLines = matches.psi.map((z) => `🧠 Пси-зона · R:${Math.round(Number(z.radius || 0))}`);
    parts.push(psiLines.join("<br>"));
  }
  return parts.join("<br>");
}

function hideZoneHoverTooltip() {
  if (!state.map || !state.zoneHoverTooltip) return;
  state.map.removeLayer(state.zoneHoverTooltip);
  state.zoneHoverTooltip = null;
}

function setMouseCoordsText(text) {
  const el = document.getElementById("mouse-coords-value");
  if (el) el.textContent = text;
}

function updateMouseCoordsDisplay(latlng) {
  if (!latlng) {
    state.lastMouseGameCoords = null;
    setMouseCoordsText("— / —");
    return;
  }
  const game = latLngToGame(latlng);
  state.lastMouseGameCoords = { x: game.x, y: game.y };
  setMouseCoordsText(`${Math.round(game.x)} / ${Math.round(game.y)}`);
}

function updateZoneHoverTooltip(latlng) {
  if (!state.map || !latlng) return;
  const game = latLngToGame(latlng);
  const matches = collectZonesAtGamePoint(game.x, game.y);
  if (!matches.radiation.length && !matches.psi.length) {
    hideZoneHoverTooltip();
    return;
  }
  const html = zonesInfoHtml(matches, true);
  if (!state.zoneHoverTooltip) {
    state.zoneHoverTooltip = L.tooltip({
      permanent: false,
      direction: "top",
      offset: [0, -8],
      opacity: 0.95,
      className: "zone-hover-tooltip",
      interactive: false,
    });
    state.zoneHoverTooltip.setLatLng(latlng).setContent(html).addTo(state.map);
  } else {
    state.zoneHoverTooltip.setLatLng(latlng).setContent(html);
  }
}

function ensurePsiStripePattern() {
  if (!state.map) return null;
  const overlayPane = state.map.getPane("overlayPane");
  const svg = overlayPane?.querySelector("svg");
  if (!svg) return null;
  const NS = "http://www.w3.org/2000/svg";
  let defs = svg.querySelector("defs[data-psi-pattern='1']");
  if (!defs) {
    defs = document.createElementNS(NS, "defs");
    defs.setAttribute("data-psi-pattern", "1");
    svg.insertBefore(defs, svg.firstChild);
  }
  let pattern = defs.querySelector("#psi-stripes-pattern");
  if (!pattern) {
    pattern = document.createElementNS(NS, "pattern");
    pattern.setAttribute("id", "psi-stripes-pattern");
    pattern.setAttribute("patternUnits", "userSpaceOnUse");
    pattern.setAttribute("width", "10");
    pattern.setAttribute("height", "10");
    pattern.setAttribute("patternTransform", "rotate(45)");
    const bg = document.createElementNS(NS, "rect");
    bg.setAttribute("width", "10");
    bg.setAttribute("height", "10");
    bg.setAttribute("fill", "rgba(107,16,46,0.14)");
    const stripe = document.createElementNS(NS, "line");
    stripe.setAttribute("x1", "0");
    stripe.setAttribute("y1", "0");
    stripe.setAttribute("x2", "0");
    stripe.setAttribute("y2", "10");
    stripe.setAttribute("stroke", "rgba(107,16,46,0.7)");
    stripe.setAttribute("stroke-width", "4");
    pattern.appendChild(bg);
    pattern.appendChild(stripe);
    defs.appendChild(pattern);
  }
  return "psi-stripes-pattern";
}

function applyPsiStripedFill(circle) {
  const patternId = ensurePsiStripePattern();
  if (!patternId || !circle?._path) return;
  circle._path.setAttribute("fill", `url(#${patternId})`);
  circle._path.setAttribute("fill-opacity", "0.7");
}

function buildMarkerIconDefs() {
  const defs = {
    marker: { emoji: "📌", label: "Метка", glyph: "📌" },
    chest: { emoji: "📦", label: "Сундук", glyph: "📦" },
    loot: { emoji: "🔫", label: "Лут", glyph: "🔫" },
    death: { emoji: "💀", label: "Смерть", glyph: "💀" },
    point: { emoji: "🔵", label: "Точка", glyph: "🔵" },
    camp: { emoji: "🏕", label: "Лагерь", glyph: "🏕" },
    danger: { emoji: "⚠️", label: "Опасность", glyph: "⚠️" },
    screenshot: { emoji: "❓", label: "Снимок", glyph: "❓" },
  };
  if (typeof POI_ICONS === "object" && POI_ICONS) {
    Object.entries(POI_ICONS).forEach(([key, icon]) => {
      defs[key] = {
        emoji: icon?.glyph || "📌",
        glyph: icon?.glyph || "📌",
        label: icon?.label || key,
      };
    });
  }
  return defs;
}

const MARKER_ICON_DEFS = buildMarkerIconDefs();
let markerIconPickerApi = null;

function renderMarkerIconGrid(selectedType = "marker") {
  const container = document.getElementById("marker-icon-grid");
  if (!container) return null;

  markerIconPickerApi = setupSearchableIconPicker(container, {
    entries: Object.entries(MARKER_ICON_DEFS),
    selectedKey: selectedType,
    onSelect: () => {},
    gridClass: "marker-icon-grid icon-picker-grid",
    renderOption: (type, def, active) => `
      <button type="button" class="marker-icon-btn${active ? " selected" : ""}" data-type="${type}" title="${markerEscapeHtml(def.label)}">
        <span class="icon-emoji">${markerEscapeHtml(def.glyph || def.emoji || "📌")}</span>
        <span>${markerEscapeHtml(def.label)}</span>
      </button>
    `,
  });
  return markerIconPickerApi;
}

function markerTypeLabel(type) {
  return (MARKER_ICON_DEFS[type] || MARKER_ICON_DEFS.marker).label;
}

function markerTypeToPoiIcon(markerType) {
  const key = String(markerType || "marker").trim().toLowerCase();
  if (typeof POI_ICONS === "object" && POI_ICONS && POI_ICONS[key]) {
    return normalizePoiIcon(key);
  }
  return "star";
}

function markerIconHtml(type, color) {
  const def = MARKER_ICON_DEFS[type] || MARKER_ICON_DEFS.marker;
  if (type === "marker") {
    // classic crosshair for default marker
    return `
      <div style="width:24px;height:24px;position:relative;display:flex;align-items:center;justify-content:center;filter:drop-shadow(0 0 3px rgba(0,0,0,0.95));">
        <div style="position:absolute;width:24px;height:3px;background:#ff2e44;border:0.75px solid #fff;"></div>
        <div style="position:absolute;width:3px;height:24px;background:#ff2e44;border:0.75px solid #fff;"></div>
        <div style="width:10px;height:10px;border-radius:50%;border:2.5px solid #ff2e44;background:#fff;z-index:2;box-shadow:0 0 2px #000;"></div>
      </div>
    `;
  }
  return `<div style="font-size:22px;line-height:1;filter:drop-shadow(0 0 3px rgba(0,0,0,0.9));">${def.glyph || def.emoji || "📌"}</div>`;
}

function drawHint(text) {
  const el = document.getElementById("draw-hint");
  if (el) el.textContent = text;
}

function updateMapCursor() {
  if (!state.map) return;
  const el = state.map.getContainer();
  el.classList.toggle("map-cursor-crosshair", !!(state.navActive || state.draw.mode));
  if (!el.classList.contains("leaflet-dragging")) {
    el.style.cursor = "";
  }
}

function initMapDragCursor() {
  if (!state.map) return;
  const el = state.map.getContainer();
  state.map.on("dragstart", () => {
    el.style.cursor = "grabbing";
  });
  state.map.on("dragend", () => {
    updateMapCursor();
  });
}

function closeMapContextMenu() {
  const menu = document.getElementById("map-context-menu");
  if (!menu) return;
  menu.classList.add("hidden");
  menu.setAttribute("aria-hidden", "true");
}

function showMapContextMenu(clientX, clientY, gameCoords) {
  const menu = document.getElementById("map-context-menu");
  if (!menu) return;

  document.getElementById("ctx-shapes-section")?.classList.toggle("hidden", !state.me);

  const coordsEl = document.getElementById("ctx-coords-display");
  if (coordsEl && gameCoords) {
    coordsEl.textContent = formatCoordLookupValue(gameCoords.x, gameCoords.y);
  }
  state.contextMenuCoords = gameCoords;

  menu.classList.remove("hidden");
  menu.setAttribute("aria-hidden", "false");
  menu.style.visibility = "hidden";
  menu.style.left = "0px";
  menu.style.top = "0px";

  const pad = 8;
  const mw = menu.offsetWidth;
  const mh = menu.offsetHeight;
  let left = clientX;
  let top = clientY;
  if (left + mw > window.innerWidth - pad) left = Math.max(pad, window.innerWidth - mw - pad);
  if (top + mh > window.innerHeight - pad) top = Math.max(pad, window.innerHeight - mh - pad);
  if (left < pad) left = pad;
  if (top < pad) top = pad;

  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  menu.style.visibility = "";
}

function initMapContextMenu() {
  const menu = document.getElementById("map-context-menu");
  if (!menu) return;

  document.getElementById("ctx-copy-coords-btn")?.addEventListener("click", async () => {
    const c = state.contextMenuCoords;
    if (!c) return;
    const text = formatCoordLookupValue(c.x, c.y);
    try {
      await navigator.clipboard.writeText(text);
      const btn = document.getElementById("ctx-copy-coords-btn");
      if (btn) {
        const orig = btn.textContent;
        btn.textContent = "✓ Скопировано";
        setTimeout(() => { btn.textContent = orig; }, 1400);
      }
    } catch {
      alert("Не удалось скопировать координаты");
    }
    closeMapContextMenu();
  });

  document.addEventListener("mousedown", (e) => {
    if (menu.classList.contains("hidden")) return;
    if (menu.contains(e.target)) return;
    closeMapContextMenu();
  });
}

function openMarkerImageModal(src) {
  const modal = document.getElementById("marker-image-modal");
  const img = document.getElementById("marker-image-full");
  if (!modal || !img || !src) return;
  img.src = src;
  modal.classList.remove("hidden");
}

function closeMarkerImageModal() {
  const modal = document.getElementById("marker-image-modal");
  const img = document.getElementById("marker-image-full");
  if (!modal || !img) return;
  img.src = "";
  modal.classList.add("hidden");
}

function normalizeHexColor(value, fallback) {
  const v = String(value || "").trim();
  return /^#[0-9a-fA-F]{6}$/.test(v) ? v.toLowerCase() : fallback;
}

function drawCircleRadius() {
  const el = document.getElementById("draw-circle-radius");
  const radius = Number(el?.value || 300);
  return Number.isFinite(radius) ? Math.max(10, radius) : 300;
}

function drawCircleStrokeColor() {
  return normalizeHexColor(document.getElementById("draw-circle-stroke")?.value, "#ffffff");
}

function drawCircleFillColor() {
  return normalizeHexColor(document.getElementById("draw-circle-fill")?.value, "#ffffff");
}

function drawLineStrokeColor() {
  return normalizeHexColor(document.getElementById("draw-line-stroke")?.value, "#00e5ff");
}

function toggleDrawModeSettings(mode) {
  document.getElementById("draw-circle-settings")?.classList.toggle("hidden", mode !== "circle");
  document.getElementById("draw-line-settings")?.classList.toggle("hidden", mode !== "line");
}

function clearDrawTemp() {
  if (state.draw.tempLayer && state.map) {
    state.map.removeLayer(state.draw.tempLayer);
  }
  state.draw.tempLayer = null;
}

function setDrawMode(mode) {
  if (state.geoEdit.markerId !== null) {
    stopGeometryEdit({ restoreMarker: true, silent: true });
  }
  state.draw.mode = mode;
  state.draw.linePoints = [];
  clearDrawTemp();
  toggleDrawModeSettings(mode);
  document.querySelectorAll(".draw-tool-row button").forEach((btn) => btn.classList.remove("active"));
  if (mode === "point") document.getElementById("draw-point-btn")?.classList.add("active");
  if (mode === "circle") document.getElementById("draw-circle-btn")?.classList.add("active");
  if (mode === "line") document.getElementById("draw-line-btn")?.classList.add("active");
  document.getElementById("draw-cancel-btn")?.classList.toggle("hidden", !mode);
  document.getElementById("draw-finish-btn")?.classList.toggle("hidden", mode !== "line");
  if (!mode) drawHint("ПКМ по карте — инструменты и координаты");
  else if (mode === "point") drawHint("Кликните по карте для установки метки");
  else if (mode === "circle") drawHint("Кликните центр круга. Радиус и цвет — в меню (ПКМ).");
  else drawHint("Кликайте точки линии, затем нажмите 'Сохранить линию'");
  updateMapCursor();
}

async function createUserShape(payload) {
  const created = await api("/api/markers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  upsertPin(created);
  return created;
}

async function handleDrawMapClick(x, y) {
  const mode = state.draw.mode;
  if (!mode) return;
  try {
    if (mode === "point") {
      await createUserShape({
        x,
        y,
        type: "marker",
        geometry_kind: "point",
        title: null,
      });
      setDrawMode(null);
      drawHint("Метка добавлена. ПКМ — ещё инструменты");
      return;
    }
    if (mode === "circle") {
      const radius = drawCircleRadius();
      await createUserShape({
        x,
        y,
        type: "danger",
        geometry_kind: "circle",
        radius,
        stroke_color: drawCircleStrokeColor(),
        fill_color: drawCircleFillColor(),
      });
      setDrawMode(null);
      drawHint("Круг добавлен");
      return;
    }
    if (mode === "line") {
      state.draw.linePoints.push([x, y]);
      clearDrawTemp();
      if (state.draw.linePoints.length >= 2) {
        state.draw.tempLayer = L.polyline(
          state.draw.linePoints.map(([px, py]) => gameToLatLng(px, py)),
          { color: drawLineStrokeColor(), weight: 3, dashArray: "6,4" },
        ).addTo(state.map);
      } else {
        state.draw.tempLayer = L.marker(gameToLatLng(x, y)).addTo(state.map);
      }
      drawHint(`Точек линии: ${state.draw.linePoints.length}`);
    }
  } catch (e) {
    alert(e.message || "Не удалось создать фигуру");
    setDrawMode(null);
  }
}

async function finishLineDrawing() {
  if (state.draw.mode !== "line") return;
  if (state.draw.linePoints.length < 2) {
    alert("Для линии нужно минимум 2 точки.");
    return;
  }
  try {
    await createUserShape({
      points: state.draw.linePoints,
      type: "point",
      geometry_kind: "line",
      stroke_color: drawLineStrokeColor(),
    });
    setDrawMode(null);
    drawHint("Линия добавлена");
  } catch (e) {
    alert(e.message || "Не удалось сохранить линию");
  }
}

function setGeometryEditButtonsVisible(visible) {
  document.getElementById("geo-edit-save-btn")?.classList.toggle("hidden", !visible);
  document.getElementById("geo-edit-cancel-btn")?.classList.toggle("hidden", !visible);
}

function editHandleIcon(text = "●", color = "#3d9ee5") {
  return L.divIcon({
    className: "geo-edit-handle",
    html: `<div style="width:18px;height:18px;border-radius:50%;background:${color};border:2px solid #fff;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:700;box-shadow:0 0 4px rgba(0,0,0,0.8);">${text}</div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function clearGeometryEditorLayers() {
  if (!state.map) return;
  if (state.geoEdit.previewLayer) {
    state.map.removeLayer(state.geoEdit.previewLayer);
    state.geoEdit.previewLayer = null;
  }
  state.geoEdit.handles.forEach((h) => state.map.removeLayer(h));
  state.geoEdit.handles = [];
}

function stopGeometryEdit({ restoreMarker = false, silent = false } = {}) {
  const markerId = state.geoEdit.markerId;
  const layer = markerId != null ? state.pinMarkers.get(markerId) : null;
  const markerMeta = layer?._markerMeta || null;

  clearGeometryEditorLayers();
  setGeometryEditButtonsVisible(false);

  state.geoEdit.markerId = null;
  state.geoEdit.kind = null;
  state.geoEdit.center = null;
  state.geoEdit.radius = null;
  state.geoEdit.points = [];

  if (restoreMarker && markerMeta) {
    upsertPin(markerMeta);
  }
  if (!silent) {
    drawHint("ПКМ по карте — инструменты и координаты");
  }
  updateMapCursor();
}

function startGeometryEdit(markerId) {
  const layer = state.pinMarkers.get(markerId);
  const m = layer?._markerMeta;
  if (!m) return;
  const kind = m.geometry_kind || "point";
  if (kind !== "circle" && kind !== "line") return;

  stopGeometryEdit({ restoreMarker: true, silent: true });
  setDrawMode(null);

  const target = state.pinMarkers.get(markerId);
  if (target && state.map?.hasLayer(target)) {
    state.map.removeLayer(target);
  }

  state.geoEdit.markerId = markerId;
  state.geoEdit.kind = kind;
  state.geoEdit.center = { x: Number(m.x || 0), y: Number(m.y || 0) };
  state.geoEdit.radius = Math.max(10, Number(m.radius || 300));
  state.geoEdit.points = Array.isArray(m.points) ? m.points.map(([x, y]) => [Number(x), Number(y)]) : [];

  setGeometryEditButtonsVisible(true);

  if (kind === "circle") {
    const circle = L.circle(gameToLatLng(state.geoEdit.center.x, state.geoEdit.center.y), {
      radius: gameRadiusToLeaflet(state.geoEdit.radius),
      color: m.stroke_color || "#ffffff",
      fillColor: m.fill_color || "#ffffff",
      fillOpacity: 0.22,
      weight: 2,
    }).addTo(state.map);
    state.geoEdit.previewLayer = circle;

    const centerHandle = L.marker(gameToLatLng(state.geoEdit.center.x, state.geoEdit.center.y), {
      icon: editHandleIcon("C", "#3d9ee5"),
      draggable: true,
    }).addTo(state.map);
    const edgeHandle = L.marker(gameToLatLng(state.geoEdit.center.x + state.geoEdit.radius, state.geoEdit.center.y), {
      icon: editHandleIcon("R", "#e67e22"),
      draggable: true,
    }).addTo(state.map);

    const syncCircleVisuals = () => {
      circle.setLatLng(gameToLatLng(state.geoEdit.center.x, state.geoEdit.center.y));
      circle.setRadius(gameRadiusToLeaflet(state.geoEdit.radius));
      centerHandle.setLatLng(gameToLatLng(state.geoEdit.center.x, state.geoEdit.center.y));
      edgeHandle.setLatLng(gameToLatLng(state.geoEdit.center.x + state.geoEdit.radius, state.geoEdit.center.y));
      drawHint(`Редактирование круга: R=${Math.round(state.geoEdit.radius)}. Перетащите C и R, затем сохраните.`);
    };

    centerHandle.on("drag", () => {
      const g = latLngToGame(centerHandle.getLatLng());
      state.geoEdit.center = { x: g.x, y: g.y };
      syncCircleVisuals();
    });
    edgeHandle.on("drag", () => {
      const g = latLngToGame(edgeHandle.getLatLng());
      const dx = g.x - state.geoEdit.center.x;
      const dy = g.y - state.geoEdit.center.y;
      state.geoEdit.radius = Math.max(10, Math.sqrt(dx * dx + dy * dy));
      syncCircleVisuals();
    });
    state.geoEdit.handles = [centerHandle, edgeHandle];
    syncCircleVisuals();
    updateMapCursor();
    return;
  }

  // line editor
  if (state.geoEdit.points.length < 2) {
    stopGeometryEdit({ restoreMarker: true });
    return;
  }
  const line = L.polyline(
    state.geoEdit.points.map(([x, y]) => gameToLatLng(x, y)),
    {
      color: m.stroke_color || "#00e5ff",
      weight: 3.5,
      opacity: 0.95,
    },
  ).addTo(state.map);
  state.geoEdit.previewLayer = line;

  state.geoEdit.points.forEach((pt, idx) => {
    const handle = L.marker(gameToLatLng(pt[0], pt[1]), {
      icon: editHandleIcon(String(idx + 1), "#3d9ee5"),
      draggable: true,
    }).addTo(state.map);
    handle.on("drag", () => {
      const g = latLngToGame(handle.getLatLng());
      state.geoEdit.points[idx] = [g.x, g.y];
      line.setLatLngs(state.geoEdit.points.map(([x, y]) => gameToLatLng(x, y)));
      drawHint(`Редактирование линии: ${state.geoEdit.points.length} точек. Перетащите маркеры и сохраните.`);
    });
    state.geoEdit.handles.push(handle);
  });
  drawHint(`Редактирование линии: ${state.geoEdit.points.length} точек. Перетащите маркеры и сохраните.`);
  updateMapCursor();
}

async function saveGeometryEdit() {
  const markerId = state.geoEdit.markerId;
  if (markerId == null) return;
  const sourceMeta = state.pinMarkers.get(markerId)?._markerMeta || null;
  const kind = state.geoEdit.kind;
  try {
    const payload = kind === "circle"
      ? {
          geometry_kind: "circle",
          x: state.geoEdit.center.x,
          y: state.geoEdit.center.y,
          radius: Math.max(10, Number(state.geoEdit.radius || 10)),
        }
      : {
          geometry_kind: "line",
          points: state.geoEdit.points,
        };
    const patched = await api(`/api/markers/${markerId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    stopGeometryEdit({ restoreMarker: false, silent: true });
    upsertPin(sourceMeta ? { ...sourceMeta, ...patched } : patched);
    drawHint("Геометрия сохранена");
  } catch (e) {
    alert("Ошибка сохранения геометрии: " + (e.message || e));
  }
}

function markerCenterLatLng(layer) {
  if (typeof layer.getLatLng === "function") return layer.getLatLng();
  if (typeof layer.getBounds === "function") return layer.getBounds().getCenter();
  return null;
}

function rememberCommandZoomAnchor(latlng = null) {
  if (!state.map) return;
  state.commandZoomAnchor = latlng || state.map.getCenter();
}

function applyCommandZoom(action) {
  if (!state.map) return;
  const minZoom = state.map.getMinZoom();
  const maxZoom = state.map.getMaxZoom();
  const currentZoom = state.map.getZoom();
  const anchor = state.commandZoomAnchor || state.map.getCenter();

  const zoomToAnchor = (targetZoom) => {
    state.commandZoomApplying = true;
    state.map.once("moveend", () => {
      // Keep the flag true for the current moveend dispatch cycle
      // so global move handlers won't overwrite the saved anchor.
      setTimeout(() => {
        state.commandZoomApplying = false;
      }, 0);
    });
    state.map.setView(anchor, targetZoom, { animate: true });
  };

  if (action === "zoom_out") {
    // Save viewport focus only once; do not overwrite it on repeated zoom-out,
    // otherwise at min zoom it gets replaced by map center.
    if (!state.commandZoomAnchor) {
      rememberCommandZoomAnchor(state.map.getCenter());
    }
    const targetZoom = Math.max(minZoom, currentZoom - 1);
    zoomToAnchor(targetZoom);
    return;
  }
  if (action === "zoom_in") {
    const targetZoom = Math.min(currentZoom + 1, maxZoom);
    zoomToAnchor(targetZoom);
    return;
  }
  if (action === "zoom_reset") {
    state.commandZoomAnchor = null;
    state.map.setZoom(state.map.getMinZoom() || 3);
  }
}

function canManageStashes() {
  return !!state.me?.can_manage_stashes;
}

function canManageMapStaff() {
  return canManageStashes();
}

function isStashMarker(meta) {
  return isMapScopedCategory(meta?.marker_category);
}

function isMapScopedCategory(category) {
  const value = category || "group";
  return value === "stash" || value === "mutants" || value === "hunting";
}

const MAP_SCOPED_CATEGORY_LABELS = {
  stash: "Тайник",
  mutants: "Мутанты",
  hunting: "Охота",
};

function markerVisibleOnMap(category) {
  const value = category || "group";
  if (value === "stash") return !state.filters.stashes;
  if (value === "mutants") return !!state.filters.mutants;
  if (value === "hunting") return !!state.filters.hunting;
  return !!state.filters.markers;
}

function canEditMarker(meta) {
  if (isStashMarker(meta)) return canManageStashes();
  return true;
}

function canDeleteMarker(meta) {
  if (isStashMarker(meta)) return canManageStashes();
  if (canManageMapStaff()) return true;
  return !!(state.me && meta?.user_id === state.me.user_id);
}

function syncStaffCategoryControls(kind = "point", isMapScoped = false) {
  const can = canManageMapStaff();
  const allowPoi = can && kind === "point" && !isMapScoped;
  document.querySelectorAll(
    '#marker-edit-category option[value="stash"], #marker-edit-category option[value="mutants"], #marker-edit-category option[value="hunting"]',
  ).forEach((opt) => {
    opt.hidden = !can;
    opt.disabled = !can;
  });
  document.querySelectorAll('#marker-edit-category option[value="poi"]').forEach((opt) => {
    opt.hidden = !allowPoi;
    opt.disabled = !allowPoi;
  });
}

function updateMarkerCategoryHint() {
  const hint = document.getElementById("marker-edit-category-hint");
  const categoryInput = document.getElementById("marker-edit-category");
  if (!hint || !categoryInput) return;
  const value = categoryInput.value || "group";
  if (value === "stash") {
    hint.textContent = "Тайник виден всем группам на карте. Автор отображается как «Сервер».";
    hint.classList.remove("hidden");
    return;
  }
  if (value === "mutants") {
    hint.textContent = "Серверная категория «Мутанты»: видна всем группам на карте. Автор — «Сервер».";
    hint.classList.remove("hidden");
    return;
  }
  if (value === "hunting") {
    hint.textContent = "Серверная категория «Охота»: видна всем группам на карте. Автор — «Сервер».";
    hint.classList.remove("hidden");
    return;
  }
  if (value === "poi") {
    hint.textContent = "Метка станет серверной: исчезнет из группы и появится в «Метки сервера» для всех игроков.";
    hint.classList.remove("hidden");
    return;
  }
  hint.textContent = "";
  hint.classList.add("hidden");
}

function upsertPin(m) {
  const color = colorForUser(m.user_id);
  if (m.avatar_url !== undefined) {
    state.userAvatars.set(m.user_id, m.avatar_url);
  }
  let layer = state.pinMarkers.get(m.id);

  const inGroup = canEditMarker(m);
  const kind = m.geometry_kind || "point";
  const markerCategory = m.marker_category || "group";
  const canGeoEdit = inGroup && (kind === "circle" || kind === "line");
  const title = m.title || markerTypeLabel(m.type || "marker");
  const roundedX = Math.round(m.x || 0);
  const roundedY = Math.round(m.y || 0);
  const imgHtml = m.image_url
    ? `<img class="marker-popup-img" src="${m.image_url}" data-full="${m.image_url}" alt="Скриншот">`
    : "";
  const descHtml = m.description
    ? `<div style="margin:4px 0;font-size:0.88rem;color:#333;white-space:pre-wrap;max-width:220px;">${m.description.replace(/</g, "&lt;")}</div>`
    : "";
  const shapeInfo = kind === "circle"
    ? `<div style="font-size:0.78rem;color:#555;margin-top:3px;">Пользовательский круг · R: ${Math.round(m.radius || 0)}</div>`
    : (kind === "line"
      ? `<div style="font-size:0.78rem;color:#555;margin-top:3px;">Точек: ${Array.isArray(m.points) ? m.points.length : 0}</div>`
      : "");

  const isMapScoped = isMapScopedCategory(markerCategory);
  const categoryLabel = MAP_SCOPED_CATEGORY_LABELS[markerCategory] || null;
  const popupHeadHtml = isMapScoped
    ? `<b>${markerEscapeHtml(title)}</b>`
    : `<div class="marker-popup-head">
        <span class="marker-popup-avatar-wrap" style="--user-color:${color}">
          ${userAvatarHtml(m.user_id, m.avatar_url, 36, "marker-popup-avatar")}
        </span>
        <div class="marker-popup-head-text">
          <b>${markerEscapeHtml(title)}</b>
          <span class="marker-popup-author">${markerEscapeHtml(m.nickname)} · ${roundedX} / ${roundedY}</span>
        </div>
      </div>`;

  const popupHtml = `
    ${popupHeadHtml}
    ${isMapScoped ? `<span style="color:#555;font-size:0.82rem;display:block;margin-top:2px">${markerEscapeHtml(m.nickname)} · ${roundedX} / ${roundedY}</span>` : ""}
    ${categoryLabel ? `<div style="font-size:0.78rem;color:#6b102e;margin-top:3px;">Категория: ${categoryLabel}</div>` : ""}
    ${shapeInfo}
    ${descHtml}
    ${imgHtml}
    <div class="marker-popup-actions">
      <button class="marker-route" data-x="${m.x}" data-y="${m.y}">Маршрут</button>
      ${inGroup ? `<button class="marker-edit-btn" data-id="${m.id}">✏️ Изменить</button>` : ""}
      ${canGeoEdit ? `<button class="marker-geo-edit-btn" data-id="${m.id}">🧩 Геометрия</button>` : ""}
      ${canDeleteMarker(m) ? `<button class="marker-delete" data-id="${m.id}">Удалить</button>` : ""}
    </div>
  `;

  const prevLayer = layer;
  if (prevLayer && state.map) state.map.removeLayer(prevLayer);

  if (kind === "circle") {
    const center = gameToLatLng(m.x, m.y);
    layer = L.circle(center, {
      radius: gameRadiusToLeaflet(m.radius || 300),
      color: m.stroke_color || m.fill_color || "#ffffff",
      fillColor: m.fill_color || "#ffffff",
      fillOpacity: 0.12,
      weight: 3,
      dashArray: "8,6",
      pane: "userShapesPane",
    }).addTo(state.map);
    layer.bindPopup(popupHtml);
  } else if (kind === "line" && Array.isArray(m.points) && m.points.length >= 2) {
    layer = L.polyline(
      m.points.map(([x, y]) => gameToLatLng(x, y)),
      {
        color: m.stroke_color || "#00e5ff",
        weight: 3,
        opacity: 0.95,
        pane: "userShapesPane",
      },
    ).addTo(state.map);
    layer.bindPopup(popupHtml);
  } else {
    const latlng = gameToLatLng(m.x, m.y);
    const iconHtml = markerIconHtml(m.type || "marker", color);
    const isEmoji = m.type && m.type !== "marker";
    const icon = L.divIcon({
      className: `pin-icon-${m.type || "marker"}`,
      html: iconHtml,
      iconSize: isEmoji ? [28, 28] : [24, 24],
      iconAnchor: isEmoji ? [14, 14] : [12, 12],
    });
    layer = L.marker(latlng, { icon }).addTo(state.map);
    layer.bindPopup(popupHtml);
  }

  layer._markerMeta = m;
  state.pinMarkers.set(m.id, layer);

  const visibleOnMap = markerVisibleOnMap(markerCategory);
  if (visibleOnMap) {
    if (state.map && !state.map.hasLayer(layer)) layer.addTo(state.map);
  } else if (state.map && state.map.hasLayer(layer)) {
    state.map.removeLayer(layer);
  }

  const centerLatLng = markerCenterLatLng(layer);
  if (state.me && m.user_id === state.me.user_id && state.map && centerLatLng) {
    state.map.panTo(centerLatLng, { animate: true, duration: 0.6 });
  }
  updateMarkersList();
}

function upsertPoi(p) {
  if (!state.filters.poi) return;
  const latlng = gameToLatLng(p.x, p.y);
  let marker = state.poiMarkers.get(p.id);
  const popup = poiPopupHtml(p, { canManage: canManageMapStaff() });
  const icon = L.divIcon({
    className: "poi-map-pin",
    html: poiLabelHtml(p.icon || "star", p.title),
    ...poiMapIconOptions(),
  });

  if (marker) {
    marker.setLatLng(latlng);
    marker.setIcon(icon);
    marker.setPopupContent(popup);
    marker._poiMeta = p;
  } else {
    marker = L.marker(latlng, { icon }).addTo(state.map);
    marker.bindPopup(popup);
    marker._poiMeta = p;
    state.poiMarkers.set(p.id, marker);
  }
}

async function reloadPois() {
  try {
    const data = await api("/api/room/state");
    state.poiMarkers.forEach((layer) => {
      if (state.map) state.map.removeLayer(layer);
    });
    state.poiMarkers.clear();
    if (state.filters.poi) data.pois.forEach(upsertPoi);
  } catch {
    /* optional */
  }
}

function removePin(id) {
  if (state.geoEdit.markerId === id || state.geoEdit.markerId === Number(id)) {
    stopGeometryEdit({ restoreMarker: false, silent: true });
  }
  const marker = state.pinMarkers.get(id);
  if (marker) {
    state.map.removeLayer(marker);
    state.pinMarkers.delete(id);
  }
  updateMarkersList();
}

async function deleteMarker(id) {
  try {
    await api(`/api/markers/${id}`, { method: "DELETE" });
    removePin(id);
  } catch (e) {
    alert(e.message);
  }
}

function updatePlayersList() {
  const el = document.getElementById("web-players-list");
  if (!el) return;

  const rows = [];
  state.liveMarkers.forEach((marker) => {
    const pos = marker._playerMeta;
    if (!pos) return;

    const color = colorForUser(pos.user_id);
    const isMe = state.me && pos.user_id === state.me.user_id;
    const nameLabel = isMe ? `${pos.nickname} (Вы)` : pos.nickname;

    rows.push(`
      <div class="sidebar-row" onclick="focusOnPlayer(${pos.user_id})">
        <div class="sidebar-row-left">
          <span class="sidebar-avatar-wrap" style="--user-color: ${color}">
            ${userAvatarHtml(pos.user_id, pos.avatar_url, 22, "sidebar-avatar")}
          </span>
          <span class="sidebar-name" title="${markerEscapeHtml(pos.nickname)}">${markerEscapeHtml(nameLabel)}</span>
        </div>
        <span class="sidebar-info">${Math.round(pos.x)} / ${Math.round(pos.y)}</span>
      </div>
    `);
  });

  el.innerHTML = rows.length
    ? rows.join("")
    : `<div class="list-empty">Никого онлайн</div>`;
}

function updateMarkersList() {
  const groupEl = document.getElementById("web-markers-list");
  const stashEl = document.getElementById("web-stashes-list");
  if (!groupEl || !stashEl) return;

  const groupRows = [];
  const stashRows = [];
  state.pinMarkers.forEach((marker) => {
    const m = marker._markerMeta;
    if (!m) return;

    const showDelete = canDeleteMarker(m);
    const def = MARKER_ICON_DEFS[m.type] || MARKER_ICON_DEFS.marker;
    const shapePrefix = m.geometry_kind === "circle"
      ? "⭕"
      : (m.geometry_kind === "line" ? "📏" : def.emoji);
    const label = m.title ? `${shapePrefix} ${m.title}` : `${shapePrefix} ${def.label}`;
    const extra = m.geometry_kind === "circle"
      ? ` · R:${Math.round(m.radius || 0)}`
      : (m.geometry_kind === "line"
        ? ` · pts:${Array.isArray(m.points) ? m.points.length : 0}`
        : "");
    const subLabel = `${m.nickname}${extra}`;
    const userColor = colorForUser(m.user_id);
    const isStash = (m.marker_category || "group") === "stash";
    const isMapScoped = isMapScopedCategory(m.marker_category);
    const rowIconHtml = isMapScoped
      ? `<span class="sidebar-dot" style="background: ${userColor}"></span>`
      : `<span class="sidebar-avatar-wrap" style="--user-color: ${userColor}">
            ${userAvatarHtml(m.user_id, m.avatar_url, 22, "sidebar-avatar")}
          </span>`;

    const rowHtml = `
      <div class="sidebar-row" onclick="focusOnMarker('${m.id}')">
        <div class="sidebar-row-left">
          ${rowIconHtml}
          <div style="min-width:0">
            <div class="sidebar-name" title="${markerEscapeHtml(label)}" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px">${markerEscapeHtml(label)}</div>
            <div class="sidebar-info">${markerEscapeHtml(subLabel)}</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 4px;">
          <span class="sidebar-info" style="margin-right: 4px;">${Math.round(m.x)}/${Math.round(m.y)}</span>
          ${showDelete ? `<button class="delete-btn-small" onclick="event.stopPropagation(); deleteMarker('${m.id}')" title="Удалить">✕</button>` : ""}
        </div>
      </div>
    `;
    if (isStash) {
      stashRows.push(rowHtml);
    } else {
      groupRows.push(rowHtml);
    }
  });

  groupEl.innerHTML = groupRows.length
    ? groupRows.join("")
    : `<div class="list-empty">Нет меток</div>`;
  const stashCountEl = document.getElementById("stashes-total-count");
  if (stashCountEl) stashCountEl.textContent = String(stashRows.length);
  stashEl.innerHTML = stashRows.length
    ? stashRows.join("")
    : `<div class="list-empty">Нет тайников</div>`;
}

/** Return the sidebar width in pixels (0 if collapsed). */
function getSidebarOffset() {
  const legend = document.getElementById("legend");
  if (!legend || legend.classList.contains("collapsed")) return 0;
  return legend.offsetWidth || 280;
}

/**
 * Set the map view so that `latlng` appears at the visual centre of the
 * area NOT covered by the sidebar.  Without this adjustment Leaflet
 * centres on the full container, which pushes the target behind the
 * right-hand sidebar.
 */
function setViewCentered(latlng, zoom, opts = { animate: true }) {
  // Сайдбар — flex-элемент рядом с картой, Leaflet сам знает реальные размеры.
  // Дополнительная компенсация не нужна.
  state.map.setView(latlng, zoom, opts);
}

function focusOnPlayer(userId) {
  if (!state.map) return;
  const marker = state.liveMarkers.get(userId);
  if (marker) {
    // Открываем попап ПОСЛЕ завершения анимации — иначе autoPan Leaflet
    // сдвигает карту обратно и маркер не остаётся в центре.
    const target = marker.getLatLng();
    rememberCommandZoomAnchor(target);
    state.map.once("moveend", () => marker.openPopup());
    setViewCentered(target, Math.max(state.map.getZoom(), 5));
  }
}

function focusOnMarker(markerId) {
  if (!state.map) return;
  let marker = state.pinMarkers.get(markerId) || state.pinMarkers.get(Number(markerId));
  if (marker) {
    const center = markerCenterLatLng(marker);
    if (!center) return;
    rememberCommandZoomAnchor(center);
    state.map.once("moveend", () => marker.openPopup());
    setViewCentered(center, Math.max(state.map.getZoom(), 5));
  }
}

function clearCoordLookupMarker() {
  if (state.coordLookupMarker && state.map) {
    state.map.removeLayer(state.coordLookupMarker);
    state.coordLookupMarker = null;
  }
  const clearBtn = document.getElementById("coord-lookup-clear-btn");
  if (clearBtn) clearBtn.classList.add("hidden");
}

function parseCoordLookupInputs() {
  const input = document.getElementById("coord-lookup-input");
  const text = String(input?.value || "").trim();
  if (!text) return null;

  const sepMatch = text.match(/^([\d.]+)\s*[/,\-–—]\s*([\d.]+)$/);
  if (sepMatch) return parseCoordPair(sepMatch[1], sepMatch[2]);

  const spaceMatch = text.match(/^([\d.]+)\s+([\d.]+)$/);
  if (spaceMatch) return parseCoordPair(spaceMatch[1], spaceMatch[2]);

  return null;
}

function parseCoordPair(xRaw, yRaw) {
  const x = Number(xRaw);
  const y = Number(yRaw);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { x, y };
}

function formatCoordLookupValue(x, y) {
  return `${Math.round(x)} / ${Math.round(y)}`;
}

function fillCoordLookupFromCursor() {
  if (!state.lastMouseGameCoords) {
    alert("Наведите курсор на карту, чтобы получить координаты");
    return;
  }
  const input = document.getElementById("coord-lookup-input");
  if (input) {
    input.value = formatCoordLookupValue(state.lastMouseGameCoords.x, state.lastMouseGameCoords.y);
  }
}

function showCoordLookup() {
  if (!state.map || !state.config) return;
  const input = document.getElementById("coord-lookup-input");
  const coords = parseCoordLookupInputs();
  if (!coords) {
    alert("Введите координаты в формате: X Y, X / Y, X - Y, X,Y или X-Y");
    return;
  }

  const size = mapSize(state.config);
  if (coords.x < 0 || coords.y < 0 || coords.x > size || coords.y > size) {
    alert(`Координаты должны быть в пределах 0 — ${Math.round(size)}`);
    return;
  }

  if (input) input.value = formatCoordLookupValue(coords.x, coords.y);

  clearCoordLookupMarker();

  const { x, y } = coords;
  const latlng = gameToLatLng(x, y);
  const label = `${Math.round(x)} / ${Math.round(y)}`;
  const popup = `<b>${label}</b><div class="marker-popup-actions"><button class="marker-route" data-x="${x}" data-y="${y}">Маршрут</button></div>`;

  state.coordLookupMarker = L.marker(latlng, {
    icon: L.divIcon({
      className: "coord-lookup-pin",
      html: '<div class="coord-lookup-pin-inner">📍</div>',
      iconSize: [28, 28],
      iconAnchor: [14, 28],
    }),
    zIndexOffset: 2500,
  }).addTo(state.map);
  state.coordLookupMarker.bindPopup(popup);

  rememberCommandZoomAnchor(latlng);
  state.map.once("moveend", () => state.coordLookupMarker?.openPopup());
  setViewCentered(latlng, Math.max(state.map.getZoom(), 5));

  const clearBtn = document.getElementById("coord-lookup-clear-btn");
  if (clearBtn) clearBtn.classList.remove("hidden");
}

function focusMe() {
  if (!state.map || !state.me) return;
  const marker = state.liveMarkers.get(state.me.user_id);
  if (marker) {
    const target = marker.getLatLng();
    rememberCommandZoomAnchor(target);
    setViewCentered(target, Math.max(state.map.getZoom(), 5));
    return;
  }

  let fallbackLatLng = null;
  state.pinMarkers.forEach((m) => {
    const popup = m.getPopup();
    if (popup && typeof popup.getContent === "function") {
      const content = popup.getContent();
      const normContent = content ? content.toLowerCase().trim() : "";
      const normNick = state.me.nickname ? state.me.nickname.toLowerCase().trim() : "";
      if (normContent && normNick && normContent.includes(`<b>${normNick}</b>`)) {
        fallbackLatLng = m.getLatLng();
      }
    }
  });
  if (fallbackLatLng) {
    rememberCommandZoomAnchor(fallbackLatLng);
    setViewCentered(fallbackLatLng, Math.max(state.map.getZoom(), 5));
  }
}

function switchLegendTab(tabId) {
  const groupBtn = document.getElementById("tab-btn-group");
  const filtersBtn = document.getElementById("tab-btn-filters");
  const groupContent = document.getElementById("tab-content-group");
  const filtersContent = document.getElementById("tab-content-filters");

  if (!groupBtn || !filtersBtn || !groupContent || !filtersContent) return;

  if (tabId === "group") {
    groupBtn.classList.add("active");
    filtersBtn.classList.remove("active");
    groupContent.classList.remove("hidden");
    filtersContent.classList.add("hidden");
  } else {
    groupBtn.classList.remove("active");
    filtersBtn.classList.add("active");
    groupContent.classList.add("hidden");
    filtersContent.classList.remove("hidden");
  }
}

function openAppModal() {
  document.getElementById("app-modal")?.classList.remove("hidden");
}

function closeAppModal() {
  document.getElementById("app-modal")?.classList.add("hidden");
}

// Expose functions globally for inline HTML event handlers
window.focusOnPlayer = focusOnPlayer;
window.focusOnMarker = focusOnMarker;
window.deleteMarker = deleteMarker;
window.switchLegendTab = switchLegendTab;
window.navRouteTo = navRouteTo;
window.openMarkerEditModal = openMarkerEditModal;

// ============================================================
//  MARKER EDIT MODAL
// ============================================================

let _editMarkerId = null;
let _editImageFile = null;
let _editClearImage = false;
let _editPoiId = null;
let _editPoiIcon = "star";
let _editPoiImageFile = null;

function markerKindLabel(kind) {
  if (kind === "circle") return "Круг";
  if (kind === "line") return "Линия";
  return "Точка";
}

function updateMarkerEditGeometryFields(kind) {
  const isCircle = kind === "circle";
  const isLine = kind === "line";
  document.getElementById("marker-edit-circle-fields")?.classList.toggle("hidden", !isCircle);
  document.getElementById("marker-edit-line-fields")?.classList.toggle("hidden", !isLine);
}

function openMarkerEditModal(markerId) {
  if (state.geoEdit.markerId !== null) {
    stopGeometryEdit({ restoreMarker: true, silent: true });
  }
  const leafletMarker = state.pinMarkers.get(markerId);
  if (!leafletMarker) return;
  const m = leafletMarker._markerMeta;
  if (!m) return;
  if (isStashMarker(m) && !canManageStashes()) {
    alert("Серверные метки этой категории может редактировать только администратор или модератор");
    return;
  }

  _editMarkerId = markerId;
  _editImageFile = null;
  _editClearImage = false;

  // Fill form fields
  document.getElementById("marker-edit-title").value = m.title || "";
  document.getElementById("marker-edit-desc").value = m.description || "";
  const categoryInput = document.getElementById("marker-edit-category");
  if (categoryInput) categoryInput.value = (m.marker_category || "group");
  const kind = m.geometry_kind || "point";
  syncStaffCategoryControls(kind, isStashMarker(m));
  updateMarkerCategoryHint();
  const geometryKind = document.getElementById("marker-edit-geometry-kind");
  if (geometryKind) geometryKind.value = markerKindLabel(kind);
  const radiusInput = document.getElementById("marker-edit-radius");
  if (radiusInput) radiusInput.value = String(Math.max(10, Number(m.radius || 300)));
  const strokeInput = document.getElementById("marker-edit-stroke-color");
  if (strokeInput) strokeInput.value = normalizeHexColor(m.stroke_color, "#ffffff");
  const fillInput = document.getElementById("marker-edit-fill-color");
  if (fillInput) fillInput.value = normalizeHexColor(m.fill_color, "#ffffff");
  const lineInput = document.getElementById("marker-edit-line-color");
  if (lineInput) lineInput.value = normalizeHexColor(m.stroke_color, "#00e5ff");
  updateMarkerEditGeometryFields(kind);

  // Set icon selection
  markerIconPickerApi?.resetSearch();
  markerIconPickerApi?.setSelected(m.type || "marker");

  // Image preview
  const previewWrap = document.getElementById("marker-img-preview");
  const previewImg = document.getElementById("marker-img-preview-img");
  const fileInput = document.getElementById("marker-img-file");
  fileInput.value = "";

  if (m.image_url) {
    previewImg.src = m.image_url;
    previewWrap.style.display = "block";
  } else {
    previewImg.src = "";
    previewWrap.style.display = "none";
  }

  document.getElementById("marker-edit-modal").classList.remove("hidden");
  document.getElementById("marker-edit-title").focus();
}

function closeMarkerEditModal() {
  document.getElementById("marker-edit-modal").classList.add("hidden");
  _editMarkerId = null;
  _editImageFile = null;
  _editClearImage = false;
}

function getPoiMeta(poiId) {
  const layer = state.poiMarkers.get(poiId);
  return layer?._poiMeta || null;
}

function openPoiEditModal(poiId) {
  const poi = getPoiMeta(poiId);
  if (!poi || !canManageMapStaff()) return;
  _editPoiId = poiId;
  _editPoiIcon = poi.icon || "star";
  _editPoiImageFile = null;
  document.getElementById("poi-edit-title").value = poi.title || "";
  document.getElementById("poi-edit-desc").value = poi.description || "";
  document.getElementById("poi-edit-x").value = Math.round(poi.x * 10) / 10;
  document.getElementById("poi-edit-y").value = Math.round(poi.y * 10) / 10;
  document.getElementById("poi-edit-image-file").value = "";
  renderPoiIconPicker(
    document.getElementById("poi-edit-icon-picker"),
    _editPoiIcon,
    (iconKey) => { _editPoiIcon = iconKey; },
  );
  document.getElementById("poi-edit-modal").classList.remove("hidden");
  document.getElementById("poi-edit-title").focus();
}

function closePoiEditModal() {
  document.getElementById("poi-edit-modal")?.classList.add("hidden");
  _editPoiId = null;
  _editPoiImageFile = null;
}

async function savePoiEdit() {
  if (!_editPoiId) return;
  const title = document.getElementById("poi-edit-title")?.value.trim();
  if (!title) {
    alert("Укажите название");
    return;
  }
  const payload = {
    title,
    description: document.getElementById("poi-edit-desc")?.value.trim() || "",
    icon: _editPoiIcon || "star",
    x: Number(document.getElementById("poi-edit-x")?.value),
    y: Number(document.getElementById("poi-edit-y")?.value),
  };
  try {
    const updated = await api(`/api/pois/${_editPoiId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    if (_editPoiImageFile) {
      const fd = new FormData();
      fd.append("file", _editPoiImageFile);
      const res = await fetch(`/api/pois/${_editPoiId}/image`, {
        method: "POST",
        credentials: "same-origin",
        body: fd,
      });
      const data = res.ok ? await res.json().catch(() => null) : null;
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        if (data?.detail) msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
        throw new Error(msg);
      }
      upsertPoi(data);
    } else {
      upsertPoi(updated);
    }
    closePoiEditModal();
  } catch (err) {
    alert(err.message);
  }
}

async function deletePoi(poiId) {
  if (!canManageMapStaff()) return;
  if (!confirm("Удалить серверную метку?")) return;
  try {
    await api(`/api/pois/${poiId}`, { method: "DELETE" });
    const layer = state.poiMarkers.get(poiId);
    if (layer && state.map) state.map.removeLayer(layer);
    state.poiMarkers.delete(poiId);
    closePoiEditModal();
  } catch (err) {
    alert(err.message);
  }
}

async function uploadMarkerImageIfPending(markerId) {
  if (!_editImageFile) return null;
  const fd = new FormData();
  fd.append("file", _editImageFile);
  const res = await fetch(`/api/markers/${markerId}/image`, {
    method: "POST",
    credentials: "same-origin",
    body: fd,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json().catch(() => null);
}

async function promoteMarkerToPoi(options = {}) {
  const { skipConfirm = false } = options;
  if (!_editMarkerId || !canManageMapStaff()) return false;
  const leafletMarker = state.pinMarkers.get(_editMarkerId);
  const m = leafletMarker?._markerMeta;
  if (!m || (m.geometry_kind || "point") !== "point") return false;
  if (isStashMarker(m)) return false;
  if (
    !skipConfirm
    && !confirm("Преобразовать метку в серверную? Исходная метка игрока будет удалена.")
  ) {
    return false;
  }

  const markerId = Number(_editMarkerId);
  const icon = markerTypeToPoiIcon(markerIconPickerApi?.getSelected() || m.type || "marker");
  try {
    if (_editClearImage) {
      await api(`/api/markers/${markerId}`, {
        method: "PATCH",
        body: JSON.stringify({ image_url: null }),
      });
    }
    const withImage = await uploadMarkerImageIfPending(markerId);
    if (withImage) upsertPin({ ...m, ...withImage });

    const poi = await api(`/api/markers/${markerId}/promote-to-poi`, {
      method: "POST",
      body: JSON.stringify({
        icon,
        title: document.getElementById("marker-edit-title")?.value.trim() || m.title || "Метка",
        description: document.getElementById("marker-edit-desc")?.value.trim() || m.description || "",
      }),
    });
    removePin(markerId);
    upsertPoi(poi);
    closeMarkerEditModal();
    return true;
  } catch (err) {
    alert(err.message);
    return false;
  }
}

window.openPoiEditModal = openPoiEditModal;

// Icon buttons
renderMarkerIconGrid();

// Image file input
const markerImgFile = document.getElementById("marker-img-file");
const markerImgDrop = document.getElementById("marker-img-drop");
const markerImgPreview = document.getElementById("marker-img-preview");
const markerImgPreviewImg = document.getElementById("marker-img-preview-img");
const markerEditModal = document.getElementById("marker-edit-modal");

function _clipboardImageFile(event) {
  const items = event?.clipboardData?.items;
  if (!items || !items.length) return null;
  for (const item of items) {
    if (item.kind === "file" && item.type && item.type.startsWith("image/")) {
      const file = item.getAsFile();
      if (file) return file;
    }
  }
  return null;
}

function _showImgPreview(file) {
  _editImageFile = file;
  _editClearImage = false;
  const reader = new FileReader();
  reader.onload = (ev) => {
    markerImgPreviewImg.src = ev.target.result;
    markerImgPreview.style.display = "block";
  };
  reader.readAsDataURL(file);
}

markerImgFile.addEventListener("change", () => {
  if (markerImgFile.files[0]) _showImgPreview(markerImgFile.files[0]);
});

// Drag-and-drop
markerImgDrop.addEventListener("dragover", (e) => { e.preventDefault(); markerImgDrop.classList.add("dragover"); });
markerImgDrop.addEventListener("dragleave", () => markerImgDrop.classList.remove("dragover"));
markerImgDrop.addEventListener("drop", (e) => {
  e.preventDefault();
  markerImgDrop.classList.remove("dragover");
  const file = e.dataTransfer?.files?.[0];
  if (file && file.type.startsWith("image/")) _showImgPreview(file);
});

// Paste image from clipboard (Ctrl+V) when edit modal is open.
markerEditModal?.addEventListener("paste", (e) => {
  if (markerEditModal.classList.contains("hidden")) return;
  const imageFile = _clipboardImageFile(e);
  if (!imageFile) return;
  e.preventDefault();
  _showImgPreview(imageFile);
});

// Clear image button
document.getElementById("marker-img-clear").addEventListener("click", () => {
  markerImgPreviewImg.src = "";
  markerImgPreview.style.display = "none";
  markerImgFile.value = "";
  _editImageFile = null;
  _editClearImage = true;
});

// Cancel
document.getElementById("marker-edit-cancel").addEventListener("click", closeMarkerEditModal);
document.getElementById("marker-edit-category")?.addEventListener("change", updateMarkerCategoryHint);

// Close on backdrop click
document.getElementById("marker-edit-modal").addEventListener("click", (e) => {
  if (e.target === document.getElementById("marker-edit-modal")) closeMarkerEditModal();
});

// Save
document.getElementById("marker-edit-save").addEventListener("click", async () => {
  if (!_editMarkerId) return;

  const markerId = Number(_editMarkerId);
  const existingMarker = state.pinMarkers.get(markerId);
  const existingMeta = existingMarker?._markerMeta || null;
  const selectedType = markerIconPickerApi?.getSelected() || "marker";
  const saveBtn = document.getElementById("marker-edit-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "⏳ Сохраняю…";

  try {
    const markerKind = existingMeta?.geometry_kind || "point";
    const selectedCategory = document.getElementById("marker-edit-category")?.value || "group";
    if (selectedCategory === "poi") {
      await promoteMarkerToPoi();
      return;
    }

    const circleRadius = Number(document.getElementById("marker-edit-radius")?.value || 300);
    const circleStroke = normalizeHexColor(document.getElementById("marker-edit-stroke-color")?.value, "#ffffff");
    const circleFill = normalizeHexColor(document.getElementById("marker-edit-fill-color")?.value, "#ffffff");
    const lineStroke = normalizeHexColor(document.getElementById("marker-edit-line-color")?.value, "#00e5ff");
    const patchBody = {
      title: document.getElementById("marker-edit-title").value.trim() || null,
      description: document.getElementById("marker-edit-desc").value.trim() || null,
      type: selectedType,
      marker_category: selectedCategory,
    };
    if (markerKind === "circle") {
      patchBody.radius = Math.max(10, Number.isFinite(circleRadius) ? circleRadius : 300);
      patchBody.stroke_color = circleStroke;
      patchBody.fill_color = circleFill;
    } else if (markerKind === "line") {
      patchBody.stroke_color = lineStroke;
    }
    if (_editClearImage) patchBody.image_url = null;

    const patched = await api(`/api/markers/${markerId}`, {
      method: "PATCH",
      body: JSON.stringify(patchBody),
    });
    // Apply immediately in current tab (websocket can lag or reconnect).
    upsertPin(existingMeta ? { ...existingMeta, ...patched } : patched);

    // Upload image if selected
    if (_editImageFile) {
      const fd = new FormData();
      fd.append("file", _editImageFile);
      const res = await fetch(`/api/markers/${markerId}/image`, {
        method: "POST",
        credentials: "same-origin",
        body: fd,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const withImage = await res.json().catch(() => null);
      if (withImage) {
        upsertPin(existingMeta ? { ...existingMeta, ...withImage } : withImage);
      }
    }

    closeMarkerEditModal();
  } catch (e) {
    alert("Ошибка при сохранении: " + e.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "💾 Сохранить";
  }
});

document.getElementById("poi-edit-cancel")?.addEventListener("click", closePoiEditModal);
document.getElementById("poi-edit-close")?.addEventListener("click", closePoiEditModal);
document.getElementById("poi-edit-save")?.addEventListener("click", savePoiEdit);
document.getElementById("poi-edit-delete")?.addEventListener("click", () => {
  if (_editPoiId) deletePoi(_editPoiId);
});
document.getElementById("poi-edit-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "poi-edit-modal") closePoiEditModal();
});
document.getElementById("poi-edit-image-file")?.addEventListener("change", (e) => {
  _editPoiImageFile = e.target.files?.[0] || null;
});

function connectWebSocket() {
  state.wsClosing = false;  // сбрасываем флаг при каждом новом подключении
  const proto = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${proto}://${location.host}/ws/map`);

  state.ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    console.log("WS received:", msg);
    if (msg.type === "position") upsertLive(msg.data);
    if (msg.type === "marker_added") upsertPin(msg.data);
    if (msg.type === "marker_updated") upsertPin(msg.data);
    if (msg.type === "marker_deleted") removePin(msg.data.id);
    if (msg.type === "pois_changed") reloadPois();
    if (msg.type === "user_profile") {
      const data = msg.data || {};
      if (data.user_id != null) {
        state.userAvatars.set(data.user_id, data.avatar_url ?? null);
        refreshUserAvatars(data.user_id);
      }
    }
    if (msg.type === "map_command") {
      const action = msg.data?.action;
      console.log("Executing map command:", action);
      if (action === "focus_me") focusMe();
      else applyCommandZoom(action);
    }
  };

  state.ws.onclose = () => {
    if (state.wsClosing) return;  // намеренный выход — не переподключаемся
    setTimeout(connectWebSocket, 3000);
  };
}

async function loadRoomState() {
  const data = await api("/api/room/state");
  if (state.filters.players) data.positions.forEach(upsertLive);
  if (state.filters.markers) data.markers.forEach(upsertPin);
  if (state.filters.poi) data.pois.forEach(upsertPoi);
}

function locationMinMapZoom(minZoom) {
  if (minZoom <= 1) return 0;
  if (minZoom === 2) return 2;
  if (minZoom === 3) return 3;
  return 4;
}

function renderLocationLabels(locations) {
  if (!state.locationLayer) return;
  state.locationLayer.clearLayers();
  state.locationEntries = [];

  locations.forEach((loc, idx) => {
    const latlng = gameToLatLng(loc.x, loc.y);
    const icon = L.divIcon({
      className: `map-label type-${loc.label_class || "local"}`,
      html: `<span>${loc.title}</span>`,
      iconSize: [200, 30],
      iconAnchor: [100, 15],
    });
    const marker = L.marker(latlng, { icon, interactive: false, pane: "labelsPane" });
    marker._locMeta = loc;
    marker._locId = idx;
    state.locationEntries.push(marker);
  });
  applyLocationFilters();
}

function applyLocationFilters() {
  if (!state.locationLayer || !state.map) return;
  state.locationLayer.clearLayers();
  if (!state.filters.labels) return;

  const zoom = state.map.getZoom();
  state.locationEntries.forEach((marker) => {
    const loc = marker._locMeta;
    if (!state.filters[loc.category]) return;
    if (zoom < locationMinMapZoom(loc.min_zoom || 4)) return;
    state.locationLayer.addLayer(marker);
  });
}

function updateLocationVisibility() {
  applyLocationFilters();
}

function clearRadiationLayers() {
  state.radiationOverlay = null;
  if (state.radiationLayer) state.radiationLayer.clearLayers();
  if (state.psiLayer) state.psiLayer.clearLayers();
}

function renderRadiationLayer(data) {
  if (!state.map || !state.radiationLayer || !state.psiLayer) return;
  clearRadiationLayers();

  if (state.filters.radiation) {
    const overlay = data?.overlay;
    // Полноэкранный JPG поверх тайлов даёт «двоение» и перекрывает подписи — только по явному флагу.
    if (overlay?.url && overlay?.enabled && !(data?.zones?.length) && !(data?.polygons?.length)) {
      const bounds = gameBoundsToLatLng(overlay.bounds || {});
      state.radiationOverlay = L.imageOverlay(overlay.url, bounds, {
        opacity: Math.min(overlay.opacity ?? 0.55, 0.85),
        interactive: false,
        pane: "radiationPane",
      });
      state.radiationLayer.addLayer(state.radiationOverlay);
    }

    (data?.polygons || []).forEach((poly) => {
      if ((data?.zones || []).length) return;
      const rings = (poly.rings || [])
        .map((ring) => ring.map(([x, y]) => gameToLatLng(x, y)))
        .filter((ring) => ring.length >= 3);
      if (!rings.length) return;
      const polygon = L.polygon(rings, {
        color: poly.color || "#ff9800",
        weight: poly.weight ?? 2,
        opacity: poly.strokeOpacity ?? 0.95,
        fillColor: poly.color || "#ff9800",
        fillOpacity: poly.fillOpacity ?? 0.42,
        interactive: false,
        pane: "radiationPane",
      });
      if (poly.label) {
        polygon.bindTooltip(poly.label, { permanent: false, direction: "top" });
      }
      state.radiationLayer.addLayer(polygon);
    });

    (data?.zones || []).forEach((zone) => {
      const latlng = gameToLatLng(zone.x, zone.y);
      const circle = L.circle(latlng, {
        radius: gameRadiusToLeaflet(zone.radius),
        color: zone.color || "#ff9800",
        weight: zone.weight ?? 2,
        opacity: zone.strokeOpacity ?? 0.9,
        fillColor: zone.color || "#ff9800",
        fillOpacity: zone.fillOpacity ?? 0.35,
        interactive: false,
        pane: "radiationPane",
      });
      state.radiationLayer.addLayer(circle);
    });
  }

  if (state.filters.psi) {
    (data?.psi_zones || []).forEach((zone) => {
      const latlng = gameToLatLng(zone.x, zone.y);
      const color = zone.color || "#6b102e";
      const circle = L.circle(latlng, {
        radius: gameRadiusToLeaflet(zone.radius),
        color,
        weight: zone.weight ?? 2,
        opacity: zone.strokeOpacity ?? 0.95,
        fillColor: color,
        fillOpacity: zone.fillOpacity ?? 0.2,
        interactive: false,
        pane: "radiationPane",
      });
      circle.on("add", () => applyPsiStripedFill(circle));
      state.psiLayer.addLayer(circle);
    });
  }

  applyRadiationVisibility();
  renderRadiationLegend(data?.legend || []);
}

function applyRadiationVisibility() {
  if (!state.radiationLayer || !state.psiLayer || !state.map) return;
  if (state.filters.radiation) {
    if (!state.map.hasLayer(state.radiationLayer)) {
      state.radiationLayer.addTo(state.map);
    }
  } else {
    state.map.removeLayer(state.radiationLayer);
  }
  if (state.filters.psi) {
    if (!state.map.hasLayer(state.psiLayer)) {
      state.psiLayer.addTo(state.map);
    }
  } else {
    state.map.removeLayer(state.psiLayer);
  }
}

function renderRadiationLegend(legend) {
  const el = document.getElementById("radiation-legend");
  if (!el) return;
  if (!legend.length) {
    el.innerHTML = "";
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");
  el.innerHTML = `
    <h3>Радиация</h3>
    <ul>${legend
      .map(
        (item) =>
          `<li><span class="rad-dot" style="background:${item.color}"></span>${item.label}</li>`,
      )
      .join("")}</ul>`;
}

function renderFilterPanel(categories) {
  const el = document.getElementById("filter-list");
  if (!el) return;

  const staticFilters = [
    { id: "labels", label: "Названия мест" },
    { id: "players", label: "Игроки (live)" },
    { id: "markers", label: "Метки группы" },
    { id: "stashes", label: "Скрыть тайники" },
    { id: "mutants", label: "Мутанты" },
    { id: "hunting", label: "Охота" },
    { id: "poi", label: "Метки сервера" },
    { id: "radiation", label: "Радиационные зоны" },
    { id: "psi", label: "Пси-зоны" },
  ];

  const dynamic = (categories || []).map((c) => ({
    id: c.id,
    label: `${c.label} (${c.count})`,
  }));
  const all = [...staticFilters, ...dynamic];

  el.innerHTML = all
    .map(
      (f) => `
    <label class="filter-row">
      <input type="checkbox" data-filter="${f.id}" ${state.filters[f.id] !== false ? "checked" : ""}>
      ${f.label}
    </label>`
    )
    .join("");

  el.querySelectorAll("input[data-filter]").forEach((input) => {
    input.addEventListener("change", () => {
      state.filters[input.dataset.filter] = input.checked;
      saveFilterPrefs();
      if (input.dataset.filter === "stashes") {
        syncStashVisibilityControls();
      }
      applyLocationFilters();
      refreshDynamicLayers();
      updateMarkersList();
      if ((input.dataset.filter === "radiation" || input.dataset.filter === "psi") && state.radiationData) {
        renderRadiationLayer(state.radiationData);
      } else {
        applyRadiationVisibility();
      }
    });
  });
}

function refreshDynamicLayers() {
  if (!state.map) return;
  state.liveMarkers.forEach((m) => {
    if (state.filters.players) m.addTo(state.map);
    else state.map.removeLayer(m);
  });
  state.pinMarkers.forEach((m) => {
    const shouldShow = markerVisibleOnMap(m._markerMeta?.marker_category);
    if (shouldShow) m.addTo(state.map);
    else state.map.removeLayer(m);
  });
  state.poiMarkers.forEach((m) => {
    if (state.filters.poi) m.addTo(state.map);
    else state.map.removeLayer(m);
  });
  applyRadiationVisibility();
}

function syncStashVisibilityControls() {
  const localToggle = document.getElementById("stashes-visible-toggle");
  if (localToggle) localToggle.checked = !!state.filters.stashes;
  const filterToggle = document.querySelector('#filter-list input[data-filter="stashes"]');
  if (filterToggle) filterToggle.checked = !!state.filters.stashes;
}

async function loadMapLocations() {
  if (!state.me) return;
  const slug = state.me.map_slug;
  const urls = [`/api/maps/${slug}/locations`, "/api/map/locations"];
  let data = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (res.ok) {
        data = await res.json();
        break;
      }
    } catch {
      /* try next */
    }
  }
  if (!data) {
    renderFilterPanel([]);
    return;
  }
  renderFilterPanel(data.categories || []);
  renderLocationLabels(data.locations || []);
}

async function loadMapRadiation() {
  if (!state.me) return;
  const slug = state.me.map_slug;
  try {
    const res = await fetch(`/api/maps/${slug}/radiation`, { credentials: "same-origin" });
    if (!res.ok) return;
    const data = await res.json();
    state.radiationData = data;
    renderRadiationLayer(data);
  } catch {
    /* optional layer */
  }
}

async function bootstrapMapView() {
  state.me = await api("/api/auth/me");
  state.config = await api(`/api/maps/${state.me.map_slug}/config`);

  showMap();
  await waitForLayout();

  if (!state.map) {
    initLeaflet(state.config);
  } else {
    setTileLayer(state.layerType);
  }
  refreshMapLayout();
  restoreMapView();

  document.getElementById("user-label").textContent = state.me.nickname;
  document.getElementById("room-label").textContent = `${state.me.map_name} · PIN: ${state.me.pin}`;
  window.ProfileUi?.syncAvatarUi();
  window.ProfileUi?.syncAdminPanelLink?.();
  await ensureClientKey();
  syncStaffCategoryControls();
  const roadsFilter = document.getElementById("filter-roads");
  if (roadsFilter) roadsFilter.checked = !!state.filters.roads;
  const buildingsFilter = document.getElementById("filter-buildings");
  if (buildingsFilter) buildingsFilter.checked = !!state.filters.buildings;
  syncStashVisibilityControls();
  await Promise.all([loadRoomState(), loadMapLocations(), loadMapRadiation(), loadRoads(), loadBuildings()]);
  connectWebSocket();
  initNavigatorButton();
  initMapContextMenu();
}

async function loadMapOptions() {
  const maps = await api("/api/maps");
  const sel = document.getElementById("map-slug");
  if (!maps.length) {
    sel.innerHTML = `<option value="">Нет доступных карт</option>`;
    return;
  }
  sel.innerHTML = maps.map((m) => `<option value="${m.slug}">${m.name}</option>`).join("");
}

async function loadPinPolicyHint() {
  const hint = document.getElementById("pin-policy-hint");
  if (!hint) return;
  try {
    const data = await api("/api/auth/pin-policy");
    if (data.public_pin_creation) {
      hint.classList.add("hidden");
      hint.textContent = "";
    } else {
      hint.textContent =
        "Создание новых PIN отключено. Войти можно только в существующую группу — PIN выдаёт администратор.";
      hint.classList.remove("hidden");
    }
  } catch {
    hint.classList.add("hidden");
  }
}

let loginRequirementsTimer = null;

function applyLoginRequirements(data) {
  const roomWrap = document.getElementById("room-password-wrap");
  const profileWrap = document.getElementById("profile-password-wrap");
  const newProfileWrap = document.getElementById("new-profile-password-wrap");
  if (!roomWrap || !profileWrap || !newProfileWrap) return;

  roomWrap.classList.toggle("hidden", !data.room_password_required);
  profileWrap.classList.toggle("hidden", !data.profile_password_required);
  newProfileWrap.classList.toggle("hidden", !(data.is_new_user && !data.profile_password_required));

  if (!data.room_password_required) {
    const roomInput = document.getElementById("room-password");
    if (roomInput) roomInput.value = "";
  }
  if (!data.profile_password_required) {
    const profileInput = document.getElementById("profile-password");
    if (profileInput) profileInput.value = "";
  }
  if (!data.is_new_user || data.profile_password_required) {
    const newProfileInput = document.getElementById("new-profile-password");
    if (newProfileInput) newProfileInput.value = "";
  }
}

async function refreshLoginRequirements() {
  const mapSlug = document.getElementById("map-slug")?.value;
  const pin = document.getElementById("pin")?.value.trim();
  const nickname = document.getElementById("nickname")?.value.trim();
  if (!mapSlug || pin.length < 4 || nickname.length < 2) {
    applyLoginRequirements({
      room_password_required: false,
      profile_password_required: false,
      is_new_user: true,
    });
    return;
  }
  try {
    const data = await api("/api/auth/login-requirements", {
      method: "POST",
      body: JSON.stringify({ map_slug: mapSlug, pin, nickname }),
    });
    applyLoginRequirements(data);
  } catch {
    applyLoginRequirements({
      room_password_required: false,
      profile_password_required: false,
      is_new_user: true,
    });
  }
}

function scheduleLoginRequirementsRefresh() {
  clearTimeout(loginRequirementsTimer);
  loginRequirementsTimer = setTimeout(refreshLoginRequirements, 350);
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("login-error");
  errEl.classList.add("hidden");
  try {
    const map_slug = document.getElementById("map-slug").value;
    const pin = document.getElementById("pin").value.trim();
    const nickname = document.getElementById("nickname").value.trim();
    const room_password = document.getElementById("room-password")?.value || null;
    const profile_password =
      document.getElementById("profile-password")?.value ||
      document.getElementById("new-profile-password")?.value ||
      null;
    const payload = { map_slug, pin, nickname };
    if (room_password) payload.room_password = room_password;
    if (profile_password) payload.profile_password = profile_password;
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.client_key) {
      showKeyModal(data.client_key);
    } else {
      alert(data.message);
    }
    await bootstrapMapView();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
  }
});

function performMapLogoutCleanup() {
  if (state.ws) {
    state.wsClosing = true;
    state.ws.close();
    state.ws = null;
  }
  state.me = null;
  state.clientKey = null;
  state.userAvatars.clear();
  state.liveMarkers.forEach((m) => { if (state.map) state.map.removeLayer(m); });
  state.liveMarkers.clear();
  state.pinMarkers.forEach((m) => { if (state.map) state.map.removeLayer(m); });
  state.pinMarkers.clear();
  state.poiMarkers.forEach((m) => { if (state.map) state.map.removeLayer(m); });
  state.poiMarkers.clear();
  clearCoordLookupMarker();
  state.lastMouseGameCoords = null;
  state.locationEntries = [];
  if (state.locationLayer) state.locationLayer.clearLayers();
  clearRadiationLayers();
  if (state.roadLayer) state.roadLayer.clearLayers();
  if (state.buildingLayer) state.buildingLayer.clearLayers();
  stopGeometryEdit({ restoreMarker: false, silent: true });
  setDrawMode(null);
  showLogin();
}

document.getElementById("reset-key-btn").addEventListener("click", async () => {
  if (!confirm("Старый ключ перестанет работать. Создать новый?")) return;
  try {
    const data = await api("/api/auth/reset-key", { method: "POST" });
    showKeyModal(data.client_key);
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("copy-key-btn").addEventListener("click", async () => {
  const key = await ensureClientKey();
  if (key) showKeyModal(key);
  else {
    alert(
      "Ключ не сохранён в этой сессии браузера. Если вы уже настраивали клиент раньше — используйте сохранённый ключ. " +
        "Если потеряли — нажмите «Создать новый ключ» (старый перестанет работать)."
    );
  }
});

document.getElementById("copy-key-confirm").addEventListener("click", () => {
  if (state.clientKey) navigator.clipboard.writeText(state.clientKey);
});

document.getElementById("close-key-modal").addEventListener("click", () => {
  document.getElementById("key-modal").classList.add("hidden");
});

document.getElementById("app-btn")?.addEventListener("click", openAppModal);
document.getElementById("close-app-modal")?.addEventListener("click", closeAppModal);
document.getElementById("app-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "app-modal") closeAppModal();
});

["map-slug", "pin", "nickname"].forEach((id) => {
  document.getElementById(id)?.addEventListener("input", scheduleLoginRequirementsRefresh);
  document.getElementById(id)?.addEventListener("change", scheduleLoginRequirementsRefresh);
});

document.getElementById("marker-image-close")?.addEventListener("click", closeMarkerImageModal);
document.getElementById("marker-image-modal")?.addEventListener("click", (e) => {
  if (e.target === document.getElementById("marker-image-modal")) {
    closeMarkerImageModal();
  }
});

document.getElementById("btn-layer-sat")?.addEventListener("click", () => setTileLayer("satellite"));
document.getElementById("btn-layer-topo")?.addEventListener("click", () => setTileLayer("topographic"));

document.getElementById("btn-focus-me")?.addEventListener("click", focusMe);

document.getElementById("coord-lookup-btn")?.addEventListener("click", showCoordLookup);
document.getElementById("coord-lookup-from-cursor-btn")?.addEventListener("click", fillCoordLookupFromCursor);
document.getElementById("coord-lookup-clear-btn")?.addEventListener("click", () => {
  clearCoordLookupMarker();
  const input = document.getElementById("coord-lookup-input");
  if (input) input.value = "";
});
document.getElementById("coord-lookup-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") showCoordLookup();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const ctxMenu = document.getElementById("map-context-menu");
    if (ctxMenu && !ctxMenu.classList.contains("hidden")) {
      closeMapContextMenu();
      return;
    }
    const poiModal = document.getElementById("poi-edit-modal");
    if (poiModal && !poiModal.classList.contains("hidden")) {
      closePoiEditModal();
      return;
    }
    const imgModal = document.getElementById("marker-image-modal");
    if (imgModal && !imgModal.classList.contains("hidden")) {
      closeMarkerImageModal();
      return;
    }
    const appModal = document.getElementById("app-modal");
    if (appModal && !appModal.classList.contains("hidden")) {
      closeAppModal();
      return;
    }
  }
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") {
    return;
  }
  if (e.key === "/") {
    e.preventDefault();
    document.getElementById("btn-focus-me")?.click();
  }
});

document.getElementById("legend-toggle")?.addEventListener("click", () => {
  const legend = document.getElementById("legend");
  const btn = document.getElementById("legend-toggle");
  if (legend.classList.contains("collapsed")) {
    legend.classList.remove("collapsed");
    btn.textContent = "▶";
    setTimeout(() => {
      if (state.map) state.map.invalidateSize({ animate: false });
    }, 320);
  } else {
    legend.classList.add("collapsed");
    btn.textContent = "◀";
    setTimeout(() => {
      if (state.map) state.map.invalidateSize({ animate: false });
    }, 320);
  }
});

window.addEventListener("resize", () => {
  if (state.map) {
    state.map.invalidateSize({ animate: false });
    updateMinZoom();
  }
});

// Roads filter toggle
document.getElementById("filter-roads")?.addEventListener("change", (e) => {
  state.filters.roads = e.target.checked;
  saveFilterPrefs();
  applyRoadsVisibility();
});

document.getElementById("filter-buildings")?.addEventListener("change", (e) => {
  state.filters.buildings = e.target.checked;
  saveFilterPrefs();
  applyBuildingsVisibility();
});

document.getElementById("stashes-visible-toggle")?.addEventListener("change", (e) => {
  state.filters.stashes = !!e.target.checked;
  saveFilterPrefs();
  syncStashVisibilityControls();
  refreshDynamicLayers();
  updateMarkersList();
});

document.getElementById("stashes-collapse-btn")?.addEventListener("click", () => {
  const list = document.getElementById("web-stashes-list");
  const btn = document.getElementById("stashes-collapse-btn");
  const count = document.getElementById("stashes-total-count")?.textContent || "0";
  if (!list || !btn) return;
  const collapsed = !list.classList.contains("hidden");
  list.classList.toggle("hidden", collapsed);
  btn.innerHTML = `${collapsed ? "▸" : "▾"} Тайники (<span id="stashes-total-count">${count}</span>)`;
});

document.getElementById("draw-point-btn")?.addEventListener("click", () => {
  setDrawMode("point");
  closeMapContextMenu();
});
document.getElementById("draw-circle-btn")?.addEventListener("click", () => setDrawMode("circle"));
document.getElementById("draw-line-btn")?.addEventListener("click", () => setDrawMode("line"));
document.getElementById("draw-cancel-btn")?.addEventListener("click", () => {
  setDrawMode(null);
  closeMapContextMenu();
});
document.getElementById("draw-finish-btn")?.addEventListener("click", () => {
  finishLineDrawing();
  closeMapContextMenu();
});
document.getElementById("geo-edit-save-btn")?.addEventListener("click", saveGeometryEdit);
document.getElementById("geo-edit-cancel-btn")?.addEventListener("click", () => {
  stopGeometryEdit({ restoreMarker: true });
});



function applyClientDownloadUrl(url) {
  document.querySelectorAll(".client-download").forEach((el) => {
    el.href = url;
  });
}

async function initClientDownloadLinks() {
  try {
    const maps = await api("/api/maps");
    if (!maps.length) return;
    const cfg = await api(`/api/maps/${maps[0].slug}/config`);
    if (cfg.client_download_url) applyClientDownloadUrl(cfg.client_download_url);
  } catch {
    /* keep default href from HTML */
  }
}

(async () => {
  window.ProfileUi?.init({
    getUser: () => state.me,
    setUser: (user) => {
      state.me = user;
      if (user?.user_id != null) {
        state.userAvatars.set(user.user_id, user.avatar_url ?? null);
        refreshUserAvatars(user.user_id);
      }
    },
    onRoomPinChange: (pin) => {
      if (!state.me) return;
      state.me.pin = pin;
      document.getElementById("room-label").textContent = `${state.me.map_name} · PIN: ${pin}`;
    },
    onLogout: performMapLogoutCleanup,
  });

  try {
    await loadMapOptions();
    await loadPinPolicyHint();
    await initClientDownloadLinks();
  } catch {
    /* login page still usable */
  }
  try {
    await api("/api/auth/me");
    await bootstrapMapView();
  } catch {
    showLogin();
  }
})();

// ============================================================
//  ROADS — load & display
// ============================================================

const ROAD_COLORS_MAP = {
  highway: "#f5c900",
  road: "#f5c900",
  street: "#f5c900",
};

const ROAD_WEIGHTS_MAP = {
  highway: 4,
  road: 2.5,
  street: 2,
};

async function loadRoads() {
  if (!state.me || !state.roadLayer) return;
  try {
    const segments = await api(`/api/maps/${state.me.map_slug}/roads`);
    renderRoads(segments);
  } catch {
    /* roads are optional; silently skip */
  }
}

function renderRoads(segments) {
  if (!state.roadLayer) return;
  state.roadLayer.clearLayers();
  if (!segments || !segments.length) return;

  segments.forEach((seg) => {
    const latLngs = seg.points.map(([x, y]) => gameToLatLng(x, y));
    const color = ROAD_COLORS_MAP[seg.road_type] || "#fff";
    const weight = ROAD_WEIGHTS_MAP[seg.road_type] || 3;

    L.polyline(latLngs, {
      color,
      weight,
      opacity: 0.85,
      lineJoin: "round",
      lineCap: "butt",
      smoothFactor: 1.5,
      interactive: false,
    }).addTo(state.roadLayer);
  });

  // Apply visibility filter
  applyRoadsVisibility();
}

function applyRoadsVisibility() {
  if (!state.map || !state.roadLayer) return;
  if (state.filters.roads) {
    if (!state.map.hasLayer(state.roadLayer)) state.roadLayer.addTo(state.map);
  } else {
    state.map.removeLayer(state.roadLayer);
  }
}

// ============================================================
//  SERVER BUILDINGS — load & display
// ============================================================

const BUILDING_TYPE_COLORS = {
  structure: { stroke: "#e67e22", fill: "#e67e22" },
  residential: { stroke: "#3498db", fill: "#3498db" },
  industrial: { stroke: "#95a5a6", fill: "#95a5a6" },
  military: { stroke: "#c0392b", fill: "#c0392b" },
  commercial: { stroke: "#9b59b6", fill: "#9b59b6" },
  other: { stroke: "#f1c40f", fill: "#f1c40f" },
};

const BUILDING_TYPE_LABELS = {
  structure: "Строение",
  residential: "Жилое",
  industrial: "Промышленное",
  military: "Военное",
  commercial: "Коммерческое",
  other: "Прочее",
};

function buildingFootprintCorners(b) {
  const hw = (b.width || 20) / 2;
  const hd = (b.depth || 15) / 2;
  const rad = ((b.yaw || 0) * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  const local = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]];
  return local.map(([lx, ly]) => ({
    x: b.x + lx * cos - ly * sin,
    y: b.y + lx * sin + ly * cos,
  }));
}

function buildingColors(b) {
  const preset = BUILDING_TYPE_COLORS[b.building_type] || BUILDING_TYPE_COLORS.structure;
  return {
    stroke: b.stroke_color || preset.stroke,
    fill: b.fill_color || preset.fill,
  };
}

function buildingPopupHtml(b) {
  const typeLabel = BUILDING_TYPE_LABELS[b.building_type] || b.building_type;
  const classname = b.classname ? `<div style="font-size:0.82rem;color:#888;margin-top:2px">${markerEscapeHtml(b.classname)}</div>` : "";
  const desc = b.description ? `<div style="margin-top:6px;font-size:0.9rem">${markerEscapeHtml(b.description)}</div>` : "";
  return `
    <b>${markerEscapeHtml(b.title)}</b>
    <div style="font-size:0.82rem;color:#666;margin-top:2px">${markerEscapeHtml(typeLabel)} · ${Math.round(b.x)} / ${Math.round(b.y)}</div>
    ${classname}
    ${desc}
    <div class="marker-popup-actions">
      <button class="marker-route" data-x="${b.x}" data-y="${b.y}">Маршрут</button>
    </div>
  `;
}

async function loadBuildings() {
  if (!state.me || !state.buildingLayer) return;
  try {
    const buildings = await api(`/api/maps/${state.me.map_slug}/buildings`);
    renderBuildings(buildings);
  } catch {
    /* optional layer */
  }
}

function renderBuildings(buildings) {
  if (!state.buildingLayer) return;
  state.buildingLayer.clearLayers();
  if (!buildings || !buildings.length) {
    applyBuildingsVisibility();
    return;
  }

  buildings.forEach((b) => {
    const corners = buildingFootprintCorners(b).map((p) => gameToLatLng(p.x, p.y));
    const { stroke, fill } = buildingColors(b);
    const layer = L.polygon(corners, {
      color: stroke,
      fillColor: fill,
      fillOpacity: 0.24,
      weight: 2,
      opacity: 0.9,
      pane: "buildingsPane",
    });
    layer.bindPopup(buildingPopupHtml(b));
    layer.bindTooltip(markerEscapeHtml(b.title), { sticky: true });
    layer.addTo(state.buildingLayer);
  });

  applyBuildingsVisibility();
}

function applyBuildingsVisibility() {
  if (!state.map || !state.buildingLayer) return;
  if (state.filters.buildings) {
    if (!state.map.hasLayer(state.buildingLayer)) state.buildingLayer.addTo(state.map);
  } else {
    state.map.removeLayer(state.buildingLayer);
  }
}

// ============================================================
//  NAVIGATOR
// ============================================================

/** Convert Leaflet LatLng → game {x, y} (inverse of gameToLatLng) */
function latLngToGame(latlng) {
  if (!state.config) return { x: 0, y: 0 };
  if (isScumConfig(state.config)) {
    if (!state.map || typeof SCUM_COORDS === "undefined") return { x: 0, y: 0 };
    const p = state.map.project(latlng, SCUM_COORDS.MAX_ZOOM);
    return SCUM_COORDS.pixelToGame(p.x, p.y);
  }
  const size = mapSize(state.config);
  const ratio = size / 256;
  return {
    x: latlng.lng * ratio,
    y: (latlng.lat + 256) * ratio,
  };
}

function navMakeMarker(x, y, label, color) {
  const latlng = gameToLatLng(x, y);
  return L.marker(latlng, {
    icon: L.divIcon({
      html: `<div style="
        background:${color};
        color:#000;
        font-weight:700;
        font-size:12px;
        padding:2px 7px;
        border-radius:20px;
        border:2px solid #fff;
        box-shadow:0 2px 6px rgba(0,0,0,.6);
        white-space:nowrap;
      ">${label}</div>`,
      className: "",
      iconAnchor: [0, 0],
    }),
    zIndexOffset: 3000,
  }).addTo(state.map);
}

function navClearRoute() {
  if (state.navRouteLayer) {
    state.map.removeLayer(state.navRouteLayer);
    state.navRouteLayer = null;
  }
  state.navRoutePoints = [];
  state.navRouteManeuvers = [];
  const simBtn = document.getElementById("nav-sim-btn");
  if (simBtn) simBtn.style.display = "none";
  stopRouteSimulation();
  clearSimulationMarker();
}

function navClearMarkers() {
  if (state.navFromMarker) { state.map.removeLayer(state.navFromMarker); state.navFromMarker = null; }
  if (state.navToMarker) { state.map.removeLayer(state.navToMarker); state.navToMarker = null; }
}

function getPlayerLocation() {
  if (!state.me) return null;
  const marker = state.liveMarkers.get(state.me.user_id);
  if (marker && marker._playerMeta) {
    return { x: marker._playerMeta.x, y: marker._playerMeta.y };
  }
  return null;
}

function navReset() {
  state.navFrom = null;
  state.navTo = null;
  state.navStep = "from";
  navClearMarkers();
  navClearRoute();
  stopRouteSimulation();
  clearSimulationMarker();

  const pLoc = getPlayerLocation();
  if (pLoc) {
    state.navFrom = pLoc;
    state.navStep = "to";
  }

  updateNavUI();
}

function navRouteTo(x, y) {
  state.navActive = true;
  updateMapCursor();

  state.navTo = { x, y };
  if (state.navToMarker) state.map.removeLayer(state.navToMarker);
  state.navToMarker = navMakeMarker(x, y, "🔴 Финиш", "#ff1744");

  const pLoc = getPlayerLocation();
  if (pLoc) {
    state.navFrom = pLoc;
    if (state.navFromMarker) {
      state.map.removeLayer(state.navFromMarker);
      state.navFromMarker = null;
    }
    state.navStep = "to";
    updateNavUI("Прокладываю маршрут…");
    computeRoute();
  } else {
    state.navFrom = null;
    if (state.navFromMarker) {
      state.map.removeLayer(state.navFromMarker);
      state.navFromMarker = null;
    }
    state.navStep = "from";
    updateNavUI("Кликните точку старта на карте");
  }
}

function navSetPoint(x, y) {
  const pLoc = getPlayerLocation();
  if (pLoc) {
    state.navFrom = pLoc;
    state.navStep = "to";
  }

  if (state.navStep === "from") {
    state.navFrom = { x, y };
    if (state.navFromMarker) state.map.removeLayer(state.navFromMarker);
    state.navFromMarker = navMakeMarker(x, y, "🟢 Старт", "#00e676");
    state.navStep = "to";
    updateNavUI("Теперь кликните точку финиша");
  } else {
    state.navTo = { x, y };
    if (state.navToMarker) state.map.removeLayer(state.navToMarker);
    state.navToMarker = navMakeMarker(x, y, "🔴 Финиш", "#ff1744");

    if (pLoc) {
      state.navStep = "to"; // click again to choose a new destination
      updateNavUI("Прокладываю маршрут…");
    } else {
      state.navStep = "from"; // allow re-routing by clicking start again
      updateNavUI("Прокладываю маршрут…");
    }
    computeRoute();
  }
}

async function computeRoute() {
  const pLoc = getPlayerLocation();
  if (pLoc) {
    state.navFrom = pLoc;
  }
  if (!state.navFrom || !state.navTo || !state.me) return;
  navClearRoute();

  try {
    const result = await api(`/api/maps/${state.me.map_slug}/navigate`, {
      method: "POST",
      body: JSON.stringify({
        from_x: state.navFrom.x,
        from_y: state.navFrom.y,
        to_x: state.navTo.x,
        to_y: state.navTo.y,
      }),
    });

    if (!result.ok) {
      updateNavUI(`⚠ ${result.error || "Маршрут не найден"}`);
      return;
    }

    state.navRoutePoints = result.path;
    state.navRouteManeuvers = calculateManeuvers(result.path);
    resetRouteTracking();

    const latLngs = result.path.map(([x, y]) => gameToLatLng(x, y));
    state.navRouteLayer = L.polyline(latLngs, {
      color: "#00e5ff",
      weight: 5,
      opacity: 0.9,
      dashArray: "14 6",
      lineJoin: "round",
    }).addTo(state.map);

    // Fit bounds to route
    state.map.fitBounds(state.navRouteLayer.getBounds(), { padding: [40, 40] });

    const km = (result.total_distance / 1000).toFixed(2);
    updateNavUI(`✅ Маршрут: ~${km} км`);

    // Show simulation button
    const simBtn = document.getElementById("nav-sim-btn");
    if (simBtn) simBtn.style.display = "block";

    speak("Маршрут построен.");
  } catch (e) {
    updateNavUI(`⚠ Ошибка: ${e.message}`);
  }
}

function updateNavUI(statusText) {
  const btn = document.getElementById("btn-nav");
  const panel = document.getElementById("nav-panel");
  const status = document.getElementById("nav-status");

  if (!panel) return;

  if (state.navActive) {
    if (btn) btn.classList.add("active");
    panel.classList.remove("hidden");
    if (status && statusText) status.textContent = statusText;
    else if (status && !statusText) {
      status.textContent = state.navStep === "from"
        ? "Кликните точку старта на карте"
        : "Кликните точку финиша на карте";
    }
  } else {
    if (btn) btn.classList.remove("active");
    panel.classList.add("hidden");
  }
}

function toggleNavigator() {
  state.navActive = !state.navActive;
  if (state.navActive) {
    updateMapCursor();
    updateNavUI();
  } else {
    updateMapCursor();
    navReset();
    updateNavUI();
  }
}

function initNavigatorButton() {
  const btn = document.getElementById("btn-nav");
  if (btn) {
    btn.addEventListener("click", toggleNavigator);
  }

  const clearBtn = document.getElementById("nav-clear-btn");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      navReset();
      if (state.navActive) {
        updateMapCursor();
        updateNavUI("Кликните точку старта на карте");
      }
    });
  }

  const closeBtn = document.getElementById("nav-close-btn");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      state.navActive = false;
      updateMapCursor();
      navReset();
    });
  }

  const simBtn = document.getElementById("nav-sim-btn");
  if (simBtn) {
    simBtn.addEventListener("click", () => {
      if (state.navSimInterval) {
        stopRouteSimulation();
        clearSimulationMarker();
      } else {
        startRouteSimulation();
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Voice Navigator & Route Simulation Helpers
// ---------------------------------------------------------------------------

let selectedVoice = null;

function loadVoice() {
  if (!window.speechSynthesis) return;
  const voices = window.speechSynthesis.getVoices();
  let ruVoice = voices.find(v => {
    const name = v.name.toLowerCase();
    return v.lang.startsWith("ru") && (name.includes("alisa") || name.includes("alice") || name.includes("yandex"));
  });
  if (!ruVoice) {
    ruVoice = voices.find(v => v.lang.startsWith("ru") && v.name.toLowerCase().includes("google"));
  }
  if (!ruVoice) {
    ruVoice = voices.find(v => v.lang.startsWith("ru"));
  }
  selectedVoice = ruVoice;
}

if (window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = loadVoice;
  loadVoice();
}

function speak(text) {
  if (!window.speechSynthesis) return;
  const isVoiceEnabled = document.getElementById("nav-voice-chk")?.checked !== false;
  if (!isVoiceEnabled) return;

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "ru-RU";

  if (!selectedVoice) loadVoice();
  if (selectedVoice) utterance.voice = selectedVoice;

  utterance.pitch = 1.0;
  utterance.rate = 1.05;
  window.speechSynthesis.speak(utterance);
}

function resetRouteTracking() {
  state.navLastAnnouncedIndex = -1;
  state.navLastAnnouncedPrepIndex = -1;
  state.navAnnouncedRadZones = new Set();
  if (state.navRouteManeuvers) {
    state.navRouteManeuvers.forEach(m => {
      m.announcedPrep = false;
      m.announcedTurn = false;
    });
  }
}

function trackPlayerOnRoute(x, y) {
  if (!state.navRoutePoints || state.navRoutePoints.length === 0) return;

  // 1. Check arrival
  const dest = state.navRoutePoints[state.navRoutePoints.length - 1];
  const distToDest = Math.sqrt((x - dest[0]) ** 2 + (y - dest[1]) ** 2);
  if (distToDest < 25) {
    if (state.navLastAnnouncedIndex !== 9999) {
      state.navLastAnnouncedIndex = 9999;
      speak("Вы приехали!");
      stopRouteSimulation();
      clearSimulationMarker();
    }
    return;
  }

  // 2. Find closest segment
  let minSegDist = Infinity;
  let closestSegIdx = -1;
  for (let i = 0; i < state.navRoutePoints.length - 1; i++) {
    const p1 = state.navRoutePoints[i];
    const p2 = state.navRoutePoints[i + 1];
    const dist = distanceToSegment([x, y], p1, p2);
    if (dist < minSegDist) {
      minSegDist = dist;
      closestSegIdx = i;
    }
  }

  // 3. Off-route warning
  if (minSegDist > 100) {
    if (!state.navSimInterval) {
      if (state.navLastAnnouncedIndex !== -888) {
        state.navLastAnnouncedIndex = -888;
        speak("Вы сошли с маршрута. Перепрокладываю.");
        state.navFrom = { x, y };
        computeRoute();
      }
    }
    return;
  }

  // 4. Maneuvers warnings
  state.navRouteManeuvers.forEach((m) => {
    if (m.index <= closestSegIdx) return;

    let distToManeuver = 0;
    const pNextNode = state.navRoutePoints[closestSegIdx + 1];
    distToManeuver += Math.sqrt((x - pNextNode[0]) ** 2 + (y - pNextNode[1]) ** 2);
    for (let j = closestSegIdx + 1; j < m.index; j++) {
      const p1 = state.navRoutePoints[j];
      const p2 = state.navRoutePoints[j + 1];
      distToManeuver += Math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2);
    }

    if (distToManeuver < 180 && distToManeuver > 80 && !m.announcedPrep) {
      m.announcedPrep = true;
      const meters = Math.round(distToManeuver);
      speak(`Через ${meters} метров ${m.text}`);
    }

    if (distToManeuver < 35 && !m.announcedTurn) {
      m.announcedTurn = true;
      const capitalized = m.text.charAt(0).toUpperCase() + m.text.slice(1);
      speak(capitalized);
    }
  });

  // 5. Check radiation zones ahead
  if (state.radiationData && state.radiationData.zones) {
    if (!state.navAnnouncedRadZones) {
      state.navAnnouncedRadZones = new Set();
    }
    state.radiationData.zones.forEach((zone) => {
      if (state.navAnnouncedRadZones.has(zone.id)) return;

      const distToZone = getDistanceToCircularZoneAlongRoute(x, y, closestSegIdx, zone);
      if (distToZone >= 0 && distToZone <= 300) {
        state.navAnnouncedRadZones.add(zone.id);
        const cleanLabel = zone.label.replace("мЗв/ч", "миллизиверт в час").replace("мкЗв/ч", "микрозиверт в час");
        speak(`Впереди радиация. ${cleanLabel}`);
      }
    });
  }
}

function distanceToSegment(P, A, B) {
  const l2 = (B[0] - A[0]) ** 2 + (B[1] - A[1]) ** 2;
  if (l2 === 0) return Math.sqrt((P[0] - A[0]) ** 2 + (P[1] - A[1]) ** 2);
  let t = ((P[0] - A[0]) * (B[0] - A[0]) + (P[1] - A[1]) * (B[1] - A[1])) / l2;
  t = Math.max(0, Math.min(1, t));
  const projX = A[0] + t * (B[0] - A[0]);
  const projY = A[1] + t * (B[1] - A[1]);
  return Math.sqrt((P[0] - projX) ** 2 + (P[1] - projY) ** 2);
}

function getDistanceToCircularZoneAlongRoute(x, y, closestSegIdx, zone) {
  const cx = zone.x;
  const cy = zone.y;
  const r = zone.radius;

  let accumulatedDist = 0;
  let currentX = x;
  let currentY = y;

  for (let i = closestSegIdx; i < state.navRoutePoints.length - 1; i++) {
    const nextNode = state.navRoutePoints[i + 1];
    const nextX = nextNode[0];
    const nextY = nextNode[1];

    const dx = nextX - currentX;
    const dy = nextY - currentY;
    const len = Math.sqrt(dx * dx + dy * dy);

    if (len === 0) continue;

    const ux = currentX - cx;
    const uy = currentY - cy;

    const a = len * len;
    const b = 2 * (ux * dx + uy * dy);
    const c = ux * ux + uy * uy - r * r;

    if (c < 0) {
      return accumulatedDist;
    }

    const disc = b * b - 4 * a * c;
    if (disc >= 0) {
      const sqrtDisc = Math.sqrt(disc);
      const t1 = (-b - sqrtDisc) / (2 * a);
      const t2 = (-b + sqrtDisc) / (2 * a);

      let t = -1;
      if (t1 >= 0 && t1 <= 1) {
        t = t1;
      } else if (t2 >= 0 && t2 <= 1) {
        t = t2;
      }

      if (t >= 0) {
        return accumulatedDist + t * len;
      }
    }

    accumulatedDist += len;
    currentX = nextX;
    currentY = nextY;
  }

  return -1;
}

function calculateManeuvers(path) {
  const maneuvers = [];
  if (path.length < 3) return maneuvers;

  for (let i = 1; i < path.length - 1; i++) {
    const pPrev = path[i - 1];
    const pCurr = path[i];
    const pNext = path[i + 1];

    const dx1 = pCurr[0] - pPrev[0];
    const dy1 = pCurr[1] - pPrev[1];
    const dx2 = pNext[0] - pCurr[0];
    const dy2 = pNext[1] - pCurr[1];

    const cross = dx1 * dy2 - dy1 * dx2;
    const dot = dx1 * dx2 + dy1 * dy2;
    const angleRad = Math.atan2(cross, dot);
    const angleDeg = angleRad * 180 / Math.PI;

    const absAngle = Math.abs(angleDeg);
    if (absAngle > 20) {
      let turnText = "";
      if (absAngle > 165) {
        turnText = "развернитесь";
      } else if (angleDeg > 0) {
        if (absAngle < 60) turnText = "плавно поверните налево";
        else if (absAngle < 120) turnText = "поверните налево";
        else turnText = "круто поверните налево";
      } else {
        if (absAngle < 60) turnText = "плавно поверните направо";
        else if (absAngle < 120) turnText = "поверните направо";
        else turnText = "круто поверните направо";
      }

      maneuvers.push({
        index: i,
        coord: pCurr,
        angle: angleDeg,
        text: turnText,
        announcedPrep: false,
        announcedTurn: false,
      });
    }
  }
  return maneuvers;
}

function startRouteSimulation() {
  if (!state.navRouteLayer || !state.navRoutePoints || state.navRoutePoints.length < 2) return;
  stopRouteSimulation();

  state.navSimPathIndex = 0;
  state.navSimDistanceCovered = 0;

  const simBtn = document.getElementById("nav-sim-btn");
  if (simBtn) {
    simBtn.innerHTML = "⏹ Остановить симуляцию";
    simBtn.style.backgroundColor = "#c0392b";
  }

  const pStart = state.navRoutePoints[0];
  updateSimulationPos(pStart[0], pStart[1]);

  speak("Маршрут построен. Симуляция движения начата.");

  const speed = 25; // game units per second
  const intervalMs = 200;
  const stepDist = speed * (intervalMs / 1000);

  state.navSimInterval = setInterval(() => {
    if (state.navSimPathIndex >= state.navRoutePoints.length - 1) {
      stopRouteSimulation();
      speak("Вы приехали!");
      return;
    }

    const pCurr = state.navRoutePoints[state.navSimPathIndex];
    const pNext = state.navRoutePoints[state.navSimPathIndex + 1];

    const dx = pNext[0] - pCurr[0];
    const dy = pNext[1] - pCurr[1];
    const segLen = Math.sqrt(dx * dx + dy * dy);

    state.navSimDistanceCovered += stepDist;
    if (state.navSimDistanceCovered >= segLen) {
      state.navSimDistanceCovered = 0;
      state.navSimPathIndex++;
      if (state.navSimPathIndex >= state.navRoutePoints.length - 1) {
        const pFinal = state.navRoutePoints[state.navRoutePoints.length - 1];
        updateSimulationPos(pFinal[0], pFinal[1]);
        stopRouteSimulation();
        speak("Вы приехали!");
        return;
      }
      const pNew = state.navRoutePoints[state.navSimPathIndex];
      updateSimulationPos(pNew[0], pNew[1]);
    } else {
      const ratio = state.navSimDistanceCovered / segLen;
      const x = pCurr[0] + dx * ratio;
      const y = pCurr[1] + dy * ratio;
      updateSimulationPos(x, y);
    }
  }, intervalMs);
}

function stopRouteSimulation() {
  if (state.navSimInterval) {
    clearInterval(state.navSimInterval);
    state.navSimInterval = null;
  }
  const simBtn = document.getElementById("nav-sim-btn");
  if (simBtn) {
    simBtn.innerHTML = "🏃 Симулировать движение";
    simBtn.style.backgroundColor = "";
  }
}

function updateSimulationPos(x, y) {
  trackPlayerOnRoute(x, y);

  if (!state.navSimMarker) {
    const latlng = gameToLatLng(x, y);
    state.navSimMarker = L.marker(latlng, {
      icon: L.divIcon({
        html: `<div style="background:#e0a82e;width:24px;height:24px;border-radius:50%;border:2px solid #fff;display:flex;align-items:center;justify-content:center;color:#000;font-size:14px;box-shadow:0 0 6px #000;font-weight:bold;">🚗</div>`,
        className: "",
        iconAnchor: [12, 12]
      })
    }).addTo(state.map);
  } else {
    state.navSimMarker.setLatLng(gameToLatLng(x, y));
  }

  state.map.panTo(gameToLatLng(x, y), { animate: true, duration: 0.2 });
}

function clearSimulationMarker() {
  if (state.navSimMarker) {
    state.map.removeLayer(state.navSimMarker);
    state.navSimMarker = null;
  }
}

