/** Reference layer: user group markers (points, circles, lines) on admin map editors. */
(function () {
  "use strict";

  const groups = new WeakMap();

  function gameRadiusToLeaflet(radius, mapSize) {
    const ratio = (mapSize || 20480) / 256;
    return radius / ratio;
  }

  function markerLabel(m) {
    const title = m.title || m.type || "метка";
    return `${title} · ${m.nickname} · PIN ${m.room_pin}`;
  }

  window.AdminGroupMarkersLayer = {
    async render(map, mapSlug, toLatLng, apiFn, options = {}) {
      if (!map || !mapSlug || typeof toLatLng !== "function") return [];

      let group = groups.get(map);
      if (!group) {
        group = L.layerGroup();
        group.addTo(map);
        groups.set(map, group);
      }
      group.clearLayers();

      let markers = [];
      try {
        markers = await apiFn(
          `/api/admin/group-markers?map_slug=${encodeURIComponent(mapSlug)}`
        );
      } catch {
        return [];
      }

      const mapSize = options.mapSize || 20480;

      markers.forEach((m) => {
        const kind = m.geometry_kind || "point";
        const label = markerLabel(m);
        let layer;

        if (kind === "circle") {
          layer = L.circle(toLatLng(m.x, m.y), {
            radius: gameRadiusToLeaflet(m.radius || 300, mapSize),
            color: m.stroke_color || "#7bed9f",
            fillColor: m.fill_color || "#7bed9f",
            fillOpacity: 0.12,
            weight: 2,
            opacity: 0.75,
            dashArray: "6,5",
            interactive: false,
          });
        } else if (kind === "line" && Array.isArray(m.points) && m.points.length >= 2) {
          layer = L.polyline(
            m.points.map(([x, y]) => toLatLng(x, y)),
            {
              color: m.stroke_color || "#7bed9f",
              weight: 2.5,
              opacity: 0.8,
              dashArray: "8,6",
              interactive: false,
            }
          );
        } else {
          layer = L.circleMarker(toLatLng(m.x, m.y), {
            radius: 5,
            color: "#7bed9f",
            fillColor: "#7bed9f",
            fillOpacity: 0.85,
            weight: 1,
            opacity: 0.9,
            interactive: false,
          });
        }

        layer.bindTooltip(label, { direction: "top", opacity: 0.95, sticky: true });
        group.addLayer(layer);
      });

      return markers;
    },

    clear(map) {
      const group = groups.get(map);
      if (group) group.clearLayers();
    },
  };
})();
