const state = {
  map: null,
  tileLayer: null,
  layerType: "satellite",
  config: null,
  me: null,
  clientKey: null,
  liveMarkers: new Map(),
  pinMarkers: new Map(),
  poiMarkers: new Map(),
  locationLayer: null,
  locationEntries: [],
  radiationLayer: null,
  radiationOverlay: null,
  // Roads & Navigator
  roadLayer: null,          // L.layerGroup for road polylines
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
  navLastAnnouncedIndex: -1,
  navLastAnnouncedPrepIndex: -1,
  filters: {
    labels: true,
    cities: true,
    military: true,
    local: true,
    water: true,
    terrain: true,
    players: true,
    markers: true,
    poi: true,
    radiation: true,
    roads: true,
  },
  ws: null,
};


const TILE_BOUNDS = L.latLngBounds(L.latLng(0, 0), L.latLng(-256, 256));
const MAP_MAX_BOUNDS = TILE_BOUNDS;

function updateMinZoom() {
  if (!state.map) return;
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
  state.map.fitBounds(TILE_BOUNDS, { animate: false });
  if (state.config) {
    const center = gameToLatLng(mapSize(state.config) / 2, mapSize(state.config) / 2, state.config);
    state.map.setView(center, state.map.getZoom(), { animate: false });
  }
}

function showKeyModal(key) {
  state.clientKey = key;
  document.getElementById("client-key-display").textContent = key;
  document.getElementById("key-modal").classList.remove("hidden");
}

function mapSize(config) {
  return config.map_size || config.bounds.max_x || 20480;
}

function gameToLatLng(x, y, config = state.config) {
  const size = mapSize(config);
  const ratio = size / 256;
  return L.latLng(y / ratio - 256, x / ratio);
}

function gameBoundsToLatLng(bounds, config = state.config) {
  const x1 = bounds.x1 ?? 0;
  const y1 = bounds.y1 ?? 0;
  const x2 = bounds.x2 ?? mapSize(config);
  const y2 = bounds.y2 ?? mapSize(config);
  return L.latLngBounds(
    gameToLatLng(x1, y2, config),
    gameToLatLng(x2, y1, config),
  );
}

function gameRadiusToLeaflet(radius, config = state.config) {
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
  const maxZoom = maxNative + (state.config.extra_zoom || 3);

  if (state.tileLayer) state.map.removeLayer(state.tileLayer);

  state.tileLayer = L.tileLayer(url, {
    tileSize: 256,
    noWrap: true,
    minZoom: 0,
    maxNativeZoom: maxNative,
    maxZoom,
    bounds: TILE_BOUNDS,
    attribution: state.config.attribution || "Tiles © Xam.nu",
  }).addTo(state.map);

  document.getElementById("btn-layer-sat")?.classList.toggle("active", type === "satellite");
  document.getElementById("btn-layer-topo")?.classList.toggle("active", type === "topographic");
}

function initMapPanes(map) {
  if (!map.getPane("radiationPane")) {
    map.createPane("radiationPane");
    map.getPane("radiationPane").style.zIndex = 340;
  }
  if (!map.getPane("labelsPane")) {
    map.createPane("labelsPane");
    map.getPane("labelsPane").style.zIndex = 480;
  }
}

function initLeaflet(config) {
  const maxNative = config.max_native_zoom || 7;
  const maxZoom = maxNative + (config.extra_zoom || 3);

  state.map = L.map("map", {
    crs: L.CRS.Simple,
    minZoom: 0,
    maxZoom,
    maxBounds: MAP_MAX_BOUNDS,
    maxBoundsViscosity: 1.0,
    zoomControl: true,
    attributionControl: true,
  });

  initMapPanes(state.map);
  state.locationLayer = L.layerGroup().addTo(state.map);
  state.radiationLayer = L.layerGroup().addTo(state.map);
  state.roadLayer = L.layerGroup().addTo(state.map);
  state.map.on("zoomend", updateLocationVisibility);

  // Navigator: intercept map clicks when nav mode is active
  state.map.on("click", (e) => {
    if (!state.navActive) return;
    const gameCoords = latLngToGame(e.latlng);
    navSetPoint(gameCoords.x, gameCoords.y);
  });

  setTileLayer("satellite");
  state.map.fitBounds(TILE_BOUNDS);

  const center = gameToLatLng(mapSize(config) / 2, mapSize(config) / 2, config);
  state.map.setView(center, 3);

}

function upsertLive(pos) {
  if (!state.filters.players) return;
  const latlng = gameToLatLng(pos.x, pos.y);
  const color = colorForUser(pos.user_id);
  let marker = state.liveMarkers.get(pos.user_id);

  const popup = `<b>${pos.nickname}</b><br>Live: ${Math.round(pos.x)} / ${Math.round(pos.y)}`;

  const iconHtml = `
    <div style="display:flex;align-items:center;white-space:nowrap;filter:drop-shadow(0 0 3px rgba(0,0,0,0.8));">
      <div style="background:${color};width:24px;height:24px;border-radius:50%;border:2px solid #fff;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;box-shadow:0 0 4px #000;">
        👤
      </div>
      <div style="margin-left:5px;background:rgba(0,0,0,0.75);color:#fff;font-family:sans-serif;font-size:11px;font-weight:bold;padding:2px 6px;border-radius:4px;border:1px solid rgba(255,255,255,0.25);">
        ${pos.nickname}
      </div>
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

function upsertPin(m) {
  if (!state.filters.markers) return;
  const latlng = gameToLatLng(m.x, m.y);
  const color = colorForUser(m.user_id);
  let marker = state.pinMarkers.get(m.id);

  const isMine = state.me && m.user_id === state.me.user_id;
  const popupHtml = `
    <b>${m.nickname}</b> — метка<br>
    ${Math.round(m.x)} / ${Math.round(m.y)}
    ${isMine ? `<br><button class="marker-delete" data-id="${m.id}">Удалить</button>` : ""}
  `;

  let iconHtml = "";
  let size = [14, 14];
  let anchor = [7, 7];

  if (m.type === "screenshot") {
    iconHtml = `<div style="background:${color};width:20px;height:20px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 4px #000;display:flex;align-items:center;justify-content:center;color:#f1c40f;font-weight:bold;font-size:14px;font-family:sans-serif;line-height:20px;">?</div>`;
    size = [20, 20];
    anchor = [10, 10];
  } else {
    iconHtml = `
      <div style="width:24px;height:24px;position:relative;display:flex;align-items:center;justify-content:center;filter:drop-shadow(0 0 3px rgba(0,0,0,0.95));">
        <div style="position:absolute;width:24px;height:3px;background:#ff2e44;border:0.75px solid #fff;"></div>
        <div style="position:absolute;width:3px;height:24px;background:#ff2e44;border:0.75px solid #fff;"></div>
        <div style="width:10px;height:10px;border-radius:50%;border:2.5px solid #ff2e44;background:#fff;z-index:2;box-shadow:0 0 2px #000;"></div>
      </div>
    `;
    size = [24, 24];
    anchor = [12, 12];
  }

  const icon = L.divIcon({
    className: m.type === "screenshot" ? "pin-icon-screenshot" : "pin-icon-crosshair",
    html: iconHtml,
    iconSize: size,
    iconAnchor: anchor,
  });

  if (marker) {
    marker.setLatLng(latlng);
    marker.setIcon(icon);
    marker.setPopupContent(popupHtml);
    marker._markerMeta = m;
  } else {
    marker = L.marker(latlng, { icon }).addTo(state.map);
    marker.bindPopup(popupHtml);
    marker._markerMeta = m;
    marker.on("popupopen", () => {
      const btn = document.querySelector(".marker-delete");
      if (btn) {
        btn.onclick = () => deleteMarker(Number(btn.dataset.id));
      }
    });
    state.pinMarkers.set(m.id, marker);
  }

  if (isMine && state.map) {
    state.map.panTo(latlng, { animate: true, duration: 0.6 });
  }
  updateMarkersList();
}

function upsertPoi(p) {
  if (!state.filters.poi) return;
  const latlng = gameToLatLng(p.x, p.y);
  let marker = state.poiMarkers.get(p.id);
  const popup = poiPopupHtml(p);
  const icon = L.divIcon({
    className: "poi-map-pin",
    html: poiLabelHtml(p.icon || "star", p.title),
    iconSize: [240, 24],
    iconAnchor: [11, 12],
  });

  if (marker) {
    marker.setLatLng(latlng);
    marker.setIcon(icon);
    marker.setPopupContent(popup);
  } else {
    marker = L.marker(latlng, { icon }).addTo(state.map);
    marker.bindPopup(popup);
    state.poiMarkers.set(p.id, marker);
  }
}

function removePin(id) {
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
          <span class="sidebar-dot" style="background: ${color}"></span>
          <span class="sidebar-name" title="${pos.nickname}">${nameLabel}</span>
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
  const el = document.getElementById("web-markers-list");
  if (!el) return;
  
  const rows = [];
  state.pinMarkers.forEach((marker) => {
    const m = marker._markerMeta;
    if (!m) return;
    
    const isMine = state.me && m.user_id === state.me.user_id;
    const typeLabel = m.type === "screenshot" ? "📷 Снимок" : "📍 Метка";
    const label = `${m.nickname}: ${typeLabel}`;
    
    rows.push(`
      <div class="sidebar-row" onclick="focusOnMarker('${m.id}')">
        <div class="sidebar-row-left">
          <span class="sidebar-dot" style="background: ${colorForUser(m.user_id)}"></span>
          <span class="sidebar-name" title="${label}">${label}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 4px;">
          <span class="sidebar-info" style="margin-right: 4px;">${Math.round(m.x)}/${Math.round(m.y)}</span>
          ${isMine ? `<button class="delete-btn-small" onclick="event.stopPropagation(); deleteMarker('${m.id}')" title="Удалить">✕</button>` : ""}
        </div>
      </div>
    `);
  });
  
  el.innerHTML = rows.length
    ? rows.join("")
    : `<div class="list-empty">Нет меток</div>`;
}

function focusOnPlayer(userId) {
  if (!state.map) return;
  const marker = state.liveMarkers.get(userId);
  if (marker) {
    state.map.setView(marker.getLatLng(), Math.max(state.map.getZoom(), 5), { animate: true });
    marker.openPopup();
  }
}

function focusOnMarker(markerId) {
  if (!state.map) return;
  let marker = state.pinMarkers.get(markerId) || state.pinMarkers.get(Number(markerId));
  if (marker) {
    state.map.setView(marker.getLatLng(), Math.max(state.map.getZoom(), 5), { animate: true });
    marker.openPopup();
  }
}

// Expose functions globally for inline HTML event handlers
window.focusOnPlayer = focusOnPlayer;
window.focusOnMarker = focusOnMarker;
window.deleteMarker = deleteMarker;

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${proto}://${location.host}/ws/map`);

  state.ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "position") upsertLive(msg.data);
    if (msg.type === "marker_added") upsertPin(msg.data);
    if (msg.type === "marker_deleted") removePin(msg.data.id);
  };

  state.ws.onclose = () => {
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
}

function renderRadiationLayer(data) {
  if (!state.map || !state.radiationLayer) return;
  clearRadiationLayers();

  if (!state.filters.radiation) {
    applyRadiationVisibility();
    renderRadiationLegend(data?.legend || []);
    return;
  }

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
    if (zone.label) {
      circle.bindTooltip(zone.label, { permanent: false, direction: "top" });
    }
    state.radiationLayer.addLayer(circle);
  });

  applyRadiationVisibility();
  renderRadiationLegend(data?.legend || []);
}

function applyRadiationVisibility() {
  if (!state.radiationLayer || !state.map) return;
  if (state.filters.radiation) {
    if (!state.map.hasLayer(state.radiationLayer)) {
      state.radiationLayer.addTo(state.map);
    }
  } else {
    state.map.removeLayer(state.radiationLayer);
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
    { id: "poi", label: "Метки сервера" },
    { id: "radiation", label: "Радиационные зоны" },
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
      applyLocationFilters();
      refreshDynamicLayers();
      applyRadiationVisibility();
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
    if (state.filters.markers) m.addTo(state.map);
    else state.map.removeLayer(m);
  });
  state.poiMarkers.forEach((m) => {
    if (state.filters.poi) m.addTo(state.map);
    else state.map.removeLayer(m);
  });
  applyRadiationVisibility();
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

  document.getElementById("user-label").textContent = state.me.nickname;
  document.getElementById("room-label").textContent = `${state.me.map_name} · PIN: ${state.me.pin}`;
  await Promise.all([loadRoomState(), loadMapLocations(), loadMapRadiation(), loadRoads()]);
  connectWebSocket();
  initNavigatorButton();
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

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("login-error");
  errEl.classList.add("hidden");
  try {
    const map_slug = document.getElementById("map-slug").value;
    const pin = document.getElementById("pin").value.trim();
    const nickname = document.getElementById("nickname").value.trim();
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ map_slug, pin, nickname }),
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

document.getElementById("logout-btn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  state.liveMarkers.clear();
  state.pinMarkers.clear();
  state.poiMarkers.clear();
  state.locationEntries = [];
  if (state.locationLayer) state.locationLayer.clearLayers();
  clearRadiationLayers();
  showLogin();
});

document.getElementById("reset-key-btn").addEventListener("click", async () => {
  if (!confirm("Старый ключ перестанет работать. Создать новый?")) return;
  try {
    const data = await api("/api/auth/reset-key", { method: "POST" });
    showKeyModal(data.client_key);
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("copy-key-btn").addEventListener("click", () => {
  if (state.clientKey) showKeyModal(state.clientKey);
  else alert("Ключ доступен только после входа. Войдите заново для нового ключа.");
});

document.getElementById("copy-key-confirm").addEventListener("click", () => {
  if (state.clientKey) navigator.clipboard.writeText(state.clientKey);
});

document.getElementById("close-key-modal").addEventListener("click", () => {
  document.getElementById("key-modal").classList.add("hidden");
});

document.getElementById("btn-layer-sat")?.addEventListener("click", () => setTileLayer("satellite"));
document.getElementById("btn-layer-topo")?.addEventListener("click", () => setTileLayer("topographic"));

document.getElementById("btn-focus-me")?.addEventListener("click", () => {
  if (!state.map || !state.me) return;
  const marker = state.liveMarkers.get(state.me.user_id);
  if (marker) {
    state.map.setView(marker.getLatLng(), Math.max(state.map.getZoom(), 5), { animate: true });
  } else {
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
      state.map.setView(fallbackLatLng, Math.max(state.map.getZoom(), 5), { animate: true });
    }
  }
});

document.addEventListener("keydown", (e) => {
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
  applyRoadsVisibility();
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
  highway: "#c084fc",
  road: "#c0c0c0",
  street: "#4fc3f7",
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
//  NAVIGATOR
// ============================================================

/** Convert Leaflet LatLng → game {x, y} (inverse of gameToLatLng) */
function latLngToGame(latlng) {
  if (!state.config) return { x: 0, y: 0 };
  const size = mapSize(state.config);
  const ratio = size / 256;
  // gameToLatLng: lat = y/ratio - 256, lng = x/ratio
  // so: x = lng * ratio, y = (lat + 256) * ratio
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
  if (state.navToMarker)   { state.map.removeLayer(state.navToMarker);   state.navToMarker = null; }
}

function navReset() {
  state.navFrom = null;
  state.navTo = null;
  state.navStep = "from";
  navClearMarkers();
  navClearRoute();
  stopRouteSimulation();
  clearSimulationMarker();
  updateNavUI();
}

function navSetPoint(x, y) {
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
    state.navStep = "from"; // allow re-routing by clicking again from
    updateNavUI("Прокладываю маршрут…");
    computeRoute();
  }
}

async function computeRoute() {
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
    state.map.getContainer().style.cursor = "crosshair";
    updateNavUI();
  } else {
    state.map.getContainer().style.cursor = "";
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
        state.map.getContainer().style.cursor = "crosshair";
        updateNavUI("Кликните точку старта на карте");
      }
    });
  }

  const closeBtn = document.getElementById("nav-close-btn");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      state.navActive = false;
      state.map.getContainer().style.cursor = "";
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
  const distToDest = Math.sqrt((x - dest[0])**2 + (y - dest[1])**2);
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
    distToManeuver += Math.sqrt((x - pNextNode[0])**2 + (y - pNextNode[1])**2);
    for (let j = closestSegIdx + 1; j < m.index; j++) {
      const p1 = state.navRoutePoints[j];
      const p2 = state.navRoutePoints[j + 1];
      distToManeuver += Math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2);
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
}

function distanceToSegment(P, A, B) {
  const l2 = (B[0] - A[0])**2 + (B[1] - A[1])**2;
  if (l2 === 0) return Math.sqrt((P[0] - A[0])**2 + (P[1] - A[1])**2);
  let t = ((P[0] - A[0]) * (B[0] - A[0]) + (P[1] - A[1]) * (B[1] - A[1])) / l2;
  t = Math.max(0, Math.min(1, t));
  const projX = A[0] + t * (B[0] - A[0]);
  const projY = A[1] + t * (B[1] - A[1]);
  return Math.sqrt((P[0] - projX)**2 + (P[1] - projY)**2);
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

