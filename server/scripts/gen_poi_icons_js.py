"""Generate static/js/poi-icons.js from app/poi_icons.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.poi_icons import POI_ICONS

OUT = ROOT / "static/js/poi-icons.js"

lines = ["const POI_ICONS = {"]
for key, icon in POI_ICONS.items():
    glyph = icon["glyph"].replace("\\", "\\\\").replace('"', '\\"')
    label = icon["label"].replace('"', '\\"')
    lines.append(f'  {key}: {{ glyph: "{glyph}", label: "{label}", color: "{icon["color"]}" }},')
lines.append("};")
lines.append(
    """
function normalizePoiIcon(key) {
  const k = String(key || "star").toLowerCase();
  return POI_ICONS[k] ? k : "star";
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function poiLabelHtml(iconKey, title) {
  const key = normalizePoiIcon(iconKey);
  const icon = POI_ICONS[key];
  return `<div class="poi-pin"><span class="poi-glyph" style="background:${icon.color}">${icon.glyph}</span><span class="poi-title">${escapeHtml(title)}</span></div>`;
}

function poiPopupHtml(poi) {
  const desc = poi.description ? `<div class="poi-desc">${escapeHtml(poi.description)}</div>` : "";
  const img = poi.description_image_url
    ? `<img class="poi-desc-image" src="${escapeHtml(poi.description_image_url)}" alt="" loading="lazy">`
    : "";
  return `<b>${escapeHtml(poi.title)}</b>${desc}${img}<br><span class="poi-coords">${Math.round(poi.x)} / ${Math.round(poi.y)}</span><br><button class="marker-route" data-x="${poi.x}" data-y="${poi.y}" style="margin-top: 8px;">Маршрут</button>`;
}

function renderPoiIconPicker(container, selectedKey, onChange) {
  if (!container) return;
  const key = normalizePoiIcon(selectedKey);
  container.innerHTML = Object.entries(POI_ICONS)
    .map(([id, icon]) => `
      <button type="button" class="icon-option${id === key ? " active" : ""}" data-icon="${id}" title="${icon.label}">
        <span class="icon-option-glyph" style="background:${icon.color}">${icon.glyph}</span>
        <span class="icon-option-label">${icon.label}</span>
      </button>
    `)
    .join("");

  container.querySelectorAll(".icon-option").forEach((btn) => {
    btn.addEventListener("click", () => {
      container.querySelectorAll(".icon-option").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      onChange(btn.dataset.icon);
    });
  });
}
"""
)

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT} ({len(POI_ICONS)} icons)")
