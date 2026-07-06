/**
 * admin-buildings.js — Custom server building footprint editor.
 */
(function () {
  "use strict";

  const TILE_BOUNDS = L.latLngBounds(L.latLng(0, 0), L.latLng(-256, 256));

  const TYPE_COLORS = {
    structure: { stroke: "#e67e22", fill: "#e67e22" },
    residential: { stroke: "#3498db", fill: "#3498db" },
    industrial: { stroke: "#95a5a6", fill: "#95a5a6" },
    military: { stroke: "#c0392b", fill: "#c0392b" },
    commercial: { stroke: "#9b59b6", fill: "#9b59b6" },
    other: { stroke: "#f1c40f", fill: "#f1c40f" },
  };

  const TYPE_LABELS = {
    structure: "Строение",
    residential: "Жилое",
    industrial: "Промышленное",
    military: "Военное",
    commercial: "Коммерческое",
    other: "Прочее",
  };

  let buildingsMap = null;
  let mapConfig = null;
  let currentMapSlug = null;
  let allBuildings = [];
  let buildingLayers = new Map();
  let previewLayer = null;
  let drawCornerA = null;
  let drawMarkerA = null;
  let selectedId = null;
  let isDrawing = false;

  window.BuildingsEditor = { ensureLoaded, selectBuilding: (id) => selectBuilding(id) };

  function ensureLoaded() {
    if (buildingsMap) return;
    setTimeout(initMap, 100);
  }

  function buildingCorners(b) {
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

  function colorsFor(b) {
    const preset = TYPE_COLORS[b.building_type] || TYPE_COLORS.structure;
    return {
      stroke: b.stroke_color || preset.stroke,
      fill: b.fill_color || preset.fill,
    };
  }

  async function initMap() {
    try {
      const maps = await adminApi("/api/maps");
      if (!maps?.length) {
        showError("Нет доступных карт.");
        return;
      }
      populateMapSelect(maps);
      currentMapSlug = document.getElementById("buildings-map-select")?.value || maps[0].slug;
      mapConfig = await adminApi(`/api/maps/${currentMapSlug}/config`);
    } catch (e) {
      showError("Ошибка загрузки карты: " + e.message);
      return;
    }

    buildingsMap = L.map("buildings-map", {
      crs: L.CRS.Simple,
      minZoom: 1,
      maxZoom: 10,
      maxBounds: TILE_BOUNDS,
      maxBoundsViscosity: 1.0,
    });

    L.tileLayer(mapConfig.tiles_satellite, {
      tileSize: 256,
      maxNativeZoom: mapConfig.max_native_zoom,
      maxZoom: mapConfig.max_native_zoom + mapConfig.extra_zoom,
      noWrap: true,
      bounds: TILE_BOUNDS,
    }).addTo(buildingsMap);

    buildingsMap.fitBounds(TILE_BOUNDS);
    buildingsMap.on("click", onMapClick);
    bindFormEvents();
    await loadBuildings();
  }

  function populateMapSelect(maps) {
    const sel = document.getElementById("buildings-map-select");
    if (!sel) return;
    sel.innerHTML = maps.map((m) => `<option value="${m.slug}">${m.name}</option>`).join("");
    sel.onchange = async () => {
      currentMapSlug = sel.value;
      mapConfig = await adminApi(`/api/maps/${currentMapSlug}/config`);
      cancelDraw();
      clearSelection();
      await loadBuildings();
      await syncReferenceLayers();
    };
  }

  function toLatLng(x, y) {
    const size = mapConfig?.map_size || 20480;
    const ratio = size / 256;
    return L.latLng(y / ratio - 256, x / ratio);
  }

  function fromLatLng(latlng) {
    const size = mapConfig?.map_size || 20480;
    const ratio = size / 256;
    return [latlng.lng * ratio, (latlng.lat + 256) * ratio];
  }

  async function syncReferenceLayers() {
    if (!buildingsMap || !currentMapSlug) return;
    if (window.AdminPoiLayer) {
      await AdminPoiLayer.render(buildingsMap, currentMapSlug, toLatLng, adminApi, { interactive: false });
    }
    if (window.AdminGroupMarkersLayer) {
      await AdminGroupMarkersLayer.render(buildingsMap, currentMapSlug, toLatLng, adminApi, {
        mapSize: mapConfig?.map_size || 20480,
      });
    }
  }

  async function loadBuildings() {
    if (!currentMapSlug) return;
    try {
      allBuildings = await adminApi(`/api/admin/maps/${currentMapSlug}/buildings`);
      renderAllBuildings();
      updateBuildingList();
      await syncReferenceLayers();
    } catch (e) {
      showError("Ошибка загрузки зданий: " + e.message);
    }
  }

  function renderAllBuildings() {
    buildingLayers.forEach((layer) => buildingsMap.removeLayer(layer));
    buildingLayers.clear();
    allBuildings.forEach((b) => renderBuilding(b));
    const countEl = document.getElementById("buildings-count");
    if (countEl) countEl.textContent = `${allBuildings.length} зданий`;
  }

  function renderBuilding(b) {
    const corners = buildingCorners(b).map((p) => toLatLng(p.x, p.y));
    const { stroke, fill } = colorsFor(b);
    const layer = L.polygon(corners, {
      color: stroke,
      fillColor: fill,
      fillOpacity: selectedId === b.id ? 0.35 : 0.22,
      weight: selectedId === b.id ? 3 : 2,
      opacity: 0.9,
    }).addTo(buildingsMap);
    layer.bindTooltip(`${b.title}${b.classname ? " · " + b.classname : ""}`, { sticky: true });
    layer.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      selectBuilding(b.id);
    });
    buildingLayers.set(b.id, layer);
  }

  function updateBuildingList() {
    const el = document.getElementById("buildings-list");
    if (!el) return;
    if (!allBuildings.length) {
      el.innerHTML = `<div class="list-empty">Нет зданий — нарисуйте контур на карте</div>`;
      return;
    }
    el.innerHTML = allBuildings
      .map((b) => {
        const typeLabel = TYPE_LABELS[b.building_type] || b.building_type;
        return `<div class="road-seg-item ${selectedId === b.id ? "selected" : ""}" data-id="${b.id}" onclick="window.BuildingsEditor.selectBuilding(${b.id})">
          <div><strong>#${b.id} ${escapeHtml(b.title)}</strong></div>
          <div class="card-meta">${escapeHtml(typeLabel)} · ${Math.round(b.width)}×${Math.round(b.depth)} · ${Math.round(b.x)}/${Math.round(b.y)}</div>
        </div>`;
      })
      .join("");
  }

  function readForm() {
    return {
      title: document.getElementById("building-title")?.value.trim() || "Здание",
      classname: document.getElementById("building-classname")?.value.trim() || null,
      description: document.getElementById("building-description")?.value.trim() || "",
      building_type: document.getElementById("building-type")?.value || "structure",
      x: Number(document.getElementById("building-x")?.value || 0),
      y: Number(document.getElementById("building-y")?.value || 0),
      width: Number(document.getElementById("building-width")?.value || 20),
      depth: Number(document.getElementById("building-depth")?.value || 15),
      yaw: Number(document.getElementById("building-yaw")?.value || 0),
      enabled: document.getElementById("building-enabled")?.checked !== false,
    };
  }

  function fillForm(b) {
    document.getElementById("building-title").value = b.title || "";
    document.getElementById("building-classname").value = b.classname || "";
    document.getElementById("building-description").value = b.description || "";
    document.getElementById("building-type").value = b.building_type || "structure";
    document.getElementById("building-x").value = Math.round(b.x * 10) / 10;
    document.getElementById("building-y").value = Math.round(b.y * 10) / 10;
    document.getElementById("building-width").value = Math.round(b.width * 10) / 10;
    document.getElementById("building-depth").value = Math.round(b.depth * 10) / 10;
    document.getElementById("building-yaw").value = Math.round(b.yaw * 10) / 10;
    document.getElementById("building-enabled").checked = b.enabled !== false;
    document.getElementById("building-form-id").textContent = b.id ? `#${b.id}` : "новое";
  }

  function updatePreview() {
    if (previewLayer) {
      buildingsMap.removeLayer(previewLayer);
      previewLayer = null;
    }
    const data = readForm();
    if (!data.width || !data.depth) return;
    const corners = buildingCorners(data).map((p) => toLatLng(p.x, p.y));
    const { stroke, fill } = colorsFor(data);
    previewLayer = L.polygon(corners, {
      color: stroke,
      fillColor: fill,
      fillOpacity: 0.28,
      weight: 2,
      dashArray: "6,4",
    }).addTo(buildingsMap);
  }

  function onMapClick(e) {
    if (!isDrawing) return;
    const [x, y] = fromLatLng(e.latlng);
    if (!drawCornerA) {
      drawCornerA = [x, y];
      if (drawMarkerA) buildingsMap.removeLayer(drawMarkerA);
      drawMarkerA = L.circleMarker(e.latlng, { radius: 5, color: "#fff", fillColor: "#e67e22", fillOpacity: 1 }).addTo(buildingsMap);
      setStatus("Кликните противоположный угол здания");
      return;
    }
    const [x2, y2] = [x, y];
    const cx = (drawCornerA[0] + x2) / 2;
    const cy = (drawCornerA[1] + y2) / 2;
    const width = Math.max(5, Math.abs(x2 - drawCornerA[0]));
    const depth = Math.max(5, Math.abs(y2 - drawCornerA[1]));
    selectedId = null;
    fillForm({ title: "Здание", classname: "", description: "", building_type: "structure", x: cx, y: cy, width, depth, yaw: 0, enabled: true });
    cancelDraw(false);
    updatePreview();
    setStatus("Проверьте размеры и сохраните");
  }

  function startDraw() {
    isDrawing = true;
    drawCornerA = null;
    if (drawMarkerA) {
      buildingsMap.removeLayer(drawMarkerA);
      drawMarkerA = null;
    }
    document.getElementById("buildings-draw-btn")?.classList.add("active");
    setStatus("Кликните первый угол здания на карте");
  }

  function cancelDraw(resetForm = true) {
    isDrawing = false;
    drawCornerA = null;
    if (drawMarkerA) {
      buildingsMap.removeLayer(drawMarkerA);
      drawMarkerA = null;
    }
    document.getElementById("buildings-draw-btn")?.classList.remove("active");
    if (resetForm) setStatus("Готов");
  }

  function clearSelection() {
    selectedId = null;
    if (previewLayer) {
      buildingsMap.removeLayer(previewLayer);
      previewLayer = null;
    }
    updateBuildingList();
    renderAllBuildings();
  }

  function selectBuilding(id) {
    const b = allBuildings.find((row) => row.id === id);
    if (!b) return;
    selectedId = id;
    fillForm(b);
    updatePreview();
    updateBuildingList();
    renderAllBuildings();
    const layer = buildingLayers.get(id);
    if (layer) buildingsMap.fitBounds(layer.getBounds(), { padding: [40, 40], maxZoom: buildingsMap.getZoom() });
  }

  async function saveBuilding() {
    const data = readForm();
    if (!data.title) {
      showError("Укажите название");
      return;
    }
    try {
      if (selectedId) {
        await adminApi(`/api/admin/maps/${currentMapSlug}/buildings/${selectedId}`, {
          method: "PUT",
          body: JSON.stringify(data),
        });
      } else {
        const created = await adminApi(`/api/admin/maps/${currentMapSlug}/buildings`, {
          method: "POST",
          body: JSON.stringify(data),
        });
        selectedId = created.id;
      }
      cancelDraw(false);
      if (previewLayer) {
        buildingsMap.removeLayer(previewLayer);
        previewLayer = null;
      }
      await loadBuildings();
      if (selectedId) selectBuilding(selectedId);
      setStatus("Сохранено");
    } catch (e) {
      showError(e.message);
    }
  }

  async function deleteBuilding() {
    if (!selectedId) return;
    if (!confirm("Удалить здание?")) return;
    try {
      await adminApi(`/api/admin/maps/${currentMapSlug}/buildings/${selectedId}`, { method: "DELETE" });
      selectedId = null;
      fillForm({ title: "", classname: "", description: "", building_type: "structure", x: 0, y: 0, width: 20, depth: 15, yaw: 0, enabled: true });
      if (previewLayer) {
        buildingsMap.removeLayer(previewLayer);
        previewLayer = null;
      }
      await loadBuildings();
      setStatus("Удалено");
    } catch (e) {
      showError(e.message);
    }
  }

  function bindFormEvents() {
    document.getElementById("buildings-draw-btn")?.addEventListener("click", startDraw);
    document.getElementById("buildings-cancel-draw-btn")?.addEventListener("click", () => cancelDraw());
    document.getElementById("building-save-btn")?.addEventListener("click", saveBuilding);
    document.getElementById("building-delete-btn")?.addEventListener("click", deleteBuilding);
    document.getElementById("buildings-reload-btn")?.addEventListener("click", loadBuildings);
    document.getElementById("building-new-btn")?.addEventListener("click", () => {
      selectedId = null;
      fillForm({ title: "Здание", classname: "", description: "", building_type: "structure", x: 0, y: 0, width: 20, depth: 15, yaw: 0, enabled: true });
      if (previewLayer) {
        buildingsMap.removeLayer(previewLayer);
        previewLayer = null;
      }
      updateBuildingList();
      renderAllBuildings();
    });
    ["building-title", "building-classname", "building-description", "building-type", "building-x", "building-y", "building-width", "building-depth", "building-yaw"].forEach((id) => {
      document.getElementById(id)?.addEventListener("input", updatePreview);
      document.getElementById(id)?.addEventListener("change", updatePreview);
    });
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(text) {
    const el = document.getElementById("buildings-status");
    if (el) el.textContent = text;
  }

  function showError(msg) {
    const el = document.getElementById("buildings-error");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("hidden");
    setTimeout(() => el.classList.add("hidden"), 5000);
  }

  async function adminApi(path, options = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = res.ok ? await res.json().catch(() => ({})) : null;
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      if (data?.detail) msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      throw new Error(msg);
    }
    return data;
  }

  const origSwitchTab = window.switchTab;
  window.switchTab = function (name) {
    if (origSwitchTab) origSwitchTab(name);
    if (name === "buildings") {
      window.BuildingsEditor.ensureLoaded();
      setTimeout(() => buildingsMap && buildingsMap.invalidateSize(), 200);
    }
    if (name === "roads") {
      window.RoadsEditor?.ensureLoaded();
    }
  };
})();
