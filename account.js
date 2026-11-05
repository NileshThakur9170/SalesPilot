(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", async () => {
    const trigger = document.getElementById("accountTrigger");
    const dropdown = document.getElementById("accountDropdown");
    const overlay = document.getElementById("settingsOverlay");
    const closeBtn = document.getElementById("closeSettingsBtn");
    const flashes = document.getElementById("settingsFlashes");

    const showNotice = (message, kind = "success") => {
      if (!flashes) return;
      const node = document.createElement("div");
      node.className = `settings-notice ${kind}`;
      node.textContent = message;
      flashes.replaceChildren(node);
    };

    try {
      const response = await fetch("/api/me");
      if (response.status === 401) { location.href = "/login"; return; }
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || "Could not load account.");
      const user = result.user;
      document.getElementById("accountAvatar").textContent = (user.name || "U").trim().charAt(0).toUpperCase();
      document.getElementById("accountTriggerName").textContent = user.name;
      document.getElementById("dropdownUserName").textContent = user.name;
      document.getElementById("dropdownUserEmail").textContent = user.email;
      document.getElementById("settingsName").value = user.name;
      document.getElementById("settingsEmail").value = user.email;
    } catch (error) {
      console.error("Account profile:", error);
      showNotice(error.message, "error");
    }

    trigger?.addEventListener("click", () => {
      dropdown.hidden = !dropdown.hidden;
      trigger.setAttribute("aria-expanded", String(!dropdown.hidden));
    });
    document.addEventListener("click", event => {
      if (!event.target.closest("#accountMenu")) {
        if (dropdown) dropdown.hidden = true;
        trigger?.setAttribute("aria-expanded", "false");
      }
    });

    const openSettings = () => {
      if (dropdown) dropdown.hidden = true;
      trigger?.setAttribute("aria-expanded", "false");
      overlay.hidden = false;
      document.body.classList.add("settings-open");
      closeBtn?.focus();
    };
    const hideSettings = () => {
      overlay.hidden = true;
      document.body.classList.remove("settings-open");
    };
    document.getElementById("openSettingsBtn")?.addEventListener("click", openSettings);
    closeBtn?.addEventListener("click", hideSettings);
    overlay?.addEventListener("click", event => { if (event.target === overlay) hideSettings(); });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && overlay && !overlay.hidden) hideSettings();
    });

    document.getElementById("profileForm")?.addEventListener("submit", async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const payload = {
        name: document.getElementById("settingsName").value.trim(),
        email: document.getElementById("settingsEmail").value.trim(),
        current_password: document.getElementById("profileCurrentPassword").value
      };
      try {
        const response = await fetch("/account/profile", {
          method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || "Profile update failed.");
        document.getElementById("profileCurrentPassword").value = "";
        document.getElementById("accountTriggerName").textContent = payload.name;
        document.getElementById("accountAvatar").textContent = payload.name.charAt(0).toUpperCase();
        document.getElementById("dropdownUserName").textContent = payload.name;
        document.getElementById("dropdownUserEmail").textContent = payload.email;
        showNotice("Profile updated successfully.");
      } catch (error) { showNotice(error.message, "error"); }
    });

    document.getElementById("passwordForm")?.addEventListener("submit", async event => {
      event.preventDefault();
      const payload = {
        current_password: document.getElementById("passwordCurrent").value,
        new_password: document.getElementById("passwordNew").value,
        confirm_password: document.getElementById("passwordConfirm").value
      };
      try {
        const response = await fetch("/account/password", {
          method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || "Password update failed.");
        event.currentTarget.reset();
        showNotice("Password changed successfully.");
      } catch (error) { showNotice(error.message, "error"); }
    });

    document.getElementById("switchAccountBtn")?.addEventListener("click", () => {
      const form = document.createElement("form");
      form.method = "POST"; form.action = "/logout";
      document.body.appendChild(form); form.submit();
    });

    if (location.hash === "#settings") openSettings();
  });
})();