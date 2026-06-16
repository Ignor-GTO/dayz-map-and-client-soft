const POI_ICONS = {
  star: { glyph: "★", label: "Звезда", color: "#3498db" },
  trader: { glyph: "🛒", label: "Торговец", color: "#2980b9" },
  camp: { glyph: "⛺", label: "Лагерь", color: "#c0392b" },
  heli: { glyph: "H", label: "Вертолёт", color: "#e91e9b" },
  skull: { glyph: "☠", label: "Опасно", color: "#2c3e50" },
  house: { glyph: "⌂", label: "Дом", color: "#8e44ad" },
  car: { glyph: "🚗", label: "Техника", color: "#16a085" },
  loot: { glyph: "📦", label: "Лут", color: "#d35400" },
  medical: { glyph: "+", label: "Медицина", color: "#27ae60" },
  water: { glyph: "≋", label: "Вода", color: "#1abc9c" },
  tower: { glyph: "▲", label: "Вышка", color: "#bdc3c7" },
  collector: { glyph: "◎", label: "Коллекционер", color: "#f1c40f" },
  military: { glyph: "✚", label: "Военное", color: "#7f8c8d" },
};

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
