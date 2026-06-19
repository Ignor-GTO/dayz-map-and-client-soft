/**
 * admin-roads.js — Road network editor for the admin panel.
 * Allows drawing, managing and deleting road segments on the DayZ map.
 *
 * Road types:
 *   highway : yellow  (#f5c900) — main highway
 *   road    : gray    (#b0b0b0) — village/rural road
 *   street  : blue   (#4fc3f7) — city street
 */
(function () {
  "use strict";

  const ROAD_COLORS = {
    highway: "#c084fc",
    road: "#b0b0b0",
    street: "#4fc3f7",
  };

  const ROAD_WEIGHTS = {
    highway: 5,
    road: 3,
    street: 2.5,
  };

  const ROAD_LABELS = {
    highway: "Трасса",
    road: "Посёлковая",
    street: "Городская",
  };

  // Map config matches the real map
  const TILE_BOUNDS = L.latLngBounds(L.latLng(0, 0), L.latLng(-256, 256));
  const MAP_CENTER = [-128, 128];
  const MAP_ZOOM = 3;

  let roadsMap = null;
  let tileLayer = null;
  let mapConfig = null;

  // State
  let currentMapSlug = null;
  let selectedRoadType = "highway";
  let isDrawing = false;
  let drawPoints = [];        // [[lat, lng], ...] — currently drawing
  let drawPolyline = null;    // Leaflet polyline being drawn
  let drawMarkers = [];       // vertex markers
  let allSegments = [];       // loaded from server
  let segmentLayers = new Map(); // id -> Leaflet polyline

  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------

  window.RoadsEditor = {
    ensureLoaded,
  };

  function ensureLoaded() {
    if (roadsMap) return;
    setTimeout(initMap, 100);
  }

  async function initMap() {
    // Fetch map config to get tile URLs
    try {
      const maps = await adminApi("/api/maps");
      if (!maps || maps.length === 0) {
        showError("Нет доступных карт. Сначала добавьте карту.");
        return;
      }
      currentMapSlug = maps[0].slug;
      mapConfig = await adminApi(`/api/maps/${currentMapSlug}/config`);
    } catch (e) {
      showError("Ошибка загрузки конфигурации карты: " + e.message);
      return;
    }

    roadsMap = L.map("roads-map", {
      crs: L.CRS.Simple,
      minZoom: 1,
      maxZoom: 10,
      maxBounds: TILE_BOUNDS,
      maxBoundsViscosity: 1.0,
    });

    tileLayer = L.tileLayer(mapConfig.tiles_satellite, {
      tileSize: 256,
      maxNativeZoom: mapConfig.max_native_zoom,
      maxZoom: mapConfig.max_native_zoom + mapConfig.extra_zoom,
      noWrap: true,
      bounds: TILE_BOUNDS,
    }).addTo(roadsMap);

    roadsMap.fitBounds(TILE_BOUNDS);

    // Map click for drawing
    roadsMap.on("click", onMapClick);
    roadsMap.on("dblclick", onMapDblClick);

    await loadSegments();
    bindEvents();
  }

  // -------------------------------------------------------------------------
  // Segment loading and rendering
  // -------------------------------------------------------------------------

  async function loadSegments() {
    if (!currentMapSlug) return;
    try {
      allSegments = await adminApi(`/api/admin/maps/${currentMapSlug}/roads`);
      renderAllSegments();
      updateSegmentList();
    } catch (e) {
      showError("Ошибка загрузки дорог: " + e.message);
    }
  }

  function renderAllSegments() {
    // Remove old layers
    segmentLayers.forEach((layer) => roadsMap.removeLayer(layer));
    segmentLayers.clear();

    allSegments.forEach((seg) => {
      renderSegment(seg);
    });

    document.getElementById("roads-seg-count").textContent =
      `${allSegments.length} сегментов`;
  }

  function renderSegment(seg) {
    // points are [[x, y], ...] in map coords
    // In Leaflet CRS.Simple: lat = -y, lng = x (because y grows down)
    const latLngs = seg.points.map(([x, y]) => toLatLng(x, y));
    const color = ROAD_COLORS[seg.road_type] || "#fff";
    const weight = ROAD_WEIGHTS[seg.road_type] || 3;

    const poly = L.polyline(latLngs, {
      color,
      weight,
      opacity: 0.9,
      lineJoin: "round",
      lineCap: "round",
    }).addTo(roadsMap);

    poly.bindTooltip(
      `${ROAD_LABELS[seg.road_type] || seg.road_type} #${seg.id}`,
      { sticky: true }
    );

    poly.on("click", (e) => {
      if (!isDrawing) {
        L.DomEvent.stopPropagation(e);
        highlightSegment(seg.id);
      }
    });

    segmentLayers.set(seg.id, poly);
    return poly;
  }

  function updateSegmentList() {
    const list = document.getElementById("roads-segment-list");
    if (!allSegments.length) {
      list.innerHTML = '<p class="roads-empty">Нет сегментов. Нарисуйте дорогу на карте.</p>';
      return;
    }

    list.innerHTML = allSegments
      .map((seg) => {
        const color = ROAD_COLORS[seg.road_type] || "#fff";
        const label = ROAD_LABELS[seg.road_type] || seg.road_type;
        const pts = seg.points.length;
        return `
          <div class="road-seg-item" data-id="${seg.id}" id="seg-item-${seg.id}">
            <span class="seg-color-dot" style="background:${color}"></span>
            <div class="seg-info">
              <span class="seg-type">${label}</span>
              <span class="seg-pts">${pts} точек</span>
            </div>
            <button class="seg-focus-btn" onclick="RoadsEditor.focusSegment(${seg.id})" title="Найти на карте">🎯</button>
            <button class="seg-delete-btn" onclick="RoadsEditor.deleteSegment(${seg.id})" title="Удалить">🗑</button>
          </div>`;
      })
      .join("");
  }

  function highlightSegment(id) {
    // Scroll to item in sidebar
    const item = document.getElementById(`seg-item-${id}`);
    if (item) {
      document.querySelectorAll(".road-seg-item").forEach((el) =>
        el.classList.remove("selected")
      );
      item.classList.add("selected");
      item.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    // Flash the polyline
    const poly = segmentLayers.get(id);
    if (poly) {
      const orig = poly.options.weight;
      poly.setStyle({ weight: orig + 4, opacity: 1 });
      setTimeout(() => poly.setStyle({ weight: orig, opacity: 0.9 }), 600);
    }
  }

  // Public
  window.RoadsEditor.focusSegment = function (id) {
    const poly = segmentLayers.get(id);
    if (poly) {
      roadsMap.fitBounds(poly.getBounds(), { maxZoom: 6 });
      highlightSegment(id);
    }
  };

  window.RoadsEditor.deleteSegment = async function (id) {
    if (!confirm(`Удалить сегмент #${id}?`)) return;
    try {
      await adminApi(`/api/admin/maps/${currentMapSlug}/roads/${id}`, {
        method: "DELETE",
      });
      allSegments = allSegments.filter((s) => s.id !== id);
      const layer = segmentLayers.get(id);
      if (layer) roadsMap.removeLayer(layer);
      segmentLayers.delete(id);
      updateSegmentList();
      document.getElementById("roads-seg-count").textContent =
        `${allSegments.length} сегментов`;
    } catch (e) {
      showError("Ошибка удаления: " + e.message);
    }
  };

  // -------------------------------------------------------------------------
  // Drawing mode
  // -------------------------------------------------------------------------

  function startDraw() {
    isDrawing = true;
    drawPoints = [];
    clearDrawPreview();
    roadsMap.getContainer().style.cursor = "crosshair";
    setStatus("Кликайте по карте, двойной клик — сохранить сегмент", "drawing");
  }

  function cancelDraw() {
    isDrawing = false;
    drawPoints = [];
    clearDrawPreview();
    roadsMap.getContainer().style.cursor = "";
    setStatus("Готов", "idle");
  }

  function clearDrawPreview() {
    if (drawPolyline) {
      roadsMap.removeLayer(drawPolyline);
      drawPolyline = null;
    }
    drawMarkers.forEach((m) => roadsMap.removeLayer(m));
    drawMarkers = [];
  }

  function undoLastPoint() {
    if (!isDrawing || drawPoints.length === 0) return;
    const removedPt = drawPoints.pop();
    const removedMarker = drawMarkers.pop();
    if (removedMarker) roadsMap.removeLayer(removedMarker);
    updateDrawPolyline();
    if (drawPoints.length === 0) {
      setStatus("Кликайте по карте, двойной клик — сохранить сегмент", "drawing");
    }
  }

  function onMapClick(e) {
    if (!isDrawing) return;
    const latlng = e.latlng;
    drawPoints.push(latlng);

    // Add vertex marker
    const vm = L.circleMarker(latlng, {
      radius: 5,
      color: ROAD_COLORS[selectedRoadType],
      fillColor: "#fff",
      fillOpacity: 1,
      weight: 2,
    }).addTo(roadsMap);
    drawMarkers.push(vm);

    updateDrawPolyline();
    setStatus(`${drawPoints.length} точек — двойной клик для сохранения`, "drawing");
  }

  function onMapDblClick(e) {
    if (!isDrawing) return;
    // Leaflet fires click before dblclick — so we have at least 2 points
    // Remove the last duplicate click from dblclick
    if (drawPoints.length > 1) {
      drawPoints.pop();
      const extra = drawMarkers.pop();
      if (extra) roadsMap.removeLayer(extra);
    }
    if (drawPoints.length < 2) {
      cancelDraw();
      return;
    }
    saveSegment();
  }

  function updateDrawPolyline() {
    if (drawPolyline) roadsMap.removeLayer(drawPolyline);
    if (drawPoints.length < 2) { drawPolyline = null; return; }
    drawPolyline = L.polyline(drawPoints, {
      color: ROAD_COLORS[selectedRoadType],
      weight: ROAD_WEIGHTS[selectedRoadType],
      opacity: 0.7,
      dashArray: "8 4",
    }).addTo(roadsMap);
  }

  async function saveSegment() {
    const points = drawPoints.map((ll) => fromLatLng(ll));
    cancelDraw();

    try {
      const seg = await adminApi(`/api/admin/maps/${currentMapSlug}/roads`, {
        method: "POST",
        body: JSON.stringify({ road_type: selectedRoadType, points }),
      });
      allSegments.push(seg);
      renderSegment(seg);
      updateSegmentList();
      document.getElementById("roads-seg-count").textContent =
        `${allSegments.length} сегментов`;
      setStatus(`✅ Сохранено: ${ROAD_LABELS[seg.road_type]} #${seg.id}`, "idle");
    } catch (e) {
      showError("Ошибка сохранения: " + e.message);
    }

    // restart drawing mode
    startDraw();
  }

  // -------------------------------------------------------------------------
  // Coordinate conversion
  // -------------------------------------------------------------------------

  // Map uses CRS.Simple: lat = -y, lng = x
  function toLatLng(x, y) {
    return L.latLng(-y, x);
  }

  function fromLatLng(latlng) {
    return [latlng.lng, -latlng.lat];
  }

  // -------------------------------------------------------------------------
  // Event bindings
  // -------------------------------------------------------------------------

  function bindEvents() {
    // Road type selector
    document.querySelectorAll(".road-type-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".road-type-btn").forEach((b) =>
          b.classList.remove("active")
        );
        btn.classList.add("active");
        selectedRoadType = btn.dataset.type;
        // Update draw preview color
        if (drawPolyline) updateDrawPolyline();
      });
    });

    document.getElementById("roads-draw-btn").addEventListener("click", () => {
      if (!isDrawing) startDraw();
    });

    document.getElementById("roads-undo-btn").addEventListener("click", undoLastPoint);

    document.getElementById("roads-cancel-btn").addEventListener("click", cancelDraw);

    document.getElementById("roads-reload-btn").addEventListener("click", loadSegments);
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  function setStatus(msg, state) {
    const el = document.getElementById("roads-draw-status");
    if (!el) return;
    el.textContent = msg;
    el.className = `draw-${state}`;
  }

  function showError(msg) {
    const el = document.getElementById("roads-error");
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
      if (data?.detail)
        msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      throw new Error(msg);
    }
    return data;
  }

  // -------------------------------------------------------------------------
  // Hook into switchTab
  // -------------------------------------------------------------------------
  const origSwitchTab = window.switchTab;
  window.switchTab = function (name) {
    if (origSwitchTab) origSwitchTab(name);
    if (name === "roads") {
      window.RoadsEditor.ensureLoaded();
      // invalidate map size after tab reveal
      setTimeout(() => roadsMap && roadsMap.invalidateSize(), 200);
    }
  };
})();
