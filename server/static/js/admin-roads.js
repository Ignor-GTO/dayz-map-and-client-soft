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

  // Edit State
  let editingSegmentId = null;
  let editingPoints = [];      // [L.LatLng, ...]
  let editPolyline = null;    // Leaflet polyline representing edited segment
  let editMarkers = [];       // Vertex markers
  let editMidpoints = [];     // Midpoint markers
  let extendMode = null;       // null, "start", or "end"


  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------

  window.RoadsEditor = {
    ensureLoaded,
    selectSegment,
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
    if (editingSegmentId) cancelEditSegment();
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
        window.RoadsEditor.selectSegment(seg.id);
      }
    });

    poly.on("contextmenu", (e) => {
      if (!isDrawing) {
        L.DomEvent.stopPropagation(e);
        if (e.originalEvent) e.originalEvent.preventDefault();
        window.RoadsEditor.deleteSegment(seg.id);
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
          <div class="road-seg-item" data-id="${seg.id}" id="seg-item-${seg.id}" onclick="window.RoadsEditor.selectSegment(${seg.id}, event)" style="cursor: pointer;">
            <span class="seg-color-dot" style="background:${color}"></span>
            <div class="seg-info">
              <span class="seg-type">${label}</span>
              <span class="seg-pts">${pts} точек</span>
            </div>
            <button class="seg-focus-btn" onclick="event.stopPropagation(); window.RoadsEditor.focusSegment(${seg.id})" title="Найти на карте">🎯</button>
            <button class="seg-delete-btn" onclick="event.stopPropagation(); window.RoadsEditor.deleteSegment(${seg.id})" title="Удалить">🗑</button>
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

  function isSamePoint(p1, p2, threshold = 0.5) {
    return Math.abs(p1.lat - p2.lat) < threshold && Math.abs(p1.lng - p2.lng) < threshold;
  }

  function findConnectedSegments(startSegId) {
    const startSeg = allSegments.find(s => s.id === startSegId);
    if (!startSeg) return [];

    const visited = new Set();
    const queue = [startSegId];
    visited.add(startSegId);

    while (queue.length > 0) {
      const currentId = queue.shift();
      const currentSeg = allSegments.find(s => s.id === currentId);
      if (!currentSeg) continue;

      const currentLatLngs = currentSeg.points.map(([x, y]) => toLatLng(x, y));
      if (currentLatLngs.length < 2) continue;

      const pStart = currentLatLngs[0];
      const pEnd = currentLatLngs[currentLatLngs.length - 1];

      for (const otherSeg of allSegments) {
        if (visited.has(otherSeg.id)) continue;
        if (otherSeg.road_type !== currentSeg.road_type) continue;

        const otherLatLngs = otherSeg.points.map(([x, y]) => toLatLng(x, y));
        if (otherLatLngs.length < 2) continue;

        const oStart = otherLatLngs[0];
        const oEnd = otherLatLngs[otherLatLngs.length - 1];

        const threshold = 1.0;
        const isConnected = 
          isSamePoint(pStart, oStart, threshold) ||
          isSamePoint(pStart, oEnd, threshold) ||
          isSamePoint(pEnd, oStart, threshold) ||
          isSamePoint(pEnd, oEnd, threshold);

        if (isConnected) {
          visited.add(otherSeg.id);
          queue.push(otherSeg.id);
        }
      }
    }

    return Array.from(visited);
  }

  function showDeleteModal(segmentId, connectedCount) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.style.position = "fixed";
      overlay.style.top = "0";
      overlay.style.left = "0";
      overlay.style.width = "100vw";
      overlay.style.height = "100vh";
      overlay.style.background = "rgba(10, 15, 23, 0.75)";
      overlay.style.backdropFilter = "blur(6px)";
      overlay.style.webkitBackdropFilter = "blur(6px)";
      overlay.style.display = "flex";
      overlay.style.alignItems = "center";
      overlay.style.justifyContent = "center";
      overlay.style.zIndex = "99999";
      overlay.style.opacity = "0";
      overlay.style.transition = "opacity 0.2s ease";

      const modal = document.createElement("div");
      modal.style.background = "#1a2634";
      modal.style.border = "1px solid #2e3e52";
      modal.style.borderRadius = "12px";
      modal.style.padding = "24px";
      modal.style.width = "400px";
      modal.style.maxWidth = "90%";
      modal.style.boxShadow = "0 20px 40px rgba(0,0,0,0.55)";
      modal.style.transform = "scale(0.9)";
      modal.style.transition = "transform 0.2s ease";
      modal.style.color = "#e8f0ff";
      modal.style.fontFamily = "'Segoe UI', Roboto, sans-serif";

      const header = document.createElement("h3");
      header.textContent = "Удаление дороги";
      header.style.margin = "0 0 12px 0";
      header.style.fontSize = "1.25rem";
      header.style.color = "#ff4757";
      modal.appendChild(header);

      const body = document.createElement("p");
      body.innerHTML = `Этот сегмент соединен с другими частями дороги.<br><br>Найдено <strong>${connectedCount}</strong> соединенных сегментов этого же типа.<br>Что вы хотите удалить?`;
      body.style.margin = "0 0 20px 0";
      body.style.lineHeight = "1.5";
      body.style.fontSize = "0.95rem";
      modal.appendChild(body);

      const btnContainer = document.createElement("div");
      btnContainer.style.display = "flex";
      btnContainer.style.flexDirection = "column";
      btnContainer.style.gap = "8px";

      function createBtn(text, bg, fg, hoverBg, onClick) {
        const btn = document.createElement("button");
        btn.textContent = text;
        btn.style.padding = "10px 16px";
        btn.style.border = "none";
        btn.style.borderRadius = "6px";
        btn.style.cursor = "pointer";
        btn.style.fontWeight = "600";
        btn.style.fontSize = "0.9rem";
        btn.style.background = bg;
        btn.style.color = fg;
        btn.style.transition = "background 0.15s ease, transform 0.1s ease";
        btn.onmouseover = () => btn.style.background = hoverBg;
        btn.onmouseout = () => btn.style.background = bg;
        btn.onmousedown = () => btn.style.transform = "scale(0.98)";
        btn.onmouseup = () => btn.style.transform = "scale(1)";
        btn.onclick = onClick;
        return btn;
      }

      const onlySegBtn = createBtn(
        `Удалить только этот сегмент (#${segmentId})`,
        "#2c3e50",
        "#e8f0ff",
        "#34495e",
        () => { cleanup(); resolve("segment"); }
      );

      const entireRoadBtn = createBtn(
        `Удалить всю соединенную дорогу (${connectedCount} сегм.)`,
        "#c0392b",
        "#ffffff",
        "#e74c3c",
        () => { cleanup(); resolve("road"); }
      );

      const cancelBtn = createBtn(
        "Отмена",
        "transparent",
        "#95a5a6",
        "rgba(255,255,255,0.05)",
        () => { cleanup(); resolve(null); }
      );
      cancelBtn.style.border = "1px solid #7f8c8d";

      btnContainer.appendChild(entireRoadBtn);
      btnContainer.appendChild(onlySegBtn);
      btnContainer.appendChild(cancelBtn);
      modal.appendChild(btnContainer);
      overlay.appendChild(modal);
      document.body.appendChild(overlay);

      setTimeout(() => {
        overlay.style.opacity = "1";
        modal.style.transform = "scale(1)";
      }, 20);

      function cleanup() {
        overlay.style.opacity = "0";
        modal.style.transform = "scale(0.9)";
        setTimeout(() => {
          document.body.removeChild(overlay);
        }, 200);
      }
    });
  }

  window.RoadsEditor.deleteSegment = async function (id) {
    const connectedIds = findConnectedSegments(id);
    let choice = "segment";
    let idsToDelete = [id];

    if (connectedIds.length > 1) {
      choice = await showDeleteModal(id, connectedIds.length);
      if (choice === null) return; // Cancelled
      if (choice === "road") {
        idsToDelete = connectedIds;
      }
    } else {
      if (!confirm(`Удалить сегмент #${id}?`)) return;
    }

    try {
      await adminApi(`/api/admin/maps/${currentMapSlug}/roads/delete-bulk`, {
        method: "POST",
        body: JSON.stringify(idsToDelete),
      });

      idsToDelete.forEach((delId) => {
        if (editingSegmentId === delId) {
          cancelEditSegment();
        }
        allSegments = allSegments.filter((s) => s.id !== delId);
        const layer = segmentLayers.get(delId);
        if (layer) roadsMap.removeLayer(layer);
        segmentLayers.delete(delId);
      });

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
    if (editingSegmentId) cancelEditSegment();
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
    if (isDrawing) {
      let latlng = e.latlng;
      const snapLatLng = getSnapLatLng(latlng);
      if (snapLatLng) latlng = snapLatLng;

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
    } else if (editingSegmentId && extendMode) {
      let latlng = e.latlng;
      const snapLatLng = getSnapLatLng(latlng);
      if (snapLatLng) latlng = snapLatLng;

      if (extendMode === "start") {
        editingPoints.unshift(latlng);
      } else if (extendMode === "end") {
        editingPoints.push(latlng);
      }
      updateEditPolyline();
      renderEditMarkers();
      setStatus(`Редактирование: ${editingPoints.length} точек`, "drawing");
    }
  }

  function onMapDblClick(e) {
    if (isDrawing) {
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
    } else if (editingSegmentId) {
      L.DomEvent.stopPropagation(e);
    }
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
  // Editing mode
  // -------------------------------------------------------------------------

  function selectSegment(id) {
    const seg = allSegments.find((s) => s.id === id);
    if (seg) {
      highlightSegment(id);
      startEditSegment(seg);
    }
  }

  function startEditSegment(seg) {
    if (isDrawing) cancelDraw();
    if (editingSegmentId) cancelEditSegment();

    editingSegmentId = seg.id;
    editingPoints = seg.points.map(([x, y]) => toLatLng(x, y));
    extendMode = null;

    document.getElementById("roads-draw-tools").classList.add("hidden");
    document.getElementById("roads-edit-tools").classList.remove("hidden");
    document.getElementById("edit-seg-id").textContent = seg.id;

    const origLayer = segmentLayers.get(seg.id);
    if (origLayer) {
      origLayer.setStyle({ opacity: 0.15 });
    }

    roadsMap.getContainer().style.cursor = "";

    updateEditPolyline();
    renderEditMarkers();

    setStatus(`Редактирование #${seg.id}. Двойной клик на точке — удалить, правый клик — разрезать.`, "drawing");
  }

  function cancelEditSegment() {
    if (!editingSegmentId) return;

    const origLayer = segmentLayers.get(editingSegmentId);
    if (origLayer) {
      const seg = allSegments.find(s => s.id === editingSegmentId);
      const origWeight = ROAD_WEIGHTS[seg?.road_type] || 3;
      origLayer.setStyle({ opacity: 0.9, weight: origWeight });
    }

    clearEditPreview();

    editingSegmentId = null;
    editingPoints = [];
    extendMode = null;

    document.getElementById("roads-draw-tools").classList.remove("hidden");
    document.getElementById("roads-edit-tools").classList.add("hidden");
    document.querySelectorAll(".road-seg-item").forEach((el) => el.classList.remove("selected"));

    document.getElementById("roads-edit-extend-start").classList.remove("active");
    document.getElementById("roads-edit-extend-end").classList.remove("active");

    setStatus("Готов", "idle");
  }

  function clearEditPreview() {
    if (editPolyline) {
      roadsMap.removeLayer(editPolyline);
      editPolyline = null;
    }
    editMarkers.forEach(m => roadsMap.removeLayer(m));
    editMarkers = [];
    editMidpoints.forEach(m => roadsMap.removeLayer(m));
    editMidpoints = [];
  }

  function updateEditPolyline() {
    if (editPolyline) roadsMap.removeLayer(editPolyline);
    
    const roadType = allSegments.find(s => s.id === editingSegmentId)?.road_type || selectedRoadType;
    const color = "#ff9100";
    const weight = (ROAD_WEIGHTS[roadType] || 3) + 2;

    editPolyline = L.polyline(editingPoints, {
      color,
      weight,
      opacity: 0.9,
      lineJoin: "round",
      lineCap: "round",
    }).addTo(roadsMap);
  }

  function renderEditMarkers() {
    editMarkers.forEach(m => roadsMap.removeLayer(m));
    editMarkers = [];
    editMidpoints.forEach(m => roadsMap.removeLayer(m));
    editMidpoints = [];

    const vertexIcon = L.divIcon({
      className: "edit-vertex-icon",
      html: `<div style="width: 12px; height: 12px; background: #fff; border: 3px solid #ff3d00; border-radius: 50%; box-sizing: border-box; transform: translate(-3px, -3px); box-shadow: 0 0 4px rgba(0,0,0,0.5);"></div>`,
      iconSize: [12, 12],
      iconAnchor: [6, 6]
    });

    const midpointIcon = L.divIcon({
      className: "edit-midpoint-icon",
      html: `<div style="width: 8px; height: 8px; background: #fff; border: 2px solid #ff9100; border-radius: 50%; opacity: 0.8; box-sizing: border-box; transform: translate(-2px, -2px); box-shadow: 0 0 3px rgba(0,0,0,0.5);"></div>`,
      iconSize: [8, 8],
      iconAnchor: [4, 4]
    });

    editingPoints.forEach((latlng, idx) => {
      const m = L.marker(latlng, {
        icon: vertexIcon,
        draggable: true
      }).addTo(roadsMap);

      m.on("drag", (e) => {
        let latlng = e.target.getLatLng();
        const snapLatLng = getSnapLatLng(latlng);
        if (snapLatLng) {
          latlng = snapLatLng;
          e.target.setLatLng(latlng);
        }
        editingPoints[idx] = latlng;
        updateEditPolyline();
        updateMidpointsDuringDrag();
      });

      m.on("dragend", () => {
        renderEditMarkers();
      });

      m.on("dblclick", (e) => {
        L.DomEvent.stopPropagation(e);
        if (editingPoints.length <= 2) {
          showError("Минимум 2 точки в сегменте!");
          return;
        }
        editingPoints.splice(idx, 1);
        updateEditPolyline();
        renderEditMarkers();
      });

      m.on("contextmenu", (e) => {
        if (e.originalEvent) {
          e.originalEvent.preventDefault();
        }
        L.DomEvent.stopPropagation(e);
        if (idx === 0 || idx === editingPoints.length - 1) {
          showError("Нельзя разрезать дорогу на концах!");
          return;
        }
        if (confirm(`Разделить дорогу в этой точке на два отдельных сегмента?`)) {
          splitSegmentAt(idx);
        }
      });

      editMarkers.push(m);
    });

    for (let i = 0; i < editingPoints.length - 1; i++) {
      const p1 = editingPoints[i];
      const p2 = editingPoints[i+1];
      const mid = L.latLng((p1.lat + p2.lat) / 2, (p1.lng + p2.lng) / 2);

      const m = L.marker(mid, {
        icon: midpointIcon,
        draggable: true
      }).addTo(roadsMap);

      let hasInserted = false;
      m.on("drag", (e) => {
        let dragLatLng = e.target.getLatLng();
        const snapLatLng = getSnapLatLng(dragLatLng);
        if (snapLatLng) {
          dragLatLng = snapLatLng;
          e.target.setLatLng(dragLatLng);
        }
        if (!hasInserted) {
          hasInserted = true;
          editingPoints.splice(i + 1, 0, dragLatLng);
          updateEditPolyline();
        } else {
          editingPoints[i + 1] = dragLatLng;
          updateEditPolyline();
        }
      });

      m.on("dragend", () => {
        renderEditMarkers();
      });

      editMidpoints.push(m);
    }
  }

  function updateMidpointsDuringDrag() {
    for (let i = 0; i < editingPoints.length - 1; i++) {
      const p1 = editingPoints[i];
      const p2 = editingPoints[i+1];
      const mid = L.latLng((p1.lat + p2.lat) / 2, (p1.lng + p2.lng) / 2);
      if (editMidpoints[i]) {
        editMidpoints[i].setLatLng(mid);
      }
    }
  }

  function toggleExtendMode(mode) {
    if (extendMode === mode) {
      extendMode = null;
    } else {
      extendMode = mode;
    }

    const startBtn = document.getElementById("roads-edit-extend-start");
    const endBtn = document.getElementById("roads-edit-extend-end");

    startBtn.classList.remove("active");
    endBtn.classList.remove("active");

    if (extendMode === "start") {
      startBtn.classList.add("active");
      setStatus("Кликайте на карте, чтобы добавить точки в НАЧАЛО дороги", "drawing");
    } else if (extendMode === "end") {
      endBtn.classList.add("active");
      setStatus("Кликайте на карте, чтобы добавить точки в КОНЕЦ дороги", "drawing");
    } else {
      setStatus(`Редактирование #${editingSegmentId}. Двойной клик на точке — удалить, правый клик — разрезать.`, "drawing");
    }
  }

  async function saveEditSegment() {
    if (editingPoints.length < 2) {
      showError("Необходимо как минимум 2 точки!");
      return;
    }
    const points = editingPoints.map((ll) => fromLatLng(ll));
    const segmentId = editingSegmentId;

    try {
      const seg = await adminApi(`/api/admin/maps/${currentMapSlug}/roads/${segmentId}`, {
        method: "PUT",
        body: JSON.stringify({ points }),
      });

      const idx = allSegments.findIndex(s => s.id === segmentId);
      if (idx !== -1) {
        allSegments[idx] = seg;
      }

      const origLayer = segmentLayers.get(segmentId);
      if (origLayer) {
        roadsMap.removeLayer(origLayer);
      }

      cancelEditSegment();
      
      renderSegment(seg);
      updateSegmentList();
      
      setStatus(`✅ Сегмент #${segmentId} успешно обновлен`, "idle");
    } catch (e) {
      showError("Ошибка обновления сегмента: " + e.message);
    }
  }

  async function splitSegmentAt(idx) {
    const roadType = allSegments.find(s => s.id === editingSegmentId)?.road_type || selectedRoadType;
    const points1 = editingPoints.slice(0, idx + 1).map(ll => fromLatLng(ll));
    const points2 = editingPoints.slice(idx).map(ll => fromLatLng(ll));
    const segmentId = editingSegmentId;

    try {
      const seg1 = await adminApi(`/api/admin/maps/${currentMapSlug}/roads/${segmentId}`, {
        method: "PUT",
        body: JSON.stringify({ points: points1 }),
      });

      const seg2 = await adminApi(`/api/admin/maps/${currentMapSlug}/roads`, {
        method: "POST",
        body: JSON.stringify({ road_type: roadType, points: points2 }),
      });

      const idxLocal = allSegments.findIndex(s => s.id === segmentId);
      if (idxLocal !== -1) {
        allSegments[idxLocal] = seg1;
      }
      allSegments.push(seg2);

      const origLayer = segmentLayers.get(segmentId);
      if (origLayer) {
        roadsMap.removeLayer(origLayer);
      }

      cancelEditSegment();
      
      renderSegment(seg1);
      renderSegment(seg2);
      updateSegmentList();

      document.getElementById("roads-seg-count").textContent =
        `${allSegments.length} сегментов`;

      setStatus(`✅ Дорога разделена на сегменты #${seg1.id} и #${seg2.id}`, "idle");
    } catch (e) {
      showError("Ошибка разделения дороги: " + e.message);
    }
  }

  // -------------------------------------------------------------------------
  // Coordinate conversion
  // -------------------------------------------------------------------------

  // Map uses CRS.Simple: lat = y/ratio - 256, lng = x/ratio
  function toLatLng(x, y) {
    const size = mapConfig ? (mapConfig.map_size || 20480) : 20480;
    const ratio = size / 256;
    return L.latLng(y / ratio - 256, x / ratio);
  }

  function fromLatLng(latlng) {
    const size = mapConfig ? (mapConfig.map_size || 20480) : 20480;
    const ratio = size / 256;
    const x = latlng.lng * ratio;
    const y = (latlng.lat + 256) * ratio;
    return [x, y];
  }

  function getSnapLatLng(latlng) {
    const snapDistancePixels = 10; // Snap radius in pixels
    let closestLatLng = null;
    let minDistance = Infinity;

    const pTarget = roadsMap.latLngToContainerPoint(latlng);

    allSegments.forEach((seg) => {
      if (seg.id === editingSegmentId) return;

      seg.points.forEach((pt) => {
        const candidateLatLng = toLatLng(pt[0], pt[1]);
        const pCandidate = roadsMap.latLngToContainerPoint(candidateLatLng);
        
        const dx = pTarget.x - pCandidate.x;
        const dy = pTarget.y - pCandidate.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < snapDistancePixels && dist < minDistance) {
          minDistance = dist;
          closestLatLng = candidateLatLng;
        }
      });
    });

    return closestLatLng;
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

    // Edit controls listeners
    document.getElementById("roads-edit-extend-start").addEventListener("click", () => toggleExtendMode("start"));
    document.getElementById("roads-edit-extend-end").addEventListener("click", () => toggleExtendMode("end"));
    document.getElementById("roads-edit-save").addEventListener("click", saveEditSegment);
    document.getElementById("roads-edit-cancel").addEventListener("click", cancelEditSegment);
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
