/** Radiation zone editor — full-page Leaflet + overlay alignment + draggable circles. */

const RAD_DEFAULT_TIERS = [
  { id: "t-green", color: "#4caf50", label: "250 мЗв/ч", radius: 900 },
  { id: "t-yellow", color: "#cddc39", label: "280 мЗв/ч", radius: 700 },
  { id: "t-orange", color: "#ff9800", label: "350 мЗв/ч", radius: 500 },
  { id: "t-red", color: "#f44336", label: "530 мЗв/ч", radius: 300 },
];

const radState = {
  map: null,
  tileLayer: null,
  overlayLayer: null,
  config: null,
  zones: [],
  tiers: [],
  legend: [],
  overlay: null,
  selectedId: null,
  activeTierId: "t-orange",
  defaultRadius: 500,
  zoneLayers: new Map(),
  loadedSlug: null,
  addZoneMode: false,
  overlayHandles: [],
};

function radApplySatelliteVisibility() {
  const hide = document.getElementById("rad-hide-satellite")?.checked;
  if (!radState.map || !radState.tileLayer) return;
  if (hide) {
    if (radState.map.hasLayer(radState.tileLayer)) {
      radState.map.removeLayer(radState.tileLayer);
    }
  } else {
    if (!radState.map.hasLayer(radState.tileLayer)) {
      radState.tileLayer.addTo(radState.map);
    }
  }
}

function radDefaultLegend() {
  return radState.tiers.map((t) => ({ color: t.color, label: t.label }));
}

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
  return { x: latlng.lng * ratio, y: (latlng.lat + 256) * ratio };
}

function radGameRadiusToLeaflet(radius, config = radState.config) {
  return radius / (radMapSize(config) / 256);
}

function radGameBoundsToLatLng(bounds, config = radState.config) {
  const size = radMapSize(config);
  return L.latLngBounds(
    radGameToLatLng(bounds?.x1 ?? 0, bounds?.y2 ?? size, config),
    radGameToLatLng(bounds?.x2 ?? size, bounds?.y1 ?? 0, config),
  );
}

function radNewZoneId() {
  return `zone-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function radActiveTier() {
  return radState.tiers.find((t) => t.id === radState.activeTierId) || radState.tiers[0] || RAD_DEFAULT_TIERS[2];
}

function radOverlaySrc(url) {
  if (!url) return "";
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}t=${Date.now()}`;
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

function radBringZonesToFront() {
  radState.zoneLayers.forEach(({ circle, marker }) => {
    circle.bringToFront();
    marker.setZIndexOffset(2000);
  });
}

function radEnsureTiers() {
  if (!radState.tiers.length) {
    radState.tiers = RAD_DEFAULT_TIERS.map((t) => ({ ...t }));
  }
  if (!radState.tiers.some((t) => t.id === radState.activeTierId)) {
    radState.activeTierId = radState.tiers[2]?.id || radState.tiers[0]?.id || "t-orange";
  }
}

function radRenderTierSelect() {
  radEnsureTiers();
  const sel = document.getElementById("rad-tier-select");
  if (!sel) return;
  const prev = radState.activeTierId;
  sel.innerHTML = radState.tiers
    .map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.label)}</option>`)
    .join("");
  if (radState.tiers.some((t) => t.id === prev)) sel.value = prev;
  else if (radState.tiers.length) {
    radState.activeTierId = radState.tiers[0].id;
    sel.value = radState.activeTierId;
  }
  const tier = radActiveTier();
  const radiusInput = document.getElementById("rad-default-radius");
  if (tier && radiusInput && !radiusInput.matches(":focus")) {
    radiusInput.value = tier.radius;
    radState.defaultRadius = tier.radius;
  }
  radRenderZoneTierSelect();
}

function radTiersForZone(zone) {
  const tiers = radState.tiers.map((t) => ({ ...t }));
  if (!zone) return tiers;
  const known = tiers.some((t) => t.color === zone.color && t.label === (zone.label || t.label));
  if (!known) {
    tiers.push({
      id: `t-zone-${zone.id}`,
      color: zone.color,
      label: zone.label || zone.color,
      radius: zone.radius,
    });
  }
  return tiers;
}

function radRenderZoneTierSelect() {
  const sel = document.getElementById("rad-zone-tier");
  if (!sel) return;
  radEnsureTiers();
  const zone = radState.zones.find((z) => z.id === radState.selectedId);
  const tiers = zone ? radTiersForZone(zone) : radState.tiers;
  sel.innerHTML = tiers
    .map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.label)}</option>`)
    .join("");
  if (zone) {
    const match =
      tiers.find((t) => t.color === zone.color && t.label === zone.label)
      || tiers.find((t) => t.color === zone.color)
      || tiers[0];
    if (match) sel.value = match.id;
  } else {
    sel.value = radState.activeTierId;
  }
}

function radRenderOverlaySelect() {
  const sel = document.getElementById("rad-overlay-select");
  if (!sel) return;
  sel.innerHTML = `<option value="">— нет подложки —</option>`;
  if (radState.overlay?.url) {
    const name = radState.overlay.url.split("/").pop();
    sel.innerHTML += `<option value="active" selected>${escapeHtml(name)}</option>`;
  }
  const preview = document.getElementById("rad-overlay-preview");
  if (preview) {
    if (radState.overlay?.url) {
      preview.src = radOverlaySrc(radState.overlay.url);
      preview.classList.remove("hidden");
    } else {
      preview.removeAttribute("src");
      preview.classList.add("hidden");
    }
  }
}

function radRenderZoneSelect() {
  const sel = document.getElementById("rad-zone-select");
  const count = document.getElementById("rad-zones-count");
  if (count) count.textContent = String(radState.zones.length);
  if (!sel) return;

  if (!radState.zones.length) {
    sel.innerHTML = `<option value="">Нет зон — кликните «+ Зона» и по карте</option>`;
    return;
  }

  sel.innerHTML = radState.zones
    .map((z, i) => {
      const label = z.label || `Зона ${i + 1}`;
      return `<option value="${escapeHtml(z.id)}" ${z.id === radState.selectedId ? "selected" : ""}>#${i + 1} ${escapeHtml(label)} · ${Math.round(z.x)}/${Math.round(z.y)} · r${Math.round(z.radius)}</option>`;
    })
    .join("");
}

function radSelectZone(id) {
  radState.selectedId = id || null;
  radRenderZoneSelect();
  const zone = radState.zones.find((z) => z.id === id);
  if (!zone) return;
  document.getElementById("rad-zone-x").value = Math.round(zone.x);
  document.getElementById("rad-zone-y").value = Math.round(zone.y);
  document.getElementById("rad-zone-radius").value = Math.round(zone.radius);
  const tier = radState.tiers.find((t) => t.color === zone.color);
  if (tier) radState.activeTierId = tier.id;
  radRenderTierSelect();
  radRenderZoneTierSelect();
  if (radState.map) {
    const latlng = radGameToLatLng(zone.x, zone.y);
    radState.map.panTo(latlng, { animate: true, duration: 0.35 });
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
    zIndexOffset: 2000,
  });

  const syncFromMarker = () => {
    const pos = radLatLngToGame(marker.getLatLng());
    zone.x = pos.x;
    zone.y = pos.y;
    circle.setLatLng(marker.getLatLng());
    if (radState.selectedId === zone.id) {
      document.getElementById("rad-zone-x").value = Math.round(zone.x);
      document.getElementById("rad-zone-y").value = Math.round(zone.y);
      radRenderZoneSelect();
    }
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
  radBringZonesToFront();
  radRenderZoneSelect();
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
  radBringZonesToFront();
  radSelectZone(zone.id);
  radState.addZoneMode = false;
  document.getElementById("rad-add-zone-btn")?.classList.remove("active");
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
  radRenderZoneSelect();
}

function radApplySelectedFields() {
  const id = radState.selectedId;
  if (!id) return;
  const zone = radState.zones.find((z) => z.id === id);
  if (!zone) return;
  zone.x = Number(document.getElementById("rad-zone-x").value);
  zone.y = Number(document.getElementById("rad-zone-y").value);
  zone.radius = Number(document.getElementById("rad-zone-radius").value);
  const tierId = document.getElementById("rad-zone-tier")?.value;
  const tiers = radTiersForZone(zone);
  const tier = tiers.find((t) => t.id === tierId) || radActiveTier();
  zone.label = tier.label;
  zone.color = tier.color;
  radUpsertZoneLayer(zone);
  radBringZonesToFront();
  radRenderZoneSelect();
}

function radClearOverlayHandles() {
  if (radState.overlayHandles) {
    radState.overlayHandles.forEach((marker) => {
      radState.map?.removeLayer(marker);
    });
  }
  radState.overlayHandles = [];
}

function radCreateOverlayHandles() {
  if (!radState.map || !radState.overlay?.bounds) return;

  const b = radState.overlay.bounds;

  // Corner handle style (blue squares)
  const cornerIcon = L.divIcon({
    className: "rad-overlay-corner-handle",
    html: '<div style="width:12px;height:12px;background:#2196f3;border:2px solid #fff;border-radius:2px;box-shadow:0 1px 4px rgba(0,0,0,0.4);cursor:nwse-resize;"></div>',
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  });

  // Center handle style (orange circle with crosshair symbol)
  const centerIcon = L.divIcon({
    className: "rad-overlay-center-handle",
    html: '<div style="width:18px;height:18px;background:#ff9800;border:2px solid #fff;border-radius:50%;box-shadow:0 1px 5px rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:bold;font-size:10px;cursor:move;">✥</div>',
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

  // 1. Bottom-left corner (x1, y1)
  const m1 = L.marker(radGameToLatLng(b.x1, b.y1), {
    draggable: true,
    icon: cornerIcon,
    zIndexOffset: 3000,
  }).addTo(radState.map);

  // 2. Top-right corner (x2, y2)
  const m2 = L.marker(radGameToLatLng(b.x2, b.y2), {
    draggable: true,
    icon: cornerIcon,
    zIndexOffset: 3000,
  }).addTo(radState.map);

  // 3. Center ((x1+x2)/2, (y1+y2)/2)
  const cx = (b.x1 + b.x2) / 2;
  const cy = (b.y1 + b.y2) / 2;
  const mCenter = L.marker(radGameToLatLng(cx, cy), {
    draggable: true,
    icon: centerIcon,
    zIndexOffset: 3000,
  }).addTo(radState.map);

  radState.overlayHandles = [m1, m2, mCenter];

  let startCenterCoords = { x: cx, y: cy };

  m1.on("dragstart", () => {
    mCenter.setOpacity(0.5);
  });
  
  m1.on("drag", (e) => {
    const pt = radLatLngToGame(e.target.getLatLng());
    b.x1 = Math.max(0, Math.min(pt.x, b.x2 - 10));
    b.y1 = Math.max(0, Math.min(pt.y, b.y2 - 10));
    
    radState.overlayLayer?.setBounds(radGameBoundsToLatLng(b));
    mCenter.setLatLng(radGameToLatLng((b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2));
    radFillBoundsInputs();
  });

  m1.on("dragend", () => {
    mCenter.setOpacity(1.0);
    radSyncOverlayLayer();
  });

  m2.on("dragstart", () => {
    mCenter.setOpacity(0.5);
  });

  m2.on("drag", (e) => {
    const size = radMapSize(radState.config);
    const pt = radLatLngToGame(e.target.getLatLng());
    b.x2 = Math.max(b.x1 + 10, Math.min(pt.x, size));
    b.y2 = Math.max(b.y1 + 10, Math.min(pt.y, size));

    radState.overlayLayer?.setBounds(radGameBoundsToLatLng(b));
    mCenter.setLatLng(radGameToLatLng((b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2));
    radFillBoundsInputs();
  });

  m2.on("dragend", () => {
    mCenter.setOpacity(1.0);
    radSyncOverlayLayer();
  });

  mCenter.on("dragstart", () => {
    startCenterCoords = {
      x: (b.x1 + b.x2) / 2,
      y: (b.y1 + b.y2) / 2
    };
    m1.setOpacity(0.5);
    m2.setOpacity(0.5);
  });

  mCenter.on("drag", (e) => {
    const size = radMapSize(radState.config);
    const pt = radLatLngToGame(e.target.getLatLng());
    const dx = pt.x - startCenterCoords.x;
    const dy = pt.y - startCenterCoords.y;

    const w = b.x2 - b.x1;
    const h = b.y2 - b.y1;

    let nx1 = b.x1 + dx;
    let ny1 = b.y1 + dy;
    let nx2 = b.x2 + dx;
    let ny2 = b.y2 + dy;

    if (nx1 < 0) { nx1 = 0; nx2 = w; }
    if (nx2 > size) { nx2 = size; nx1 = size - w; }
    if (ny1 < 0) { ny1 = 0; ny2 = h; }
    if (ny2 > size) { ny2 = size; ny1 = size - h; }

    b.x1 = nx1;
    b.y1 = ny1;
    b.x2 = nx2;
    b.y2 = ny2;

    startCenterCoords = {
      x: (b.x1 + b.x2) / 2,
      y: (b.y1 + b.y2) / 2
    };

    radState.overlayLayer?.setBounds(radGameBoundsToLatLng(b));
    m1.setLatLng(radGameToLatLng(b.x1, b.y1));
    m2.setLatLng(radGameToLatLng(b.x2, b.y2));
    radFillBoundsInputs();
  });

  mCenter.on("dragend", () => {
    m1.setOpacity(1.0);
    m2.setOpacity(1.0);
    radSyncOverlayLayer();
  });
}

function radSyncOverlayLayer() {
  if (radState.overlayLayer) {
    radState.map?.removeLayer(radState.overlayLayer);
    radState.overlayLayer = null;
  }
  radClearOverlayHandles();

  if (!radState.map || !radState.overlay?.url) return;

  const b = radState.overlay.bounds || {};
  const bounds = radGameBoundsToLatLng(b);
  const src = radOverlaySrc(radState.overlay.url);

  radState.overlayLayer = L.imageOverlay(src, bounds, {
    opacity: radState.overlay.opacity ?? 0.65,
    interactive: false,
    zIndex: 450,
  });

  radState.overlayLayer.on("error", () => {
    radSetStatus(`Не удалось загрузить подложку: ${radState.overlay.url}`, true);
  });

  radState.overlayLayer.addTo(radState.map);
  radState.overlayLayer.bringToFront();
  radBringZonesToFront();
  
  radCreateOverlayHandles();
}

function radFillBoundsInputs() {
  const size = radMapSize(radState.config);
  const b = radState.overlay?.bounds || { x1: 0, y1: 0, x2: size, y2: size };
  document.getElementById("rad-bounds-x1").value = Math.round(b.x1 ?? 0);
  document.getElementById("rad-bounds-y1").value = Math.round(b.y1 ?? 0);
  document.getElementById("rad-bounds-x2").value = Math.round(b.x2 ?? size);
  document.getElementById("rad-bounds-y2").value = Math.round(b.y2 ?? size);
  const op = document.getElementById("rad-overlay-opacity");
  if (op) op.value = String(radState.overlay?.opacity ?? 0.65);
  radRenderOverlaySelect();
}

function radReadBoundsFromInputs() {
  if (!radState.overlay) return;
  radState.overlay.bounds = {
    x1: Number(document.getElementById("rad-bounds-x1").value),
    y1: Number(document.getElementById("rad-bounds-y1").value),
    x2: Number(document.getElementById("rad-bounds-x2").value),
    y2: Number(document.getElementById("rad-bounds-y2").value),
  };
  radState.overlay.opacity = Number(document.getElementById("rad-overlay-opacity").value);
}

function radUpdateMinZoom() {
  if (!radState.map) return;
  const TILE_BOUNDS = L.latLngBounds(L.latLng(0, 0), L.latLng(-256, 256));
  const boundsZoom = radState.map.getBoundsZoom(TILE_BOUNDS, false);
  radState.map.setMinZoom(boundsZoom);
}

function radEnsureMap() {
  if (radState.map) return;

  const size = radMapSize(radState.config);
  const TILE_BOUNDS = L.latLngBounds(L.latLng(0, 0), L.latLng(-256, 256));

  radState.map = L.map("radiation-map", {
    crs: L.CRS.Simple,
    minZoom: 0,
    maxZoom: (radState.config.max_native_zoom || 7) + (radState.config.extra_zoom || 3),
    maxBounds: TILE_BOUNDS,
    maxBoundsViscosity: 1.0,
    zoomControl: true,
    attributionControl: false,
  });

  radState.map.setView(radGameToLatLng(size / 2, size / 2), 0);

  radState.tileLayer = L.tileLayer(radState.config.tiles_satellite, {
    maxNativeZoom: radState.config.max_native_zoom || 7,
    maxZoom: (radState.config.max_native_zoom || 7) + (radState.config.extra_zoom || 3),
    noWrap: true,
    bounds: radGameBoundsToLatLng({ x1: 0, y1: 0, x2: size, y2: size }),
  }).addTo(radState.map);

  radApplySatelliteVisibility();

  radState.map.on("click", (e) => {
    if (!radState.addZoneMode) return;
    const { x, y } = radLatLngToGame(e.latlng);
    radAddZone(x, y);
  });

  radUpdateMinZoom();
  setTimeout(() => {
    radState.map?.invalidateSize();
    radUpdateMinZoom();
  }, 200);
}

function radDestroyMap() {
  if (!radState.map) return;
  radClearZoneLayers();
  radClearOverlayHandles();
  if (radState.overlayLayer) radState.map.removeLayer(radState.overlayLayer);
  if (radState.tileLayer) radState.map.removeLayer(radState.tileLayer);
  radState.map.remove();
  radState.map = null;
  radState.tileLayer = null;
  radState.overlayLayer = null;
}

function radInitTiersFromLegend(legend) {
  const base = RAD_DEFAULT_TIERS.map((t) => ({ ...t }));
  const extra = [];
  (legend || []).forEach((item) => {
    if (!item?.label || !item?.color) return;
    if (base.some((t) => t.color === item.color && t.label === item.label)) return;
    extra.push({
      id: `t-custom-${extra.length}-${item.color.replace("#", "")}`,
      color: item.color,
      label: item.label,
      radius: 500,
    });
  });
  radState.tiers = [...base, ...extra];
  if (!radState.tiers.some((t) => t.id === radState.activeTierId)) {
    radState.activeTierId = radState.tiers[2]?.id || radState.tiers[0]?.id;
  }
  radRenderTierSelect();
}

function radAddCustomTier() {
  const label = prompt("Название уровня радиации:", "400 мЗв/ч");
  if (!label) return;
  const color = prompt("Цвет (#rrggbb):", "#9c27b0");
  if (!color || !/^#[0-9a-fA-F]{6}$/.test(color)) {
    radSetStatus("Неверный цвет, используйте формат #rrggbb", true);
    return;
  }
  const id = `t-custom-${Date.now()}`;
  radState.tiers.push({ id, color, label, radius: Number(document.getElementById("rad-default-radius")?.value) || 500 });
  radState.activeTierId = id;
  radRenderTierSelect();
}

async function radLoadForSlug(slug) {
  if (!slug) {
    radSetStatus("Выберите карту", true);
    return;
  }
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
    radState.legend = data.legend || [];
    radState.overlay = data.overlay || null;
    radState.loadedSlug = slug;
    radState.selectedId = null;
    radState.addZoneMode = false;

    radInitTiersFromLegend(radState.legend);
    radEnsureMap();
    radSyncOverlayLayer();
    radRenderAllZones();
    radFillBoundsInputs();
    if (radState.zones.length && !radState.selectedId) {
      radSelectZone(radState.zones[0].id);
    }
    radSetStatus(`Зон: ${radState.zones.length}${radState.overlay?.url ? " · подложка загружена" : ""}`);
    setTimeout(() => {
      radState.map?.invalidateSize();
      radUpdateMinZoom();
    }, 300);
  } catch (err) {
    radSetStatus(err.message, true);
  }
}

async function radSave() {
  const slug = document.getElementById("rad-map-select")?.value;
  if (!slug) {
    radSetStatus("Выберите карту", true);
    return;
  }
  radReadBoundsFromInputs();
  radSetStatus("Сохранение…");
  try {
    const payload = {
      map_slug: slug,
      zones: radState.zones,
      legend: radDefaultLegend(),
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
  if (!slug) {
    radSetStatus("Сначала выберите карту", true);
    return;
  }
  if (!file) {
    radSetStatus("Файл не выбран", true);
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    radSetStatus("Файл больше 20 МБ — сожмите изображение", true);
    return;
  }
  radSetStatus("Загрузка подложки…");
  const fd = new FormData();
  fd.append("file", file, file.name || "overlay.png");
  const res = await fetch(`/api/admin/radiation/overlay?map_slug=${encodeURIComponent(slug)}`, {
    method: "POST",
    credentials: "same-origin",
    body: fd,
  });
  const data = res.ok ? await res.json().catch(() => ({})) : null;
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (data?.detail) {
      msg = typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : JSON.stringify(data.detail);
    }
    radSetStatus(msg, true);
    alert(msg);
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
  setTimeout(() => radState.map?.invalidateSize(), 200);
  radSetStatus("Подложка загружена — подгоните границы если нужно");
}

async function radDeleteOverlay() {
  const slug = document.getElementById("rad-map-select")?.value;
  if (!slug) return;
  if (!radState.overlay?.url) return;
  if (!confirm("Удалить подложку?")) return;
  await api(`/api/admin/radiation/overlay?map_slug=${encodeURIComponent(slug)}`, { method: "DELETE" });
  radState.overlay = null;
  radFillBoundsInputs();
  radSyncOverlayLayer();
  radSetStatus("Подложка удалена");
}

function radBindUi() {
  if (document.getElementById("rad-ui-bound")?.value === "1") return;
  document.getElementById("rad-ui-bound").value = "1";

  radState.tiers = RAD_DEFAULT_TIERS.map((t) => ({ ...t }));
  radRenderTierSelect();

  document.getElementById("rad-map-select")?.addEventListener("change", (e) => {
    radLoadForSlug(e.target.value);
  });

  document.getElementById("rad-tier-select")?.addEventListener("change", (e) => {
    radState.activeTierId = e.target.value;
    radRenderTierSelect();
    if (radState.selectedId) radApplySelectedFields();
  });

  document.getElementById("rad-tier-add")?.addEventListener("click", radAddCustomTier);
  document.getElementById("rad-zone-tier-add")?.addEventListener("click", radAddCustomTier);

  document.getElementById("rad-zone-tier")?.addEventListener("change", (e) => {
    const tier = radState.tiers.find((t) => t.id === e.target.value);
    if (tier) {
      radState.activeTierId = tier.id;
      const toolbar = document.getElementById("rad-tier-select");
      if (toolbar) toolbar.value = tier.id;
    }
    if (radState.selectedId) radApplySelectedFields();
  });

  document.getElementById("rad-zone-select")?.addEventListener("change", (e) => {
    if (e.target.value) radSelectZone(e.target.value);
  });

  document.getElementById("rad-add-zone-btn")?.addEventListener("click", () => {
    radState.addZoneMode = !radState.addZoneMode;
    document.getElementById("rad-add-zone-btn")?.classList.toggle("active", radState.addZoneMode);
    radSetStatus(radState.addZoneMode ? "Кликните по карте, чтобы поставить зону" : "");
  });

  document.getElementById("rad-save-btn")?.addEventListener("click", () => {
    radSave().catch((err) => radSetStatus(err.message, true));
  });

  document.getElementById("rad-overlay-upload-btn")?.addEventListener("click", () => {
    document.getElementById("rad-overlay-file")?.click();
  });

  document.getElementById("rad-overlay-file")?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    radUploadOverlay(file).catch((err) => radSetStatus(err.message, true));
  });

  document.getElementById("rad-overlay-delete")?.addEventListener("click", () => {
    radDeleteOverlay().catch((err) => radSetStatus(err.message, true));
  });

  document.getElementById("rad-overlay-select")?.addEventListener("change", (e) => {
    if (e.target.value === "" && radState.overlay) {
      radState.overlay = null;
      radSyncOverlayLayer();
      radRenderOverlaySelect();
    }
  });

  document.getElementById("rad-hide-satellite")?.addEventListener("change", () => {
    radApplySatelliteVisibility();
  });

  document.getElementById("rad-apply-bounds")?.addEventListener("click", () => {
    radReadBoundsFromInputs();
    radSyncOverlayLayer();
    radSetStatus("Границы подложки применены");
  });

  document.getElementById("rad-overlay-opacity")?.addEventListener("input", () => {
    radReadBoundsFromInputs();
    if (radState.overlayLayer) radState.overlayLayer.setOpacity(radState.overlay.opacity);
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

  window.addEventListener("resize", () => {
    if (radState.map) {
      radState.map.invalidateSize({ animate: false });
      radUpdateMinZoom();
    }
  });
}

const RadiationEditor = {
  ensureLoaded() {
    radBindUi();
    radEnsureTiers();
    this.refreshMapSelect();
    radRenderTierSelect();
    const sel = document.getElementById("rad-map-select");
    if (!sel?.value && typeof mapsCache !== "undefined" && mapsCache.length) {
      sel.value = mapsCache[0].slug;
    }
    const slug = sel?.value;
    if (slug && slug !== radState.loadedSlug) {
      radLoadForSlug(slug);
    } else if (radState.map) {
      setTimeout(() => radState.map.invalidateSize(), 300);
    } else if (slug && !radState.zones.length) {
      radLoadForSlug(slug);
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
