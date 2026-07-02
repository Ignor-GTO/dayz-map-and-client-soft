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
let tradersTimer = null;

function renderTraderRows(items) {
  const body = document.getElementById("traders-table-body");
  if (!body) return;
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="6" class="muted">Ничего не найдено</td></tr>`;
    return;
  }
  body.innerHTML = items.map((it) => `
    <tr>
      <td><strong>${escapeHtml(it.name)}</strong></td>
      <td>${escapeHtml(it.trader)}</td>
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

async function loadMaps() {
  tradersMaps = await tradersApi("/api/maps");
  const sel = document.getElementById("traders-map-select");
  if (!sel) return;
  sel.innerHTML = tradersMaps.map((m) => `<option value="${m.slug}">${m.name}</option>`).join("");
}

async function loadItems() {
  const sel = document.getElementById("traders-map-select");
  const input = document.getElementById("traders-search-input");
  const meta = document.getElementById("traders-meta");
  if (!sel) return;
  const slug = sel.value;
  if (!slug) {
    renderTraderRows([]);
    if (meta) meta.textContent = "Найдено: 0";
    return;
  }
  const q = (input?.value || "").trim();
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  params.set("limit", "500");
  const items = await tradersApi(`/api/maps/${encodeURIComponent(slug)}/traders/items?${params.toString()}`);
  renderTraderRows(items);
  if (meta) meta.textContent = `Найдено: ${items.length}`;
}

window.addEventListener("DOMContentLoaded", async () => {
  try {
    await loadMaps();
    await loadItems();
  } catch (err) {
    const body = document.getElementById("traders-table-body");
    if (body) {
      body.innerHTML = `<tr><td colspan="6" class="error">${escapeHtml(err.message || String(err))}</td></tr>`;
    }
  }

  document.getElementById("traders-map-select")?.addEventListener("change", () => {
    loadItems().catch(() => {});
  });

  document.getElementById("traders-search-input")?.addEventListener("input", () => {
    if (tradersTimer) clearTimeout(tradersTimer);
    tradersTimer = setTimeout(() => {
      loadItems().catch(() => {});
    }, 120);
  });
});
