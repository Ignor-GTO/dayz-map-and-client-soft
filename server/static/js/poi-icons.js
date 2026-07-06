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
  radiation: { glyph: "☢", label: "Радиация", color: "#e67e22" },
  anomaly: { glyph: "⚡", label: "Аномалия", color: "#9b59b6" },
  artifact: { glyph: "◆", label: "Артефакт", color: "#00bcd4" },
  stash: { glyph: "▣", label: "Тайник", color: "#795548" },
  bunker: { glyph: "▧", label: "Бункер", color: "#607d8b" },
  factory: { glyph: "⚙", label: "Завод", color: "#546e7a" },
  farm: { glyph: "🌾", label: "Ферма", color: "#8bc34a" },
  fuel: { glyph: "⛽", label: "Топливо", color: "#ff5722" },
  weapon: { glyph: "🔫", label: "Оружие", color: "#455a64" },
  ammo: { glyph: "⊙", label: "Патроны", color: "#78909c" },
  armor: { glyph: "🛡", label: "Броня", color: "#5d4037" },
  food: { glyph: "🍖", label: "Еда", color: "#d84315" },
  drink: { glyph: "🥤", label: "Напитки", color: "#039be5" },
  craft: { glyph: "🔧", label: "Крафт", color: "#90a4ae" },
  repair: { glyph: "🔩", label: "Ремонт", color: "#757575" },
  garage: { glyph: "🛞", label: "Гараж", color: "#37474f" },
  parking: { glyph: "P", label: "Парковка", color: "#455a64" },
  boat: { glyph: "⛵", label: "Лодка", color: "#0288d1" },
  plane: { glyph: "✈", label: "Самолёт", color: "#1976d2" },
  train: { glyph: "🚂", label: "Поезд", color: "#6d4c41" },
  bridge: { glyph: "⌇", label: "Мост", color: "#9e9e9e" },
  cave: { glyph: "◉", label: "Пещера", color: "#424242" },
  mine: { glyph: "⛏", label: "Шахта", color: "#5d4037" },
  lab: { glyph: "⚗", label: "Лаборатория", color: "#7e57c2" },
  hospital: { glyph: "🏥", label: "Госпиталь", color: "#e53935" },
  church: { glyph: "⛪", label: "Церковь", color: "#8d6e63" },
  school: { glyph: "📚", label: "Школа", color: "#fb8c00" },
  shop: { glyph: "🏬", label: "Магазин", color: "#43a047" },
  market: { glyph: "🏪", label: "Рынок", color: "#66bb6a" },
  police: { glyph: "👮", label: "Милиция", color: "#1565c0" },
  fire: { glyph: "🔥", label: "Пожар", color: "#ff6f00" },
  toxic: { glyph: "☣", label: "Токсично", color: "#c0ca33" },
  safe: { glyph: "🔒", label: "Безопасно", color: "#2e7d32" },
  warning: { glyph: "!", label: "Внимание", color: "#f9a825" },
  quest: { glyph: "?", label: "Квест", color: "#ab47bc" },
  npc: { glyph: "👤", label: "NPC", color: "#5c6bc0" },
  event: { glyph: "✦", label: "Событие", color: "#ff7043" },
  spawn: { glyph: "◇", label: "Спавн", color: "#26a69a" },
  extract: { glyph: "→", label: "Выход", color: "#00acc1" },
  entrance: { glyph: "⇒", label: "Вход", color: "#00897b" },
  sniper: { glyph: "⊕", label: "Снайпер", color: "#263238" },
  ambush: { glyph: "✕", label: "Засада", color: "#b71c1c" },
  boss: { glyph: "♛", label: "Босс", color: "#880e4f" },
  mutant: { glyph: "M", label: "Мутант", color: "#6a1b9a" },
  dog: { glyph: "🐕", label: "Псы", color: "#8d6e63" },
  infected: { glyph: "Z", label: "Заражённые", color: "#33691e" },
  bandit: { glyph: "B", label: "Бандиты", color: "#4e342e" },
  friendly: { glyph: "♥", label: "Союзники", color: "#e91e63" },
  radio: { glyph: "📡", label: "Радио", color: "#0277bd" },
  power: { glyph: "Φ", label: "Электрика", color: "#ffc107" },
  generator: { glyph: "G", label: "Генератор", color: "#616161" },
  antenna: { glyph: "📶", label: "Связь", color: "#78909c" },
  cnpp: { glyph: "☢", label: "АЭС", color: "#ff6f00" },
  ruins: { glyph: "🏚", label: "Руины", color: "#a1887f" },
  barricade: { glyph: "╬", label: "Заграждение", color: "#6d4c41" },
  watch: { glyph: "👁", label: "Наблюдение", color: "#5e35b1" },
  helipad: { glyph: "+", label: "Вертопад", color: "#00838f" },
  depot: { glyph: "▦", label: "Склад", color: "#558b2f" },
  locker: { glyph: "🗄", label: "Шкафчик", color: "#795548" },
  key: { glyph: "🔑", label: "Ключ", color: "#f9a825" },
  money: { glyph: "$", label: "Деньги", color: "#43a047" },
  tools: { glyph: "🛠", label: "Инструменты", color: "#78909c" },
  camera: { glyph: "📷", label: "Камера", color: "#5c6bc0" },
  map: { glyph: "🗺", label: "Карта", color: "#26a69a" },
  flag: { glyph: "⚑", label: "Флаг", color: "#e53935" },
  base: { glyph: "⛯", label: "База", color: "#1565c0" },
  fence: { glyph: "╫", label: "Забор", color: "#8d6e63" },
  trap: { glyph: "⊗", label: "Ловушка", color: "#bf360c" },
  chem: { glyph: "⚗", label: "Химия", color: "#7cb342" },
  bio: { glyph: "🧬", label: "Биолаб", color: "#8e24aa" },
  gas: { glyph: "☁", label: "Газ", color: "#90a4ae" },
  night: { glyph: "☾", label: "Ночь", color: "#3949ab" },
  day: { glyph: "☀", label: "День", color: "#ffb300" },
  marker: { glyph: "📌", label: "Метка", color: "#e74c3c" },
  chest: { glyph: "📦", label: "Сундук", color: "#d35400" },
  point: { glyph: "🔵", label: "Точка", color: "#3498db" },
  death: { glyph: "💀", label: "Смерть", color: "#2c3e50" },
  danger: { glyph: "⚠", label: "Опасность", color: "#f39c12" },
  screenshot: { glyph: "❓", label: "Снимок", color: "#9b59b6" },
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

function poiPopupHtml(poi, options = {}) {
  const titleText = String(poi.title || "").trim();
  const descText = String(poi.description || "").trim();
  const desc = descText && descText.toLowerCase() !== titleText.toLowerCase()
    ? `<div class="poi-desc">${escapeHtml(descText)}</div>`
    : "";
  const img = poi.description_image_url
    ? `<img class="poi-desc-image" src="${escapeHtml(poi.description_image_url)}" alt="" loading="lazy">`
    : "";
  let traderLink = "";
  if (poi.trader_name) {
    const mapSlug = (typeof state !== "undefined" && state.me?.map_slug) || "";
    const url = `/traders.html?map=${encodeURIComponent(mapSlug)}&trader=${encodeURIComponent(poi.trader_name)}`;
    const traderLabel = poi.trader_name.trim().toLowerCase() === titleText.toLowerCase()
      ? "🛒 Открыть у торговца"
      : `🛒 Открыть у торговца «${escapeHtml(poi.trader_name)}»`;
    traderLink = `<a class="poi-trader-link" href="${url}" target="_blank" rel="noopener">${traderLabel}</a>`;
  }
  const actionButtons = [
    `<button type="button" class="marker-route" data-x="${poi.x}" data-y="${poi.y}">Маршрут</button>`,
  ];
  if (options.canManage) {
    actionButtons.push(`<button type="button" class="poi-edit-btn" data-id="${poi.id}">✏️ Изменить</button>`);
    actionButtons.push(`<button type="button" class="poi-delete-btn" data-id="${poi.id}">Удалить</button>`);
  }
  const meta = `<div class="marker-popup-meta"><span class="poi-coords">${Math.round(poi.x)} / ${Math.round(poi.y)}</span>${traderLink}</div>`;
  const actions = `<div class="marker-popup-actions">${actionButtons.join("")}</div>`;
  return `<b>${escapeHtml(titleText)}</b>${desc}${img}${meta}${actions}`;
}

function filterIconEntries(entries, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return entries;
  return entries.filter(([id, item]) => {
    const label = String(item?.label || "").toLowerCase();
    return String(id).toLowerCase().includes(q) || label.includes(q);
  });
}

function setupSearchableIconPicker(container, config) {
  if (!container) return null;

  const {
    entries,
    selectedKey,
    onSelect,
    gridClass = "icon-picker icon-picker-grid",
    renderOption,
  } = config;

  let searchInput;
  let grid;
  let currentSelected = selectedKey;

  if (container.dataset.searchPickerReady === "1") {
    searchInput = container.querySelector(".icon-picker-search");
    grid = container.querySelector(".icon-picker-grid");
  } else {
    container.innerHTML = "";
    container.classList.add("icon-picker-wrap");
    container.dataset.searchPickerReady = "1";
    searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.className = "icon-picker-search";
    searchInput.placeholder = "Поиск по названию…";
    searchInput.autocomplete = "off";
    searchInput.setAttribute("aria-label", "Поиск иконки");
    grid = document.createElement("div");
    grid.className = gridClass;
    container.appendChild(searchInput);
    container.appendChild(grid);
  }

  function paintGrid() {
    if (!grid) return;
    const filtered = filterIconEntries(entries, searchInput.value);
    grid.innerHTML = filtered.length
      ? filtered.map(([id, item]) => renderOption(id, item, id === currentSelected)).join("")
      : `<div class="icon-picker-empty">Ничего не найдено</div>`;

    grid.querySelectorAll("[data-icon], [data-type]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const value = btn.dataset.icon || btn.dataset.type;
        currentSelected = value;
        grid.querySelectorAll(".active, .selected").forEach((el) => {
          el.classList.remove("active", "selected");
        });
        btn.classList.add(btn.classList.contains("marker-icon-btn") ? "selected" : "active");
        onSelect(value);
      });
    });
  }

  searchInput.oninput = paintGrid;
  currentSelected = selectedKey;
  paintGrid();

  return {
    setSelected(key) {
      currentSelected = key;
      paintGrid();
    },
    resetSearch() {
      searchInput.value = "";
      paintGrid();
    },
    getSelected() {
      return currentSelected;
    },
  };
}

function renderPoiIconPicker(container, selectedKey, onChange) {
  if (!container) return null;
  const key = normalizePoiIcon(selectedKey);
  const api = setupSearchableIconPicker(container, {
    entries: Object.entries(POI_ICONS),
    selectedKey: key,
    onSelect: onChange,
    gridClass: "icon-picker icon-picker-grid",
    renderOption: (id, icon, active) => `
      <button type="button" class="icon-option${active ? " active" : ""}" data-icon="${id}" title="${escapeHtml(icon.label)}">
        <span class="icon-option-glyph" style="background:${icon.color}">${icon.glyph}</span>
        <span class="icon-option-label">${escapeHtml(icon.label)}</span>
      </button>
    `,
  });
  api?.resetSearch();
  api?.setSelected(key);
  return api;
}
