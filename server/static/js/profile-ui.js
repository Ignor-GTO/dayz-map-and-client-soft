/** Shared map-user profile toolbar + modal (index, traders, …). */
(function () {
  "use strict";

  const DEFAULT_AVATAR_URL = "/img/default-avatar.svg";
  let hooks = {};
  let bound = false;

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
    return url || DEFAULT_AVATAR_URL;
  }

  function syncAvatarUi() {
    const me = getUser();
    if (!me) return;
    const url = resolveAvatarUrl(me.avatar_url);
    const toolbarAvatar = document.getElementById("toolbar-avatar");
    const previewAvatar = document.getElementById("profile-avatar-preview");
    if (toolbarAvatar) toolbarAvatar.src = url;
    if (previewAvatar) previewAvatar.src = url;
    document.getElementById("profile-avatar-remove-btn")?.classList.toggle("hidden", !me.avatar_url);
  }

  function setToolbarVisible(visible) {
    document.getElementById("profile-btn")?.classList.toggle("hidden", !visible);
    document.getElementById("logout-btn")?.classList.toggle("hidden", !visible);
  }

  function openProfileModal() {
    const me = getUser();
    if (!me) return;
    const modal = document.getElementById("profile-modal");
    if (!modal) return;

    document.getElementById("profile-nickname").textContent = me.nickname;
    document.getElementById("profile-room-info").textContent =
      `${me.map_name} · PIN: ${me.pin}`;
    syncAvatarUi();
    document.getElementById("profile-avatar-error")?.classList.add("hidden");

    const hasPassword = !!me.has_profile_password;
    document.getElementById("profile-password-status").textContent = hasPassword
      ? "Пароль включён — без него никто не войдёт под вашим никнеймом."
      : "Пароль не задан — вход только по PIN и никнейму.";
    document.getElementById("profile-current-password-wrap").classList.toggle("hidden", !hasPassword);
    document.getElementById("profile-remove-password-btn").classList.toggle("hidden", !hasPassword);
    document.getElementById("profile-new-password-label").textContent = hasPassword
      ? "Новый пароль"
      : "Задать пароль";
    document.getElementById("profile-current-password").value = "";
    document.getElementById("profile-new-password").value = "";
    document.getElementById("profile-password-error").classList.add("hidden");

    const roomSection = document.getElementById("room-settings-section");
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

    modal.classList.remove("hidden");
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
      openProfileModal();
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
      openProfileModal();
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

    document.getElementById("profile-btn")?.addEventListener("click", openProfileModal);
    document.getElementById("close-profile-modal")?.addEventListener("click", () => {
      document.getElementById("profile-modal")?.classList.add("hidden");
    });
    document.getElementById("profile-save-password-btn")?.addEventListener("click", () => {
      saveProfilePassword(false);
    });
    document.getElementById("profile-remove-password-btn")?.addEventListener("click", () => {
      if (!confirm("Отключить пароль профиля? Вход снова будет только по PIN и никнейму.")) return;
      saveProfilePassword(true);
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
    document.getElementById("logout-btn")?.addEventListener("click", async () => {
      await api("/api/auth/logout", { method: "POST" });
      setUser(null);
      setToolbarVisible(false);
      hooks.onLogout?.();
    });
  }

  async function refreshSession() {
    bindEvents();
    try {
      const me = await api("/api/auth/me");
      setUser(me);
      syncAvatarUi();
      setToolbarVisible(true);
      return me;
    } catch {
      setUser(null);
      setToolbarVisible(false);
      return null;
    }
  }

  window.ProfileUi = {
    init(options = {}) {
      hooks = options;
      bindEvents();
      return refreshSession();
    },
    refreshSession,
    syncAvatarUi,
    openProfileModal,
    DEFAULT_AVATAR_URL,
  };
})();
