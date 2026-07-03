async function tradersApi(path, options = {}) {
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

let tradersMaps = [];
let allItems = [];
let filterTimer = null;

function renderTraderRows(items) {
  const body = document.getElementById("traders-table-body");
  if (!body) return;
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="7" class="muted">Ничего не найдено</td></tr>`;
    return;
  }
  body.innerHTML = items.map((it) => `
    <tr>
      <td><strong>${escapeHtml(it.name)}</strong></td>
      <td>${escapeHtml(it.trader)}</td>
      <td>${it.trader_x != null && it.trader_y != null ? `${Math.round(it.trader_x)} / ${Math.round(it.trader_y)}` : "—"}</td>
      <td>${escapeHtml(it.section)}</td>
      <td>${escapeHtml(it.subsection)}</td>
      <td>${Number(it.buy_price || 0)}</td>
      <td>${Number(it.sell_price || 0)}</td>
    </tr>
  `).join("");
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function byId(id) {
  return document.getElementById(id);
}

async function loadMaps() {
  tradersMaps = await tradersApi("/api/maps");
  const sel = byId("traders-map-select");
  if (!sel) return;
  sel.innerHTML = tradersMaps.map((m) => `<option value="${m.slug}">${escapeHtml(m.name)}</option>`).join("");
}

function uniqueSorted(values) {
  return Array.from(new Set(values.filter((v) => v))).sort((a, b) => a.localeCompare(b, "ru"));
}

function fillSelect(selectId, values, currentValue) {
  const sel = byId(selectId);
  if (!sel) return;
  const options = ['<option value="">Все</option>', ...values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`)];
  sel.innerHTML = options.join("");
  sel.value = values.includes(currentValue) ? currentValue : "";
}

function rebuildDependentFilters() {
  const traderSel = byId("traders-trader-select");
  const sectionSel = byId("traders-section-select");
  const subsectionSel = byId("traders-subsection-select");
  if (!traderSel || !sectionSel || !subsectionSel) return;

  const currentTrader = traderSel.value;
  const currentSection = sectionSel.value;
  const currentSubsection = subsectionSel.value;

  fillSelect("traders-trader-select", uniqueSorted(allItems.map((it) => it.trader)), currentTrader);

  const bySectionPool = currentTrader ? allItems.filter((it) => it.trader === currentTrader) : allItems;
  fillSelect("traders-section-select", uniqueSorted(bySectionPool.map((it) => it.section)), currentSection);

  const bySubsectionPool = bySectionPool.filter((it) => !sectionSel.value || it.section === sectionSel.value);
  fillSelect("traders-subsection-select", uniqueSorted(bySubsectionPool.map((it) => it.subsection)), currentSubsection);
}

function applyFilters() {
  const q = (byId("traders-search-input")?.value || "").trim().toLowerCase();
  const trader = byId("traders-trader-select")?.value || "";
  const section = byId("traders-section-select")?.value || "";
  const subsection = byId("traders-subsection-select")?.value || "";
  const buyMin = parseFloat(byId("traders-buy-min")?.value ?? "");
  const buyMax = parseFloat(byId("traders-buy-max")?.value ?? "");
  const sellMin = parseFloat(byId("traders-sell-min")?.value ?? "");
  const sellMax = parseFloat(byId("traders-sell-max")?.value ?? "");

  const filtered = allItems.filter((it) => {
    if (q && !String(it.name || "").toLowerCase().includes(q)) return false;
    if (trader && it.trader !== trader) return false;
    if (section && it.section !== section) return false;
    if (subsection && it.subsection !== subsection) return false;
    if (Number.isFinite(buyMin) && Number(it.buy_price || 0) < buyMin) return false;
    if (Number.isFinite(buyMax) && Number(it.buy_price || 0) > buyMax) return false;
    if (Number.isFinite(sellMin) && Number(it.sell_price || 0) < sellMin) return false;
    if (Number.isFinite(sellMax) && Number(it.sell_price || 0) > sellMax) return false;
    return true;
  });

  renderTraderRows(filtered);
  const meta = byId("traders-meta");
  if (meta) meta.textContent = `Найдено: ${filtered.length}`;
}

function onFilterChanged({ rebuildCascade = false } = {}) {
  if (rebuildCascade) rebuildDependentFilters();
  applyFilters();
}

function resetFilters() {
  const ids = [
    "traders-search-input",
    "traders-buy-min",
    "traders-buy-max",
    "traders-sell-min",
    "traders-sell-max",
  ];
  ids.forEach((id) => {
    const el = byId(id);
    if (el) el.value = "";
  });
  ["traders-trader-select", "traders-section-select", "traders-subsection-select"].forEach((id) => {
    const el = byId(id);
    if (el) el.value = "";
  });
  rebuildDependentFilters();
  applyFilters();
}

async function loadItems() {
  const sel = byId("traders-map-select");
  const meta = byId("traders-meta");
  if (!sel) return;
  const slug = sel.value;
  if (!slug) {
    allItems = [];
    rebuildDependentFilters();
    renderTraderRows([]);
    if (meta) meta.textContent = "Найдено: 0";
    return;
  }
  const params = new URLSearchParams({ limit: "20000" });
  allItems = await tradersApi(`/api/maps/${encodeURIComponent(slug)}/traders/items?${params.toString()}`);
  rebuildDependentFilters();
  applyFilters();
}

window.addEventListener("DOMContentLoaded", async () => {
  try {
    await loadMaps();
    await loadItems();
  } catch (err) {
    const body = document.getElementById("traders-table-body");
    if (body) {
      body.innerHTML = `<tr><td colspan="7" class="error">${escapeHtml(err.message || String(err))}</td></tr>`;
    }
  }

  byId("traders-map-select")?.addEventListener("change", () => {
    loadItems().catch(() => {});
  });

  byId("traders-search-input")?.addEventListener("input", () => {
    if (filterTimer) clearTimeout(filterTimer);
    filterTimer = setTimeout(() => onFilterChanged(), 120);
  });

  ["traders-buy-min", "traders-buy-max", "traders-sell-min", "traders-sell-max"].forEach((id) => {
    byId(id)?.addEventListener("input", () => {
      if (filterTimer) clearTimeout(filterTimer);
      filterTimer = setTimeout(() => onFilterChanged(), 150);
    });
  });

  byId("traders-trader-select")?.addEventListener("change", () => {
    const sectionSel = byId("traders-section-select");
    const subsectionSel = byId("traders-subsection-select");
    if (sectionSel) sectionSel.value = "";
    if (subsectionSel) subsectionSel.value = "";
    onFilterChanged({ rebuildCascade: true });
  });

  byId("traders-section-select")?.addEventListener("change", () => {
    const subsectionSel = byId("traders-subsection-select");
    if (subsectionSel) subsectionSel.value = "";
    onFilterChanged({ rebuildCascade: true });
  });

  byId("traders-subsection-select")?.addEventListener("change", () => {
    onFilterChanged();
  });

  byId("traders-reset-btn")?.addEventListener("click", () => {
    resetFilters();
  });
});
