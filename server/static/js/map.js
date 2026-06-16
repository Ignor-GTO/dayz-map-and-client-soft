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
  ws: null,
};

const TILE_BOUNDS = L.latLngBounds(L.latLng(0, 0), L.latLng(-256, 256));
const MAP_MAX_BOUNDS = L.latLngBounds(L.latLng(100, -100), L.latLng(-356, 356));

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

function initLeaflet(config) {
  const maxNative = config.max_native_zoom || 7;
  const maxZoom = maxNative + (config.extra_zoom || 3);

  state.map = L.map("map", {
    crs: L.CRS.Simple,
    minZoom: 0,
    maxZoom,
    maxBounds: MAP_MAX_BOUNDS,
    maxBoundsViscosity: 0.8,
    zoomControl: true,
    attributionControl: true,
  });

  setTileLayer("satellite");
  state.map.fitBounds(TILE_BOUNDS);

  const center = gameToLatLng(mapSize(config) / 2, mapSize(config) / 2, config);
  state.map.setView(center, 3);
}

function upsertLive(pos) {
  const latlng = gameToLatLng(pos.x, pos.y);
  const color = colorForUser(pos.user_id);
  let marker = state.liveMarkers.get(pos.user_id);

  const popup = `<b>${pos.nickname}</b><br>Live: ${Math.round(pos.x)} / ${Math.round(pos.y)}`;

  if (marker) {
    marker.setLatLng(latlng);
    marker.setPopupContent(popup);
  } else {
    marker = L.circleMarker(latlng, {
      radius: 10,
      color: "#fff",
      weight: 2,
      fillColor: color,
      fillOpacity: 0.9,
    }).addTo(state.map);
    marker.bindPopup(popup);
    state.liveMarkers.set(pos.user_id, marker);
  }
  updatePlayersList();
}

function upsertPin(m) {
  const latlng = gameToLatLng(m.x, m.y);
  const color = colorForUser(m.user_id);
  let marker = state.pinMarkers.get(m.id);

  const isMine = state.me && m.user_id === state.me.user_id;
  const popupHtml = `
    <b>${m.nickname}</b> — метка<br>
    ${Math.round(m.x)} / ${Math.round(m.y)}
    ${isMine ? `<br><button class="marker-delete" data-id="${m.id}">Удалить</button>` : ""}
  `;

  if (marker) {
    marker.setLatLng(latlng);
    marker.setPopupContent(popupHtml);
  } else {
    marker = L.marker(latlng, {
      icon: L.divIcon({
        className: "pin-icon",
        html: `<div style="background:${color};width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 4px #000"></div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      }),
    }).addTo(state.map);
    marker.bindPopup(popupHtml);
    marker.on("popupopen", () => {
      const btn = document.querySelector(".marker-delete");
      if (btn) {
        btn.onclick = () => deleteMarker(Number(btn.dataset.id));
      }
    });
    state.pinMarkers.set(m.id, marker);
  }
}

function upsertPoi(p) {
  const latlng = gameToLatLng(p.x, p.y);
  let marker = state.poiMarkers.get(p.id);
  const desc = p.description ? `<br>${p.description}` : "";
  const popup = `<b>${p.title}</b>${desc}<br>${Math.round(p.x)} / ${Math.round(p.y)}`;

  if (marker) {
    marker.setLatLng(latlng);
    marker.setPopupContent(popup);
  } else {
    marker = L.marker(latlng, {
      icon: L.divIcon({
        className: "poi-icon",
        html: `<div class="poi-marker">★</div>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      }),
    }).addTo(state.map);
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
  const el = document.getElementById("players-list");
  const entries = [];
  state.liveMarkers.forEach((marker) => {
    const content = marker.getPopup()?.getContent() || "";
    const match = content.match(/^<b>(.+?)<\/b>/);
    if (match) entries.push(match[1]);
  });
  el.innerHTML = entries.length
    ? entries.map((n) => `<div class="player-row">● ${n}</div>`).join("")
    : "<div class='player-row'>Никого онлайн на карте</div>";
}

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
  data.positions.forEach(upsertLive);
  data.markers.forEach(upsertPin);
  data.pois.forEach(upsertPoi);
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
  await loadRoomState();
  connectWebSocket();
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

window.addEventListener("resize", () => {
  if (state.map) state.map.invalidateSize({ animate: false });
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
