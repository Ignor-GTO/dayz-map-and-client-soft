/** Reference layer: server POI markers on admin map editors. */
(function () {
  "use strict";

  const groups = new WeakMap();

  function poiIcon(poi) {
    return L.divIcon({
      className: "poi-map-pin admin-poi-ref",
      html: poiLabelHtml(poi.icon || "star", poi.title),
      iconSize: [240, 24],
      iconAnchor: [11, 12],
    });
  }

  window.AdminPoiLayer = {
    async render(map, mapSlug, toLatLng, apiFn, options = {}) {
      if (!map || !mapSlug || typeof toLatLng !== "function") return [];
      let group = groups.get(map);
      if (!group) {
        group = L.layerGroup();
        group.addTo(map);
        groups.set(map, group);
      }
      group.clearLayers();

      let pois = [];
      try {
        pois = await apiFn(`/api/admin/pois?map_slug=${encodeURIComponent(mapSlug)}`);
      } catch {
        return [];
      }

      const {
        interactive = false,
        highlightId = null,
        onMarkerClick = null,
      } = options;

      pois.forEach((poi) => {
        const latlng = toLatLng(poi.x, poi.y);
        const marker = L.marker(latlng, {
          icon: poiIcon(poi),
          interactive,
          zIndexOffset: highlightId === poi.id ? 500 : -200,
        });
        marker.bindTooltip(poi.title, { direction: "top", opacity: 0.95 });
        if (interactive) {
          marker.bindPopup(
            `<b>${escapeHtml(poi.title)}</b><br><span class="poi-coords">${Math.round(poi.x)} / ${Math.round(poi.y)}</span>`
          );
          if (onMarkerClick) {
            marker.on("click", () => onMarkerClick(poi));
          }
        }
        group.addLayer(marker);
      });

      return pois;
    },

    clear(map) {
      const group = groups.get(map);
      if (group) {
        group.clearLayers();
      }
    },
  };
})();
