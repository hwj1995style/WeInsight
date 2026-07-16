(() => {
  const panel = document.getElementById("authorization-management");
  if (!panel) return;
  const csrf = document.querySelector('input[name="csrf_token"]')?.value || "";
  const refresh = document.getElementById("authorization-refresh");
  const scan = document.getElementById("authorization-scan");
  const dialog = document.getElementById("authorization-dialog");
  const image = document.getElementById("authorization-qr-image");
  const message = document.getElementById("authorization-dialog-message");
  const cancel = document.getElementById("authorization-cancel");
  const settingsForm = document.getElementById("authorization-settings-form");
  const settingsDialog = document.getElementById("authorization-settings-dialog");
  const settingsOpen = document.getElementById("authorization-settings-open");
  const settingsClose = document.getElementById("authorization-settings-close");
  const settingsCancel = document.getElementById("authorization-settings-cancel");
  const settingsMessage = document.getElementById("authorization-settings-message");
  const testWerss = document.getElementById("authorization-test-werss");
  const testEmail = document.getElementById("authorization-test-email");
  let sessionId = null;
  let timer = null;
  let imageUrl = null;
  let imageAttempts = 0;

  const closeSettings = () => settingsDialog?.close();
  settingsOpen?.addEventListener("click", () => settingsDialog?.showModal());
  settingsClose?.addEventListener("click", closeSettings);
  settingsCancel?.addEventListener("click", closeSettings);
  settingsDialog?.addEventListener("click", (event) => {
    if (event.target === settingsDialog) closeSettings();
  });

  const api = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers: { "X-CSRF-Token": csrf, ...(options.headers || {}) },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message || "授权服务暂时不可用");
    return body;
  };
  const stopPolling = () => {
    if (timer) window.clearInterval(timer);
    timer = null;
  };
  const showError = (error) => {
    message.textContent = error instanceof Error ? error.message : "授权服务暂时不可用";
  };
  const loadQrImage = () => {
    if (!imageUrl || !sessionId) return;
    image.src = `${imageUrl}?v=${Date.now()}`;
  };
  image?.addEventListener("load", () => {
    imageAttempts = 0;
    image.hidden = false;
    message.textContent = "请使用微信扫描二维码完成授权";
  });
  image?.addEventListener("error", () => {
    image.hidden = true;
    if (sessionId && imageAttempts < 3) {
      imageAttempts += 1;
      message.textContent = `二维码加载中，正在重试（${imageAttempts}/3）…`;
      window.setTimeout(loadQrImage, imageAttempts * 700);
      return;
    }
    stopPolling();
    message.textContent = "二维码加载失败，请取消后重新获取";
  });

  refresh?.addEventListener("click", async () => {
    refresh.disabled = true;
    try {
      await api("/sources/articles/authorization/refresh", { method: "POST" });
      window.location.reload();
    } catch (error) {
      window.alert(error.message);
    } finally {
      refresh.disabled = false;
    }
  });

  scan?.addEventListener("click", async () => {
    stopPolling();
    sessionId = null;
    imageUrl = null;
    imageAttempts = 0;
    image.hidden = true;
    message.textContent = "正在获取二维码…";
    dialog.showModal();
    try {
      const started = await api("/sources/articles/authorization/qr/start", { method: "POST" });
      sessionId = started.session_id;
      imageUrl = started.image_url;
      loadQrImage();
      timer = window.setInterval(async () => {
        try {
          const result = await api(`/sources/articles/authorization/qr/${sessionId}/status`);
          if (result.status === "authorized") {
            stopPolling();
            message.textContent = "授权成功，正在刷新页面…";
            window.setTimeout(() => window.location.reload(), 700);
          } else if (result.status === "expired") {
            stopPolling();
            image.hidden = true;
            message.textContent = "二维码已过期，请取消后重新获取";
          }
        } catch (error) {
          stopPolling();
          showError(error);
        }
      }, 3000);
    } catch (error) {
      showError(error);
    }
  });

  cancel?.addEventListener("click", async () => {
    stopPolling();
    if (sessionId) {
      await api(`/sources/articles/authorization/qr/${sessionId}/cancel`, { method: "POST" }).catch(() => {});
    }
    sessionId = null;
    imageUrl = null;
    dialog.close();
  });

  const recipients = (value) => value.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean);
  settingsForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    settingsMessage.textContent = "正在保存…";
    const data = new FormData(settingsForm);
    const payload = {
      werss_username: String(data.get("werss_username") || ""),
      werss_password: String(data.get("werss_password") || ""),
      smtp_enabled: data.get("smtp_enabled") === "on",
      smtp_host: String(data.get("smtp_host") || ""),
      smtp_port: Number(data.get("smtp_port") || 0),
      smtp_username: String(data.get("smtp_username") || ""),
      smtp_password: String(data.get("smtp_password") || ""),
      smtp_security: String(data.get("smtp_security") || ""),
      from_address: String(data.get("from_address") || ""),
      recipients: recipients(String(data.get("recipients") || "")),
    };
    try {
      await api("/sources/articles/authorization/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      settingsForm.querySelector('[name="werss_password"]').value = "";
      settingsForm.querySelector('[name="smtp_password"]').value = "";
      settingsMessage.textContent = "配置已安全保存";
      window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      settingsMessage.textContent = error.message;
    }
  });
  const testSettings = async (button, path) => {
    button.disabled = true;
    settingsMessage.textContent = "正在测试…";
    try {
      const result = await api(path, { method: "POST" });
      settingsMessage.textContent = result.message;
    } catch (error) {
      settingsMessage.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  testWerss?.addEventListener("click", () => testSettings(testWerss, "/sources/articles/authorization/settings/test-werss"));
  testEmail?.addEventListener("click", () => testSettings(testEmail, "/sources/articles/authorization/settings/test-email"));
})();
