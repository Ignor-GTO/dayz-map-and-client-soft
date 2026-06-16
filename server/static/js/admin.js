async function api(path, options = {}) {
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

function showLogin() {
  document.getElementById("admin-login").classList.remove("hidden");
  document.getElementById("admin-panel").classList.add("hidden");
}

function showPanel() {
  document.getElementById("admin-login").classList.add("hidden");
  document.getElementById("admin-panel").classList.remove("hidden");
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
  document.getElementById(`tab-${name}`).classList.remove("hidden");
  document.getElementById("admin-panel")?.classList.toggle("admin-radiation-mode", name === "radiation");
  if (name === "radiation" && window.RadiationEditor) {
    window.RadiationEditor.ensureLoaded();
  }
}

function poiIconBadge(iconKey) {
  const key = normalizePoiIcon(iconKey);
  const icon = POI_ICONS[key];
  return `<span class="card-icon" style="background:${icon.color}">${icon.glyph}</span>`;
}

let mapsCache = [];
let poisCache = [];
let selectedPoiIcon = "star";
let poiImageFile = null;
let poiImageRemovePending = false;

function setPoiImagePreview(url) {
  const wrap = document.getElementById("poi-image-preview");
  const img = document.getElementById("poi-image-preview-img");
  if (!wrap || !img) return;
  if (url) {
    img.src = url;
    wrap.classList.remove("hidden");
  } else {
    img.removeAttribute("src");
    wrap.classList.add("hidden");
  }
}

function resetPoiImageState() {
  poiImageFile = null;
  poiImageRemovePending = false;
  const input = document.getElementById("poi-image-file");
  if (input) input.value = "";
  setPoiImagePreview("");
}

async function uploadPoiImage(poiId, file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/api/admin/pois/${poiId}/image`, {
    method: "POST",
    credentials: "same-origin",
    body: fd,
  });
  const data = res.ok ? await res.json().catch(() => ({})) : null;
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (data?.detail) msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    throw new Error(msg);
  }
  return data;
}

async function deletePoiImage(poiId) {
  await api(`/api/admin/pois/${poiId}/image`, { method: "DELETE" });
}

function setPoiIcon(iconKey) {
  selectedPoiIcon = normalizePoiIcon(iconKey);
  document.getElementById("poi-icon").value = selectedPoiIcon;
}

function initPoiIconPicker(iconKey = "star") {
  renderPoiIconPicker(document.getElementById("poi-icon-picker"), iconKey, setPoiIcon);
  setPoiIcon(iconKey);
}

function resetMapForm() {
  const form = document.getElementById("map-form");
  form.reset();
  document.getElementById("map-edit-id").value = "";
  document.getElementById("map-form-title").textContent = "Добавить карту";
  document.getElementById("map-form-submit").textContent = "Добавить карту";
  document.getElementById("map-form-cancel").classList.add("hidden");
  document.getElementById("map-slug").disabled = false;
  form.querySelector('[name="enabled"]').checked = true;
}

function fillMapForm(map) {
  const form = document.getElementById("map-form");
  document.getElementById("map-edit-id").value = String(map.id);
  document.getElementById("map-form-title").textContent = `Редактировать: ${map.name}`;
  document.getElementById("map-form-submit").textContent = "Сохранить карту";
  document.getElementById("map-form-cancel").classList.remove("hidden");
  document.getElementById("map-slug").value = map.slug;
  document.getElementById("map-slug").disabled = true;
  form.querySelector('[name="name"]').value = map.name;
  form.querySelector('[name="map_size"]').value = map.map_size;
  form.querySelector('[name="max_native_zoom"]').value = map.max_native_zoom;
  form.querySelector('[name="extra_zoom"]').value = map.extra_zoom;
  form.querySelector('[name="sort_order"]').value = map.sort_order;
  form.querySelector('[name="tiles_satellite"]').value = map.tiles_satellite;
  form.querySelector('[name="tiles_topographic"]').value = map.tiles_topographic;
  form.querySelector('[name="locations_url"]').value = map.locations_url || "";
  form.querySelector('[name="radiation_url"]').value = map.radiation_url || "";
  form.querySelector('[name="locations_source"]').value = map.locations_source || "izurvive";
  form.querySelector('[name="enabled"]').checked = !!map.enabled;
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetPoiForm() {
  const form = document.getElementById("poi-form");
  form.reset();
  document.getElementById("poi-edit-id").value = "";
  document.getElementById("poi-form-title").textContent = "Добавить метку";
  document.getElementById("poi-form-submit").textContent = "Добавить метку";
  document.getElementById("poi-form-cancel").classList.add("hidden");
  resetPoiImageState();
  initPoiIconPicker("star");
}

function fillPoiForm(poi) {
  const form = document.getElementById("poi-form");
  document.getElementById("poi-edit-id").value = String(poi.id);
  document.getElementById("poi-form-title").textContent = `Редактировать: ${poi.title}`;
  document.getElementById("poi-form-submit").textContent = "Сохранить метку";
  document.getElementById("poi-form-cancel").classList.remove("hidden");
  form.querySelector('[name="title"]').value = poi.title;
  form.querySelector('[name="x"]').value = poi.x;
  form.querySelector('[name="y"]').value = poi.y;
  form.querySelector('[name="description"]').value = poi.description || "";
  resetPoiImageState();
  if (poi.description_image_url) {
    setPoiImagePreview(poi.description_image_url);
  }
  initPoiIconPicker(poi.icon || "star");
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadMaps() {
  mapsCache = await api("/api/admin/maps");
  const list = document.getElementById("maps-list");
  list.innerHTML = mapsCache.map((m) => `
    <div class="card" data-id="${m.id}">
      <div class="card-head">
        <strong>${m.name}</strong>
        <span class="badge ${m.enabled ? "on" : "off"}">${m.enabled ? "вкл" : "выкл"}</span>
      </div>
      <div class="card-meta">slug: ${m.slug} · size: ${m.map_size}</div>
      <div class="card-actions">
        <button type="button" class="secondary edit-map" data-id="${m.id}">Редактировать</button>
        <button type="button" class="secondary toggle-map" data-id="${m.id}">${m.enabled ? "Выключить" : "Включить"}</button>
        <button type="button" class="danger delete-map" data-id="${m.id}">Удалить</button>
      </div>
    </div>
  `).join("");

  const poiSel = document.getElementById("poi-map-select");
  poiSel.innerHTML = mapsCache.map((m) => `<option value="${m.slug}">${m.name}</option>`).join("");

  const pinSel = document.getElementById("pin-map-select");
  if (pinSel) {
    pinSel.innerHTML = mapsCache.map((m) => `<option value="${m.slug}">${m.name}</option>`).join("");
  }

  if (window.RadiationEditor) {
    window.RadiationEditor.refreshMapSelect();
  }
}

async function loadPois() {
  const slug = document.getElementById("poi-map-select").value;
  if (!slug) return;
  poisCache = await api(`/api/admin/pois?map_slug=${encodeURIComponent(slug)}`);
  const list = document.getElementById("pois-list");
  list.innerHTML = poisCache.length
    ? poisCache.map((p) => `
      <div class="card" data-id="${p.id}">
        <div class="card-head"><strong>${poiIconBadge(p.icon)}${p.title}</strong></div>
        <div class="card-meta">${Math.round(p.x)} / ${Math.round(p.y)}</div>
        ${p.description ? `<p class="card-desc">${escapeHtml(p.description)}</p>` : ""}
        ${p.description_image_url ? `<img class="card-poi-image" src="${escapeHtml(p.description_image_url)}" alt="">` : ""}
        <div class="card-actions">
          <button type="button" class="secondary edit-poi" data-id="${p.id}">Редактировать</button>
          <button type="button" class="danger delete-poi" data-id="${p.id}">Удалить</button>
        </div>
      </div>
    `).join("")
    : "<p class='muted'>Нет меток на этой карте</p>";
}

async function loadPinPolicy() {
  const data = await api("/api/admin/settings");
  const cb = document.getElementById("public-pin-creation");
  if (cb) cb.checked = !!data.public_pin_creation;
}

async function loadRooms() {
  const slug = document.getElementById("pin-map-select")?.value;
  if (!slug) return;
  const rooms = await api(`/api/admin/rooms?map_slug=${encodeURIComponent(slug)}`);
  const list = document.getElementById("rooms-list");
  if (!list) return;
  list.innerHTML = rooms.length
    ? rooms.map((r) => `
      <div class="card" data-id="${r.id}">
        <div class="card-head"><strong>PIN: ${r.pin}</strong></div>
        <div class="card-meta">Участников: ${r.user_count}</div>
        <div class="card-actions">
          <button type="button" class="danger delete-room" data-id="${r.id}">Удалить</button>
        </div>
      </div>
    `).join("")
    : "<p class='muted'>Нет групп на этой карте. Создайте PIN ниже.</p>";
}

document.getElementById("pin-policy-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("pin-policy-msg");
  msg?.classList.add("hidden");
  try {
    const enabled = document.getElementById("public-pin-creation").checked;
    await api("/api/admin/settings/pin-policy", {
      method: "PUT",
      body: JSON.stringify({ public_pin_creation: enabled }),
    });
    if (msg) {
      msg.textContent = enabled
        ? "Включено: все могут создавать PIN при входе"
        : "Выключено: только PIN из админки";
      msg.classList.remove("hidden");
    }
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("pin-map-select")?.addEventListener("change", loadRooms);

document.getElementById("pin-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    await api("/api/admin/rooms", {
      method: "POST",
      body: JSON.stringify({
        map_slug: document.getElementById("pin-map-select").value,
        pin: String(fd.get("pin")).trim(),
      }),
    });
    e.target.reset();
    await loadRooms();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("rooms-list")?.addEventListener("click", async (e) => {
  const del = e.target.closest(".delete-room");
  if (!del) return;
  if (!confirm("Удалить группу и всех участников?")) return;
  await api(`/api/admin/rooms/${del.dataset.id}`, { method: "DELETE" });
  await loadRooms();
});

document.getElementById("admin-login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("admin-login-error");
  errEl.classList.add("hidden");
  try {
    await api("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password: document.getElementById("admin-password").value }),
    });
    showPanel();
    initPoiIconPicker("star");
    await loadMaps();
    await loadPois();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
  }
});

document.getElementById("admin-logout").addEventListener("click", async () => {
  await api("/api/admin/logout", { method: "POST" });
  showLogin();
});

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.getElementById("map-form-cancel")?.addEventListener("click", resetMapForm);
document.getElementById("poi-form-cancel")?.addEventListener("click", resetPoiForm);

document.getElementById("map-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const editId = document.getElementById("map-edit-id").value;
  const payload = {
    name: fd.get("name"),
    map_size: Number(fd.get("map_size")),
    tiles_satellite: fd.get("tiles_satellite"),
    tiles_topographic: fd.get("tiles_topographic"),
    locations_url: fd.get("locations_url") || "",
    radiation_url: fd.get("radiation_url") || "",
    locations_source: fd.get("locations_source") || "izurvive",
    max_native_zoom: Number(fd.get("max_native_zoom")),
    extra_zoom: Number(fd.get("extra_zoom")),
    sort_order: Number(fd.get("sort_order")),
    enabled: fd.get("enabled") === "on",
  };
  try {
    if (editId) {
      await api(`/api/admin/maps/${editId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api("/api/admin/maps", {
        method: "POST",
        body: JSON.stringify({
          slug: fd.get("slug"),
          ...payload,
        }),
      });
    }
    resetMapForm();
    await loadMaps();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("maps-list").addEventListener("click", async (e) => {
  const edit = e.target.closest(".edit-map");
  const toggle = e.target.closest(".toggle-map");
  const del = e.target.closest(".delete-map");
  if (edit) {
    const m = mapsCache.find((x) => x.id === Number(edit.dataset.id));
    if (m) fillMapForm(m);
    return;
  }
  if (toggle) {
    const id = Number(toggle.dataset.id);
    const m = mapsCache.find((x) => x.id === id);
    if (!m) return;
    await api(`/api/admin/maps/${id}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: !m.enabled }),
    });
    await loadMaps();
  }
  if (del) {
    if (!confirm("Удалить карту и все её POI?")) return;
    await api(`/api/admin/maps/${del.dataset.id}`, { method: "DELETE" });
    resetMapForm();
    await loadMaps();
    await loadPois();
  }
});

document.getElementById("poi-map-select").addEventListener("change", () => {
  resetPoiForm();
  loadPois();
});

document.getElementById("poi-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const editId = document.getElementById("poi-edit-id").value;
  const payload = {
    title: fd.get("title"),
    description: fd.get("description") || "",
    icon: selectedPoiIcon,
    x: Number(fd.get("x")),
    y: Number(fd.get("y")),
  };
  try {
    let poiId = editId;
    if (editId) {
      await api(`/api/admin/pois/${editId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      const created = await api("/api/admin/pois", {
        method: "POST",
        body: JSON.stringify({
          map_slug: document.getElementById("poi-map-select").value,
          ...payload,
        }),
      });
      poiId = created.id;
    }

    if (poiImageRemovePending && poiId) {
      await deletePoiImage(poiId);
    } else if (poiImageFile && poiId) {
      await uploadPoiImage(poiId, poiImageFile);
    }

    resetPoiForm();
    await loadPois();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("pois-list").addEventListener("click", async (e) => {
  const edit = e.target.closest(".edit-poi");
  const del = e.target.closest(".delete-poi");
  if (edit) {
    const p = poisCache.find((x) => x.id === Number(edit.dataset.id));
    if (p) fillPoiForm(p);
    return;
  }
  if (!del) return;
  if (!confirm("Удалить метку?")) return;
  await api(`/api/admin/pois/${del.dataset.id}`, { method: "DELETE" });
  await loadPois();
});

document.getElementById("poi-image-file")?.addEventListener("change", (e) => {
  const file = e.target.files?.[0];
  poiImageFile = file || null;
  poiImageRemovePending = false;
  if (file) {
    setPoiImagePreview(URL.createObjectURL(file));
  } else if (!document.getElementById("poi-edit-id").value) {
    setPoiImagePreview("");
  }
});

document.getElementById("poi-image-remove")?.addEventListener("click", () => {
  poiImageFile = null;
  poiImageRemovePending = true;
  const input = document.getElementById("poi-image-file");
  if (input) input.value = "";
  setPoiImagePreview("");
});

document.getElementById("password-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const msg = document.getElementById("password-msg");
  msg.classList.add("hidden");
  try {
    await api("/api/admin/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: fd.get("current_password"),
        new_password: fd.get("new_password"),
      }),
    });
    msg.textContent = "Пароль изменён";
    msg.classList.remove("hidden");
    e.target.reset();
  } catch (err) {
    alert(err.message);
  }
});

(async () => {
  try {
    await api("/api/admin/me");
    showPanel();
    initPoiIconPicker("star");
    await loadMaps();
    await loadPois();
    await loadPinPolicy();
    await loadRooms();
  } catch {
    showLogin();
  }
})();
