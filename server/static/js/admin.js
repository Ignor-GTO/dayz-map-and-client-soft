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
}

let mapsCache = [];

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
        <button type="button" class="secondary toggle-map" data-id="${m.id}">${m.enabled ? "Выключить" : "Включить"}</button>
        <button type="button" class="danger delete-map" data-id="${m.id}">Удалить</button>
      </div>
    </div>
  `).join("");

  const poiSel = document.getElementById("poi-map-select");
  poiSel.innerHTML = mapsCache.map((m) => `<option value="${m.slug}">${m.name}</option>`).join("");
}

async function loadPois() {
  const slug = document.getElementById("poi-map-select").value;
  if (!slug) return;
  const pois = await api(`/api/admin/pois?map_slug=${encodeURIComponent(slug)}`);
  const list = document.getElementById("pois-list");
  list.innerHTML = pois.length
    ? pois.map((p) => `
      <div class="card" data-id="${p.id}">
        <div class="card-head"><strong>${p.title}</strong></div>
        <div class="card-meta">${Math.round(p.x)} / ${Math.round(p.y)}</div>
        ${p.description ? `<p class="card-desc">${p.description}</p>` : ""}
        <div class="card-actions">
          <button type="button" class="danger delete-poi" data-id="${p.id}">Удалить</button>
        </div>
      </div>
    `).join("")
    : "<p class='muted'>Нет меток на этой карте</p>";
}

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

document.getElementById("map-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = {
    slug: fd.get("slug"),
    name: fd.get("name"),
    map_size: Number(fd.get("map_size")),
    tiles_satellite: fd.get("tiles_satellite"),
    tiles_topographic: fd.get("tiles_topographic"),
    max_native_zoom: Number(fd.get("max_native_zoom")),
    extra_zoom: Number(fd.get("extra_zoom")),
    sort_order: Number(fd.get("sort_order")),
    enabled: fd.get("enabled") === "on",
  };
  try {
    await api("/api/admin/maps", { method: "POST", body: JSON.stringify(payload) });
    e.target.reset();
    await loadMaps();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("maps-list").addEventListener("click", async (e) => {
  const toggle = e.target.closest(".toggle-map");
  const del = e.target.closest(".delete-map");
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
    await loadMaps();
    await loadPois();
  }
});

document.getElementById("poi-map-select").addEventListener("change", loadPois);

document.getElementById("poi-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = {
    map_slug: document.getElementById("poi-map-select").value,
    title: fd.get("title"),
    description: fd.get("description") || "",
    x: Number(fd.get("x")),
    y: Number(fd.get("y")),
  };
  try {
    await api("/api/admin/pois", { method: "POST", body: JSON.stringify(payload) });
    e.target.reset();
    await loadPois();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("pois-list").addEventListener("click", async (e) => {
  const del = e.target.closest(".delete-poi");
  if (!del) return;
  if (!confirm("Удалить метку?")) return;
  await api(`/api/admin/pois/${del.dataset.id}`, { method: "DELETE" });
  await loadPois();
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
    await loadMaps();
    await loadPois();
  } catch {
    showLogin();
  }
})();
