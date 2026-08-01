/** Shared map-user profile toolbar + modal (index, traders, …). */
(function () {
  "use strict";

  const DEFAULT_AVATAR_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
    '<circle cx="32" cy="32" r="32" fill="#2a3848"/>' +
    '<circle cx="32" cy="24" r="11" fill="#8b9cb3"/>' +
    '<path d="M12 54c3.5-11 11.5-17 20-17s16.5 6 20 17" fill="#8b9cb3"/>' +
    "</svg>";
  const DEFAULT_AVATAR_URL = `data:image/svg+xml,${encodeURIComponent(DEFAULT_AVATAR_SVG)}`;
  const DEFAULT_AVATAR_FILE_URL = "/img/default-avatar.svg?v=2";
  let hooks = {};
  let bound = false;
  let activeProfileTab = "settings";

  async function api(path, options = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = res.ok ? await res.json().catch(() => ({})) : null;
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      if (data?.detail) {
        msg = Array.isArray(data.detail)
          ? data.detail.map((d) => d.msg || d).join(", ")
          : data.detail;
      }
      throw new Error(msg);
    }
    return data;
  }

  function getUser() {
    return hooks.getUser?.() ?? null;
  }

  function setUser(user) {
    hooks.setUser?.(user);
  }

  function resolveAvatarUrl(url) {
    return url || DEFAULT_AVATAR_FILE_URL;
  }

  function setAvatarImage(img, url) {
    if (!img) return;
    img.onerror = () => {
      img.onerror = null;
      img.src = DEFAULT_AVATAR_URL;
    };
    img.src = url;
  }

  function syncAdminPanelLink() {
    const me = getUser();
    const link = document.getElementById("admin-panel-link");
    if (!link) return;
    const show = !!(
      me &&
      (me.can_access_admin_panel ||
        me.role === "admin" ||
        me.role === "moderator")
    );
    link.classList.toggle("hidden", !show);
  }

  function syncAvatarUi() {
    const me = getUser();
    const url = me ? resolveAvatarUrl(me.avatar_url) : DEFAULT_AVATAR_FILE_URL;
    setAvatarImage(document.getElementById("toolbar-avatar"), url);
    setAvatarImage(document.getElementById("profile-avatar-preview"), url);
    document.getElementById("profile-avatar-remove-btn")?.classList.toggle("hidden", !me?.avatar_url);
    syncAdminPanelLink();
  }

  function setToolbarVisible(visible) {
    document.getElementById("profile-btn")?.classList.toggle("hidden", !visible);
    document.getElementById("logout-btn")?.classList.toggle("hidden", !visible);
    if (!visible) syncAdminPanelLink();
  }

  function closeProfileModal() {
    document.getElementById("profile-modal")?.classList.add("hidden");
  }

  function setProfileTab(tabId) {
    activeProfileTab = tabId === "maps" ? "maps" : "settings";
    document.querySelectorAll(".profile-tab").forEach((btn) => {
      const active = btn.getAttribute("data-profile-tab") === activeProfileTab;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll(".profile-tab-panel").forEach((panel) => {
      const active = panel.getAttribute("data-profile-panel") === activeProfileTab;
      panel.classList.toggle("is-active", active);
      if (active) panel.removeAttribute("hidden");
      else panel.setAttribute("hidden", "");
    });
  }

  function renderMemberships(me) {
    const list = document.getElementById("profile-memberships-list");
    if (!list) return;
    const rows = Array.isArray(me?.memberships) ? me.memberships : [];
    if (!rows.length) {
      list.innerHTML = `<div class="list-empty">Пока только текущая группа. Войдите на другую карту с тем же ником и паролем профиля — она появится здесь.</div>`;
      return;
    }
    list.innerHTML = rows
      .map((m) => {
        const current = !!m.is_current;
        const label = `${escapeHtml(m.map_name)}`;
        const meta = `PIN ${escapeHtml(m.pin)} · ${escapeHtml(m.nickname || "")}`;
        const btn = current
          ? `<span class="profile-membership-badge">Сейчас</span>`
          : `<button type="button" class="profile-membership-go" data-user-id="${m.user_id}">Перейти</button>`;
        return `
          <div class="profile-membership-row${current ? " is-current" : ""}">
            <div class="profile-membership-main">
              <div class="profile-membership-title">${label}</div>
              <div class="profile-membership-meta">${meta}</div>
            </div>
            ${btn}
          </div>`;
      })
      .join("");
  }

  function escapeHtml(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function switchMembership(userId) {
    const data = await api("/api/auth/switch-membership", {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    });
    setUser(data);
    closeProfileModal();
    if (typeof hooks.onSwitchMembership === "function") {
      await hooks.onSwitchMembership(data);
    } else {
      const slug = data.map_slug || "";
      window.location.href = slug ? `/?map=${encodeURIComponent(slug)}` : "/";
    }
  }

  function populateProfileModal() {
    const me = getUser();
    if (!me) return;

    document.getElementById("profile-nickname").textContent = me.nickname;
    document.getElementById("profile-room-info").textContent =
      `${me.map_name} · PIN: ${me.pin}`;
    const steamEl = document.getElementById("profile-steam-info");
    if (steamEl) {
      steamEl.textContent = me.steam_id
        ? `Steam ID: ${me.steam_id}`
        : "Steam ID: не привязан";
    }
    const steamInput = document.getElementById("profile-steam-id");
    if (steamInput) steamInput.value = me.steam_id || "";
    document.getElementById("profile-clear-steam-btn")?.classList.toggle("hidden", !me.steam_id);
    document.getElementById("profile-steam-error")?.classList.add("hidden");
    syncAvatarUi();
    document.getElementById("profile-avatar-error")?.classList.add("hidden");
    renderMemberships(me);

    const hasPassword = !!me.has_profile_password;
    document.getElementById("profile-password-status").textContent = hasPassword
      ? "Пароль общий для всех карт. Без него никто не войдёт под вашим ником в защищённых группах."
      : "Пароль не задан. Задайте его, чтобы связать один профиль на разных картах.";
    document.getElementById("profile-current-password-wrap").classList.toggle("hidden", !hasPassword);
    document.getElementById("profile-remove-password-btn").classList.toggle("hidden", !hasPassword);
    document.getElementById("profile-new-password-label").textContent = hasPassword
      ? "Новый пароль"
      : "Задать пароль";
    document.getElementById("profile-current-password").value = "";
    document.getElementById("profile-new-password").value = "";
    document.getElementById("profile-password-error").classList.add("hidden");

    const roomSection = document.getElementById("room-settings-section");
    if (roomSection) {
      if (me.can_manage_room) {
        roomSection.classList.remove("hidden");
        document.getElementById("room-settings-pin").value = me.pin;
        document.getElementById("room-settings-current-password").value = "";
        document.getElementById("room-settings-entry-password").value = "";
        document.getElementById("room-settings-remove-entry-password").checked = false;
        document.getElementById("room-settings-current-password-wrap").classList.toggle(
          "hidden",
          !me.room_entry_password_enabled
        );
        document.getElementById("room-settings-error").classList.add("hidden");
      } else {
        roomSection.classList.add("hidden");
      }
    }
  }

  function openProfileModal(tabId = "settings") {
    if (!getUser()) return;
    populateProfileModal();
    setProfileTab(tabId);
    document.getElementById("profile-modal")?.classList.remove("hidden");
  }

  async function saveProfileSteamId(clear = false) {
    const errEl = document.getElementById("profile-steam-error");
    errEl?.classList.add("hidden");
    try {
      let data;
      const steam_id = clear ? "" : (document.getElementById("profile-steam-id")?.value.trim() || "");
      if (clear || !steam_id) {
        data = await api("/api/auth/profile/steam-id", { method: "DELETE" });
      } else {
        data = await api("/api/auth/profile/steam-id", {
          method: "PUT",
          body: JSON.stringify({ steam_id }),
        });
      }
      const me = { ...getUser(), steam_id: data.steam_id || null };
      setUser(me);
      populateProfileModal();
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message;
        errEl.classList.remove("hidden");
      }
    }
  }

  async function saveProfilePassword(remove = false) {
    const errEl = document.getElementById("profile-password-error");
    errEl.classList.add("hidden");
    try {
      const data = await api("/api/auth/profile/password", {
        method: "PUT",
        body: JSON.stringify({
          current_password: document.getElementById("profile-current-password").value || null,
          new_password: remove ? "" : document.getElementById("profile-new-password").value || null,
        }),
      });
      const me = { ...getUser(), has_profile_password: !!data.has_profile_password };
      setUser(me);
      alert(data.message);
      populateProfileModal();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  }

  async function saveRoomSettings() {
    const me = getUser();
    const errEl = document.getElementById("room-settings-error");
    errEl.classList.add("hidden");
    try {
      const newPin = document.getElementById("room-settings-pin").value.trim();
      const data = await api("/api/room/settings", {
        method: "PUT",
        body: JSON.stringify({
          new_pin: newPin !== me.pin ? newPin : null,
          current_room_password: document.getElementById("room-settings-current-password").value || null,
          new_entry_password: document.getElementById("room-settings-entry-password").value || null,
          remove_entry_password: document.getElementById("room-settings-remove-entry-password").checked,
        }),
      });
      setUser({
        ...me,
        pin: data.pin,
        room_entry_password_enabled: !!data.entry_password_enabled,
      });
      hooks.onRoomPinChange?.(data.pin);
      alert("Настройки группы сохранены.");
      populateProfileModal();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  }

  async function uploadProfileAvatar(file) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/auth/profile/avatar", {
      method: "POST",
      credentials: "same-origin",
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    setUser({ ...getUser(), avatar_url: data.avatar_url });
    syncAvatarUi();
  }

  async function removeProfileAvatar() {
    const errEl = document.getElementById("profile-avatar-error");
    errEl.classList.add("hidden");
    try {
      await api("/api/auth/profile/avatar", { method: "DELETE" });
      setUser({ ...getUser(), avatar_url: null });
      syncAvatarUi();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  }

  function bindEvents() {
    if (bound) return;
    bound = true;

    document.getElementById("profile-btn")?.addEventListener("click", () => openProfileModal("settings"));
    document.getElementById("close-profile-modal")?.addEventListener("click", closeProfileModal);
    document.getElementById("profile-modal")?.addEventListener("click", (e) => {
      if (e.target.id === "profile-modal") closeProfileModal();
    });
    document.querySelector(".profile-tabs")?.addEventListener("click", (e) => {
      const tab = e.target.closest(".profile-tab");
      if (!tab) return;
      setProfileTab(tab.getAttribute("data-profile-tab"));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      const modal = document.getElementById("profile-modal");
      if (modal && !modal.classList.contains("hidden")) closeProfileModal();
    });
    document.getElementById("profile-save-password-btn")?.addEventListener("click", () => {
      saveProfilePassword(false);
    });
    document.getElementById("profile-remove-password-btn")?.addEventListener("click", () => {
      if (!confirm("Отключить пароль профиля? Вход снова будет только по PIN и никнейму.")) return;
      saveProfilePassword(true);
    });
    document.getElementById("profile-save-steam-btn")?.addEventListener("click", () => {
      saveProfileSteamId(false);
    });
    document.getElementById("profile-clear-steam-btn")?.addEventListener("click", () => {
      if (!confirm("Отвязать Steam ID от профиля?")) return;
      saveProfileSteamId(true);
    });
    document.getElementById("room-settings-save-btn")?.addEventListener("click", saveRoomSettings);
    document.getElementById("profile-avatar-input")?.addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      const errEl = document.getElementById("profile-avatar-error");
      try {
        await uploadProfileAvatar(file);
      } catch (err) {
        if (errEl) {
          errEl.textContent = err.message;
          errEl.classList.remove("hidden");
        }
      }
    });
    document.getElementById("profile-avatar-remove-btn")?.addEventListener("click", async () => {
      if (!getUser()?.avatar_url) return;
      if (!confirm("Удалить фото профиля?")) return;
      await removeProfileAvatar();
    });
    document.getElementById("profile-memberships-list")?.addEventListener("click", async (e) => {
      const btn = e.target.closest(".profile-membership-go");
      if (!btn) return;
      const userId = Number(btn.getAttribute("data-user-id"));
      if (!userId) return;
      try {
        await switchMembership(userId);
      } catch (err) {
        alert(err.message || "Не удалось переключить группу");
      }
    });
    document.getElementById("logout-btn")?.addEventListener("click", async () => {
      await api("/api/auth/logout", { method: "POST" });
      setUser(null);
      setToolbarVisible(false);
      hooks.onLogout?.();
    });
  }

  async function refreshSession() {
    bindEvents();
    syncAvatarUi();
    try {
      const me = await api("/api/auth/me");
      setUser(me);
      syncAvatarUi();
      setToolbarVisible(true);
      return me;
    } catch {
      setUser(null);
      setToolbarVisible(false);
      syncAvatarUi();
      return null;
    }
  }

  function avatarImgHtml(url, size = 24, className = "user-avatar") {
    const src = resolveAvatarUrl(url);
    const fallback = DEFAULT_AVATAR_URL.replace(/"/g, "&quot;");
    return `<img class="${className}" src="${src.replace(/"/g, "&quot;")}" alt="" width="${size}" height="${size}" loading="lazy" onerror="this.onerror=null;this.src='${fallback}'">`;
  }

  window.ProfileUi = {
    init(options = {}) {
      hooks = options;
      bindEvents();
      return refreshSession();
    },
    refreshSession,
    syncAvatarUi,
    syncAdminPanelLink,
    setToolbarVisible,
    openProfileModal,
    resolveAvatarUrl,
    avatarImgHtml,
    DEFAULT_AVATAR_URL,
  };
})();
