/** Radiation zone editor — Leaflet map + alignment overlay + draggable circles. */

const RAD_TIERS = [
  { color: "#4caf50", label: "250 мЗв/ч", radius: 900 },
  { color: "#cddc39", label: "280 мЗв/ч", radius: 700 },
  { color: "#ff9800", label: "350 мЗв/ч", radius: 500 },
  { color: "#f44336", label: "530 мЗв/ч", radius: 300 },
];

const DEFAULT_LEGEND = RAD_TIERS.map((t) => ({ color: t.color, label: t.label }));

const radState = {
  map: null,
  tileLayer: null,
  overlayLayer: null,
  config: null,
  zones: [],
  legend: [],
  overlay: null,
  selectedId: null,
  activeTier: 2,
  defaultRadius: 500,
  zoneLayers: new Map(),
  loadedSlug: null,
};

function radMapSize(config) {
  return config?.map_size || 20480;
}

function radGameToLatLng(x, y, config = radState.config) {
  const size = radMapSize(config);
  const ratio = size / 256;
  return L.latLng(y / ratio - 256, x / ratio);
}

function radLatLngToGame(latlng, config = radState.config) {
  const size = radMapSize(config);
  const ratio = size / 256;
  return {
    x: latlng.lng * ratio,
    y: (latlng.lat + 256) * ratio,
  };
}

function radGameRadiusToLeaflet(radius, config = radState.config) {
  return radius / (radMapSize(config) / 256);
}

function radGameBoundsToLatLng(bounds, config = radState.config) {
  const size = radMapSize(config);
  const x1 = bounds?.x1 ?? 0;
  const y1 = bounds?.y1 ?? 0;
  const x2 = bounds?.x2 ?? size;
  const y2 = bounds?.y2 ?? size;
  return L.latLngBounds(
    radGameToLatLng(x1, y2, config),
    radGameToLatLng(x2, y1, config),
  );
}

function radNewZoneId() {
  return `zone-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function radActiveTier() {
  return RAD_TIERS[radState.activeTier] || RAD_TIERS[2];
}

function radSetStatus(text, isError = false) {
  const el = document.getElementById("rad-status");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("error", isError);
  el.classList.toggle("hidden", !text);
}

function radCenterIcon(color) {
  return L.divIcon({
    className: "rad-zone-handle",
    html: `<span style="background:${color}"></span>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

function radClearZoneLayers() {
  radState.zoneLayers.forEach(({ circle, marker }) => {
    radState.map?.removeLayer(circle);
    radState.map?.removeLayer(marker);
  });
  radState.zoneLayers.clear();
}

function radSelectZone(id) {
  radState.selectedId = id;
  document.querySelectorAll(".rad-zone-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === id);
  });
  const zone = radState.zones.find((z) => z.id === id);
  if (zone) {
    document.getElementById("rad-zone-x").value = Math.round(zone.x);
    document.getElementById("rad-zone-y").value = Math.round(zone.y);
    document.getElementById("rad-zone-radius").value = Math.round(zone.radius);
    document.getElementById("rad-zone-label").value = zone.label || "";
    const tierIdx = RAD_TIERS.findIndex((t) => t.color === zone.color);
    if (tierIdx >= 0) radSetActiveTier(tierIdx);
  }
}

function radSetActiveTier(idx) {
  radState.activeTier = idx;
  document.querySelectorAll(".rad-tier-btn").forEach((btn, i) => {
    btn.classList.toggle("active", i === idx);
  });
  const tier = radActiveTier();
  const radiusInput = document.getElementById("rad-default-radius");
  if (radiusInput && !radiusInput.matches(":focus")) {
    radiusInput.value = tier.radius;
    radState.defaultRadius = tier.radius;
  }
}

function radUpsertZoneLayer(zone) {
  const existing = radState.zoneLayers.get(zone.id);
  if (existing) {
    radState.map.removeLayer(existing.circle);
    radState.map.removeLayer(existing.marker);
  }

  const latlng = radGameToLatLng(zone.x, zone.y);
  const circle = L.circle(latlng, {
    radius: radGameRadiusToLeaflet(zone.radius),
    color: zone.color,
    fillColor: zone.color,
    fillOpacity: zone.fillOpacity ?? 0.22,
    opacity: zone.strokeOpacity ?? 0.95,
    weight: zone.weight ?? 2,
  });
  const marker = L.marker(latlng, {
    draggable: true,
    icon: radCenterIcon(zone.color),
    zIndexOffset: 1000,
  });

  const syncFromMarker = () => {
    const pos = radLatLngToGame(marker.getLatLng());
    zone.x = pos.x;
    zone.y = pos.y;
    circle.setLatLng(marker.getLatLng());
    if (radState.selectedId === zone.id) {
      document.getElementById("rad-zone-x").value = Math.round(zone.x);
      document.getElementById("rad-zone-y").value = Math.round(zone.y);
    }
    radRenderZoneList();
  };

  marker.on("drag", syncFromMarker);
  marker.on("dragend", syncFromMarker);
  circle.on("click", (e) => {
    L.DomEvent.stopPropagation(e);
    radSelectZone(zone.id);
  });
  marker.on("click", (e) => {
    L.DomEvent.stopPropagation(e);
    radSelectZone(zone.id);
  });

  circle.addTo(radState.map);
  marker.addTo(radState.map);
  radState.zoneLayers.set(zone.id, { circle, marker });
}

function radRenderAllZones() {
  radClearZoneLayers();
  radState.zones.forEach((z) => radUpsertZoneLayer(z));
  radRenderZoneList();
}

function radRenderZoneList() {
  const list = document.getElementById("rad-zones-list");
  const count = document.getElementById("rad-zones-count");
  if (!list) return;
  if (count) count.textContent = String(radState.zones.length);

  if (!radState.zones.length) {
    list.innerHTML = "<p class='muted'>Кликните по карте, чтобы добавить зону</p>";
    return;
  }

  list.innerHTML = radState.zones
    .map((z, i) => `
      <button type="button" class="rad-zone-item ${z.id === radState.selectedId ? "active" : ""}" data-id="${escapeHtml(z.id)}">
        <span class="rad-zone-swatch" style="background:${escapeHtml(z.color)}"></span>
        <span class="rad-zone-meta">#${i + 1} · ${Math.round(z.x)} / ${Math.round(z.y)} · r=${Math.round(z.radius)}</span>
        <span class="rad-zone-del" data-del="${escapeHtml(z.id)}" title="Удалить">×</span>
      </button>
    `)
    .join("");
}

function radAddZone(x, y) {
  const tier = radActiveTier();
  const radius = Number(document.getElementById("rad-default-radius")?.value) || radState.defaultRadius || tier.radius;
  const zone = {
    id: radNewZoneId(),
    label: tier.label,
    x,
    y,
    radius,
    color: tier.color,
    fillOpacity: 0.22,
    strokeOpacity: 0.95,
    weight: 2,
  };
  radState.zones.push(zone);
  radUpsertZoneLayer(zone);
  radSelectZone(zone.id);
  radRenderZoneList();
}

function radDeleteZone(id) {
  const layer = radState.zoneLayers.get(id);
  if (layer) {
    radState.map?.removeLayer(layer.circle);
    radState.map?.removeLayer(layer.marker);
    radState.zoneLayers.delete(id);
  }
  radState.zones = radState.zones.filter((z) => z.id !== id);
  if (radState.selectedId === id) radState.selectedId = null;
  radRenderZoneList();
}

function radApplySelectedFields() {
  const id = radState.selectedId;
  if (!id) return;
  const zone = radState.zones.find((z) => z.id === id);
  if (!zone) return;
  zone.x = Number(document.getElementById("rad-zone-x").value);
  zone.y = Number(document.getElementById("rad-zone-y").value);
  zone.radius = Number(document.getElementById("rad-zone-radius").value);
  zone.label = document.getElementById("rad-zone-label").value || zone.label;
  const tier = radActiveTier();
  zone.color = tier.color;
  radUpsertZoneLayer(zone);
  radRenderZoneList();
}

function radSyncOverlayLayer() {
  if (radState.overlayLayer) {
    radState.map?.removeLayer(radState.overlayLayer);
    radState.overlayLayer = null;
  }
  if (!radState.map || !radState.overlay?.url) return;

  const b = radState.overlay.bounds || {};
  const bounds = radGameBoundsToLatLng(b);
  radState.overlayLayer = L.imageOverlay(radState.overlay.url, bounds, {
    opacity: radState.overlay.opacity ?? 0.65,
    interactive: false,
  });
  radState.overlayLayer.addTo(radState.map);
}

function radFillBoundsInputs() {
  const b = radState.overlay?.bounds || {
    x1: 0,
    y1: 0,
    x2: radMapSize(radState.config),
    y2: radMapSize(radState.config),
  };
  document.getElementById("rad-bounds-x1").value = Math.round(b.x1 ?? 0);
  document.getElementById("rad-bounds-y1").value = Math.round(b.y1 ?? 0);
  document.getElementById("rad-bounds-x2").value = Math.round(b.x2 ?? radMapSize(radState.config));
  document.getElementById("rad-bounds-y2").value = Math.round(b.y2 ?? radMapSize(radState.config));
  const op = document.getElementById("rad-overlay-opacity");
  if (op) op.value = String(radState.overlay?.opacity ?? 0.65);
  const hint = document.getElementById("rad-overlay-name");
  if (hint) {
    hint.textContent = radState.overlay?.url ? radState.overlay.url.split("/").pop() : "нет подложки";
  }
}

function radReadBoundsFromInputs() {
  if (!radState.overlay) {
    radState.overlay = { url: "", opacity: 0.65, bounds: {}, editorOnly: true };
  }
  radState.overlay.bounds = {
    x1: Number(document.getElementById("rad-bounds-x1").value),
    y1: Number(document.getElementById("rad-bounds-y1").value),
    x2: Number(document.getElementById("rad-bounds-x2").value),
    y2: Number(document.getElementById("rad-bounds-y2").value),
  };
  radState.overlay.opacity = Number(document.getElementById("rad-overlay-opacity").value);
}

function radEnsureMap() {
  if (radState.map) return;

  const size = radMapSize(radState.config);
  radState.map = L.map("radiation-map", {
    crs: L.CRS.Simple,
    minZoom: -3,
    maxZoom: (radState.config.max_native_zoom || 7) + (radState.config.extra_zoom || 3),
    zoomControl: true,
    attributionControl: false,
  });

  const center = radGameToLatLng(size / 2, size / 2);
  radState.map.setView(center, 0);

  radState.tileLayer = L.tileLayer(radState.config.tiles_satellite, {
    maxNativeZoom: radState.config.max_native_zoom || 7,
    maxZoom: (radState.config.max_native_zoom || 7) + (radState.config.extra_zoom || 3),
    noWrap: true,
    bounds: radGameBoundsToLatLng({ x1: 0, y1: 0, x2: size, y2: size }),
  }).addTo(radState.map);

  radState.map.on("click", (e) => {
    const { x, y } = radLatLngToGame(e.latlng);
    radAddZone(x, y);
  });

  setTimeout(() => radState.map.invalidateSize(), 120);
}

function radDestroyMap() {
  if (!radState.map) return;
  radClearZoneLayers();
  if (radState.overlayLayer) radState.map.removeLayer(radState.overlayLayer);
  if (radState.tileLayer) radState.map.removeLayer(radState.tileLayer);
  radState.map.remove();
  radState.map = null;
  radState.tileLayer = null;
  radState.overlayLayer = null;
}

async function radLoadForSlug(slug) {
  if (!slug) return;
  radSetStatus("Загрузка…");
  try {
    const data = await api(`/api/admin/radiation?map_slug=${encodeURIComponent(slug)}`);
    radDestroyMap();

    radState.config = {
      map_size: data.map_size,
      tiles_satellite: data.tiles_satellite,
      max_native_zoom: data.max_native_zoom,
      extra_zoom: data.extra_zoom,
    };
    radState.zones = (data.zones || []).map((z) => ({ ...z }));
    radState.legend = data.legend?.length ? data.legend : DEFAULT_LEGEND;
    radState.overlay = data.overlay || null;
    radState.loadedSlug = slug;
    radState.selectedId = null;

    radEnsureMap();
    radRenderAllZones();
    radFillBoundsInputs();
    radSyncOverlayLayer();
    radSetStatus(`Зон: ${radState.zones.length}`);
  } catch (err) {
    radSetStatus(err.message, true);
  }
}

async function radSave() {
  const slug = document.getElementById("rad-map-select")?.value;
  if (!slug) return;
  radReadBoundsFromInputs();
  radSetStatus("Сохранение…");
  try {
    const payload = {
      map_slug: slug,
      zones: radState.zones,
      legend: radState.legend?.length ? radState.legend : DEFAULT_LEGEND,
      overlay: radState.overlay?.url
        ? {
            url: radState.overlay.url,
            opacity: radState.overlay.opacity ?? 0.65,
            bounds: radState.overlay.bounds,
            editorOnly: true,
          }
        : null,
    };
    const res = await api("/api/admin/radiation", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    radSetStatus(`Сохранено: ${res.zones} зон`);
  } catch (err) {
    radSetStatus(err.message, true);
  }
}

async function radUploadOverlay(file) {
  const slug = document.getElementById("rad-map-select")?.value;
  if (!slug || !file) return;
  radSetStatus("Загрузка подложки…");
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/api/admin/radiation/overlay?map_slug=${encodeURIComponent(slug)}`, {
    method: "POST",
    credentials: "same-origin",
    body: fd,
  });
  const data = res.ok ? await res.json().catch(() => ({})) : null;
  if (!res.ok) {
    const msg = data?.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  radState.overlay = {
    url: data.url,
    opacity: data.opacity ?? 0.65,
    bounds: data.bounds,
    editorOnly: true,
  };
  radFillBoundsInputs();
  radSyncOverlayLayer();
  radSetStatus("Подложка загружена");
}

async function radDeleteOverlay() {
  const slug = document.getElementById("rad-map-select")?.value;
  if (!slug) return;
  if (!confirm("Удалить подложку для выравнивания?")) return;
  await api(`/api/admin/radiation/overlay?map_slug=${encodeURIComponent(slug)}`, { method: "DELETE" });
  radState.overlay = null;
  radFillBoundsInputs();
  radSyncOverlayLayer();
  radSetStatus("Подложка удалена");
}

function radInitTierButtons() {
  const wrap = document.getElementById("rad-tier-buttons");
  if (!wrap || wrap.childElementCount) return;
  wrap.innerHTML = RAD_TIERS.map(
    (t, i) => `
      <button type="button" class="rad-tier-btn ${i === radState.activeTier ? "active" : ""}" data-tier="${i}" style="--tier-color:${t.color}">
        <span class="rad-tier-dot"></span>${t.label}
      </button>
    `,
  ).join("");
  wrap.addEventListener("click", (e) => {
    const btn = e.target.closest(".rad-tier-btn");
    if (!btn) return;
    radSetActiveTier(Number(btn.dataset.tier));
    if (radState.selectedId) radApplySelectedFields();
  });
}

function radBindUi() {
  if (document.getElementById("rad-ui-bound")) return;
  document.getElementById("rad-ui-bound").value = "1";

  radInitTierButtons();

  document.getElementById("rad-map-select")?.addEventListener("change", (e) => {
    radLoadForSlug(e.target.value);
  });

  document.getElementById("rad-save-btn")?.addEventListener("click", () => {
    radSave().catch((err) => radSetStatus(err.message, true));
  });

  document.getElementById("rad-overlay-file")?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    radUploadOverlay(file).catch((err) => radSetStatus(err.message, true));
    e.target.value = "";
  });

  document.getElementById("rad-overlay-delete")?.addEventListener("click", () => {
    radDeleteOverlay().catch((err) => radSetStatus(err.message, true));
  });

  document.getElementById("rad-apply-bounds")?.addEventListener("click", () => {
    radReadBoundsFromInputs();
    radSyncOverlayLayer();
  });

  document.getElementById("rad-overlay-opacity")?.addEventListener("input", () => {
    radReadBoundsFromInputs();
    if (radState.overlayLayer) {
      radState.overlayLayer.setOpacity(radState.overlay.opacity);
    }
  });

  document.getElementById("rad-apply-zone")?.addEventListener("click", radApplySelectedFields);
  document.getElementById("rad-delete-zone")?.addEventListener("click", () => {
    if (radState.selectedId) radDeleteZone(radState.selectedId);
  });

  document.getElementById("rad-default-radius")?.addEventListener("change", (e) => {
    radState.defaultRadius = Number(e.target.value) || 500;
  });

  ["rad-zone-x", "rad-zone-y", "rad-zone-radius"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", radApplySelectedFields);
  });

  document.getElementById("rad-zones-list")?.addEventListener("click", (e) => {
    const del = e.target.closest("[data-del]");
    if (del) {
      e.stopPropagation();
      radDeleteZone(del.dataset.del);
      return;
    }
    const item = e.target.closest(".rad-zone-item");
    if (item) radSelectZone(item.dataset.id);
  });
}

const RadiationEditor = {
  ensureLoaded() {
    radBindUi();
    const sel = document.getElementById("rad-map-select");
    if (!sel?.value && typeof mapsCache !== "undefined" && mapsCache.length) {
      sel.value = mapsCache[0].slug;
    }
    const slug = sel?.value;
    if (slug && slug !== radState.loadedSlug) {
      radLoadForSlug(slug);
    } else if (radState.map) {
      setTimeout(() => radState.map.invalidateSize(), 120);
    }
  },
  refreshMapSelect() {
    const sel = document.getElementById("rad-map-select");
    if (!sel || typeof mapsCache === "undefined") return;
    const prev = sel.value;
    sel.innerHTML = mapsCache.map((m) => `<option value="${m.slug}">${escapeHtml(m.name)}</option>`).join("");
    if (prev && mapsCache.some((m) => m.slug === prev)) sel.value = prev;
  },
};

window.RadiationEditor = RadiationEditor;
