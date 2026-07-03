(function () {
  const state = {
    mapSlug: "",
    traders: [],
    sections: [],
    subsections: [],
    items: [],
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function selectedNumber(selectId) {
    const raw = byId(selectId)?.value || "";
    const v = Number(raw);
    return Number.isFinite(v) && v > 0 ? v : null;
  }

  function selectedNumbers(selectId) {
    const el = byId(selectId);
    if (!el) return [];
    return Array.from(el.selectedOptions || [])
      .map((o) => Number(o.value))
      .filter((v) => Number.isFinite(v) && v > 0);
  }

  function updateSelectedCount() {
    const count = selectedNumbers("trader-item-list").length;
    const el = byId("trader-item-selected-count");
    if (el) el.textContent = String(count);
  }

  function selectedMapSlug() {
    return String(byId("trader-map-select")?.value || "").trim();
  }

  function renderSimpleSelect(selectId, rows, emptyText = "Нет данных") {
    const el = byId(selectId);
    if (!el) return;
    if (!rows.length) {
      el.innerHTML = "";
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = emptyText;
      el.appendChild(opt);
      el.value = "";
      return;
    }
    el.innerHTML = rows.map((r) => `<option value="${r.id}">${escapeHtml(r.name)}</option>`).join("");
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function loadMaps() {
    const maps = await api("/api/admin/maps");
    const sel = byId("trader-map-select");
    if (!sel) return;
    sel.innerHTML = maps.map((m) => `<option value="${m.slug}">${escapeHtml(m.name)}</option>`).join("");
    if (state.mapSlug && maps.some((m) => m.slug === state.mapSlug)) {
      sel.value = state.mapSlug;
    } else if (maps.length) {
      sel.value = maps[0].slug;
    }
    state.mapSlug = selectedMapSlug();
  }

  async function loadTraders() {
    state.mapSlug = selectedMapSlug();
    if (!state.mapSlug) return;
    state.traders = await api(`/api/admin/traders?map_slug=${encodeURIComponent(state.mapSlug)}`);
    const traderSelect = byId("trader-list");
    if (traderSelect) {
      if (!state.traders.length) {
        traderSelect.innerHTML = `<option value="">Нет торговцев</option>`;
      } else {
        traderSelect.innerHTML = state.traders.map((t) => {
          const loc = (t.x != null && t.y != null) ? ` (${Math.round(t.x)}/${Math.round(t.y)})` : "";
          return `<option value="${t.id}">${escapeHtml(t.name)}${loc}</option>`;
        }).join("");
      }
    }
    await loadSections();
    await loadItems();
  }

  async function loadSections() {
    const traderId = selectedNumber("trader-list");
    if (!traderId) {
      state.sections = [];
      renderSimpleSelect("trader-section-list", [], "Нет разделов");
      await loadSubsections();
      return;
    }
    state.sections = await api(`/api/admin/trader-sections?trader_id=${traderId}`);
    renderSimpleSelect("trader-section-list", state.sections, "Нет разделов");
    await loadSubsections();
  }

  async function loadSubsections() {
    const sectionId = selectedNumber("trader-section-list");
    if (!sectionId) {
      state.subsections = [];
      renderSimpleSelect("trader-subsection-list", [], "Нет подразделов");
      return;
    }
    state.subsections = await api(`/api/admin/trader-subsections?section_id=${sectionId}`);
    renderSimpleSelect("trader-subsection-list", state.subsections, "Нет подразделов");
  }

  function renderItems(items) {
    const list = byId("trader-item-list");
    if (!list) return;
    if (!items.length) {
      list.innerHTML = `<option value="">Нет предметов</option>`;
      return;
    }
    list.innerHTML = items.map((it) => (
      `<option value="${it.id}" data-subsection="${it.subsection_id}" data-section="${it.section_id}" data-trader="${it.trader_id}">
        ${escapeHtml(it.name)} | ${it.buy_price}/${it.sell_price} | ${escapeHtml(it.trader)} / ${escapeHtml(it.section)} / ${escapeHtml(it.subsection)}
      </option>`
    )).join("");
  }

  async function loadItems() {
    state.mapSlug = selectedMapSlug();
    if (!state.mapSlug) return;
    const q = String(byId("trader-item-search-input")?.value || "").trim();
    const params = new URLSearchParams({ map_slug: state.mapSlug });
    if (q) params.set("q", q);
    state.items = await api(`/api/admin/trader-items?${params.toString()}`);
    renderItems(state.items);
    updateSelectedCount();
  }

  async function createTrader() {
    const name = String(byId("trader-name-input")?.value || "").trim();
    if (!name) return alert("Введите название торговца");
    const xVal = String(byId("trader-x-input")?.value || "").trim();
    const yVal = String(byId("trader-y-input")?.value || "").trim();
    const x = xVal === "" ? null : Number(xVal);
    const y = yVal === "" ? null : Number(yVal);
    await api("/api/admin/traders", {
      method: "POST",
      body: JSON.stringify({
        map_slug: selectedMapSlug(),
        name,
        x: Number.isFinite(x) ? x : null,
        y: Number.isFinite(y) ? y : null,
      }),
    });
    byId("trader-name-input").value = "";
    byId("trader-x-input").value = "";
    byId("trader-y-input").value = "";
    await loadTraders();
  }

  async function updateTrader() {
    const traderId = selectedNumber("trader-list");
    if (!traderId) return alert("Сначала выберите торговца");
    const name = String(byId("trader-name-input")?.value || "").trim();
    const xVal = String(byId("trader-x-input")?.value || "").trim();
    const yVal = String(byId("trader-y-input")?.value || "").trim();
    const payload = {};
    if (name) payload.name = name;
    if (xVal !== "") {
      const x = Number(xVal);
      if (!Number.isFinite(x)) return alert("Некорректная координата X");
      payload.x = x;
    }
    if (yVal !== "") {
      const y = Number(yVal);
      if (!Number.isFinite(y)) return alert("Некорректная координата Y");
      payload.y = y;
    }
    await api(`/api/admin/traders/${traderId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadTraders();
  }

  async function createSection() {
    const traderId = selectedNumber("trader-list");
    if (!traderId) return alert("Сначала выберите торговца");
    const name = String(byId("trader-section-name-input")?.value || "").trim();
    if (!name) return alert("Введите название раздела");
    await api("/api/admin/trader-sections", {
      method: "POST",
      body: JSON.stringify({ trader_id: traderId, name }),
    });
    byId("trader-section-name-input").value = "";
    await loadSections();
    await loadItems();
  }

  async function createSubsection() {
    const sectionId = selectedNumber("trader-section-list");
    if (!sectionId) return alert("Сначала выберите раздел");
    const name = String(byId("trader-subsection-name-input")?.value || "").trim();
    if (!name) return alert("Введите название подраздела");
    await api("/api/admin/trader-subsections", {
      method: "POST",
      body: JSON.stringify({ section_id: sectionId, name }),
    });
    byId("trader-subsection-name-input").value = "";
    await loadSubsections();
    await loadItems();
  }

  async function createItem() {
    const subsectionId = selectedNumber("trader-subsection-list");
    if (!subsectionId) return alert("Сначала выберите подраздел");
    const name = String(byId("trader-item-name-input")?.value || "").trim();
    if (!name) return alert("Введите название предмета");
    const buy = Number(byId("trader-item-buy-input")?.value || 0);
    const sell = Number(byId("trader-item-sell-input")?.value || 0);
    await api("/api/admin/trader-items", {
      method: "POST",
      body: JSON.stringify({
        subsection_id: subsectionId,
        name,
        buy_price: Number.isFinite(buy) ? buy : 0,
        sell_price: Number.isFinite(sell) ? sell : 0,
      }),
    });
    await loadItems();
  }

  async function updateItem() {
    const itemId = selectedNumber("trader-item-list");
    if (!itemId) return alert("Выберите предмет в списке");
    const subsectionId = selectedNumber("trader-subsection-list");
    if (!subsectionId) return alert("Выберите подраздел");
    const name = String(byId("trader-item-name-input")?.value || "").trim();
    const buy = Number(byId("trader-item-buy-input")?.value || 0);
    const sell = Number(byId("trader-item-sell-input")?.value || 0);
    await api(`/api/admin/trader-items/${itemId}`, {
      method: "PUT",
      body: JSON.stringify({
        subsection_id: subsectionId,
        name: name || null,
        buy_price: Number.isFinite(buy) ? buy : 0,
        sell_price: Number.isFinite(sell) ? sell : 0,
      }),
    });
    await loadItems();
  }

  async function deleteSelected(endpointBase, selectId, confirmText) {
    const id = selectedNumber(selectId);
    if (!id) return;
    if (!confirm(confirmText)) return;
    await api(`${endpointBase}/${id}`, { method: "DELETE" });
  }

  async function deleteSelectedItemsBulk() {
    const ids = selectedNumbers("trader-item-list");
    if (!ids.length) return alert("Выберите один или несколько предметов в списке");
    const word = ids.length === 1 ? "предмет" : "предметов";
    if (!confirm(`Удалить выбранные ${ids.length} ${word}? Это действие необратимо.`)) return;
    const result = await api("/api/admin/trader-items/delete-bulk", {
      method: "POST",
      body: JSON.stringify(ids),
    });
    const status = byId("trader-import-status");
    if (status) {
      status.textContent = `Удалено предметов: ${result.deleted ?? ids.length}`;
      status.classList.remove("hidden");
    }
    await loadItems();
  }

  async function importJson() {
    const raw = String(byId("trader-import-json")?.value || "").trim();
    if (!raw) return alert("Вставьте JSON-массив");
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return alert("Некорректный JSON");
    }
    if (!Array.isArray(parsed)) return alert("JSON должен быть массивом");
    const result = await api("/api/admin/trader-items/import-json", {
      method: "POST",
      body: JSON.stringify({ map_slug: selectedMapSlug(), items: parsed }),
    });
    const status = byId("trader-import-status");
    if (status) {
      status.textContent = `Импорт: создано ${result.created}, обновлено ${result.updated}, всего ${result.total}`;
      status.classList.remove("hidden");
    }
    await loadTraders();
  }

  function bindEvents() {
    byId("trader-map-select")?.addEventListener("change", () => loadTraders().catch((e) => alert(e.message)));
    byId("trader-list")?.addEventListener("change", () => loadSections().then(loadItems).catch((e) => alert(e.message)));
    byId("trader-section-list")?.addEventListener("change", () => loadSubsections().then(loadItems).catch((e) => alert(e.message)));
    byId("trader-subsection-list")?.addEventListener("change", () => loadItems().catch((e) => alert(e.message)));
    byId("trader-item-search-input")?.addEventListener("input", () => loadItems().catch((e) => alert(e.message)));

    byId("trader-create-btn")?.addEventListener("click", () => createTrader().catch((e) => alert(e.message)));
    byId("trader-update-btn")?.addEventListener("click", () => updateTrader().catch((e) => alert(e.message)));
    byId("trader-section-create-btn")?.addEventListener("click", () => createSection().catch((e) => alert(e.message)));
    byId("trader-subsection-create-btn")?.addEventListener("click", () => createSubsection().catch((e) => alert(e.message)));
    byId("trader-item-create-btn")?.addEventListener("click", () => createItem().catch((e) => alert(e.message)));
    byId("trader-item-update-btn")?.addEventListener("click", () => updateItem().catch((e) => alert(e.message)));
    byId("trader-import-btn")?.addEventListener("click", () => importJson().catch((e) => alert(e.message)));

    byId("trader-delete-btn")?.addEventListener("click", async () => {
      await deleteSelected("/api/admin/traders", "trader-list", "Удалить торговца и всё содержимое?");
      await loadTraders();
    });
    byId("trader-section-delete-btn")?.addEventListener("click", async () => {
      await deleteSelected("/api/admin/trader-sections", "trader-section-list", "Удалить раздел и его подразделы?");
      await loadSections();
      await loadItems();
    });
    byId("trader-subsection-delete-btn")?.addEventListener("click", async () => {
      await deleteSelected("/api/admin/trader-subsections", "trader-subsection-list", "Удалить подраздел и его предметы?");
      await loadSubsections();
      await loadItems();
    });
    byId("trader-item-delete-btn")?.addEventListener("click", () => {
      deleteSelectedItemsBulk().catch((e) => alert(e.message));
    });

    byId("trader-item-select-all-btn")?.addEventListener("click", () => {
      const list = byId("trader-item-list");
      if (!list) return;
      Array.from(list.options).forEach((o) => { o.selected = true; });
      updateSelectedCount();
    });

    byId("trader-item-select-none-btn")?.addEventListener("click", () => {
      const list = byId("trader-item-list");
      if (!list) return;
      Array.from(list.options).forEach((o) => { o.selected = false; });
      updateSelectedCount();
    });

    byId("trader-item-list")?.addEventListener("change", () => {
      updateSelectedCount();
      const ids = selectedNumbers("trader-item-list");
      if (ids.length !== 1) return;
      const item = state.items.find((x) => x.id === ids[0]);
      if (!item) return;
      byId("trader-item-name-input").value = item.name;
      byId("trader-item-buy-input").value = String(item.buy_price ?? 0);
      byId("trader-item-sell-input").value = String(item.sell_price ?? 0);
    });

    byId("trader-list")?.addEventListener("change", () => {
      const traderId = selectedNumber("trader-list");
      const trader = state.traders.find((x) => x.id === traderId);
      if (!trader) return;
      byId("trader-name-input").value = trader.name || "";
      byId("trader-x-input").value = trader.x ?? "";
      byId("trader-y-input").value = trader.y ?? "";
    });
  }

  async function init() {
    if (!byId("tab-traders")) return;
    try {
      await api("/api/admin/me");
    } catch {
      return;
    }
    bindEvents();
    await loadMaps();
    await loadTraders();
  }

  window.addEventListener("DOMContentLoaded", () => {
    init().catch((err) => {
      console.error("traders admin init failed", err);
    });
  });
})();
