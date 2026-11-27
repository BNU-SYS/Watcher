(function () {
  const paths = {
    dashboard:
      '<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    history:
      '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5S20 17 20 21"/>',
    upload:
      '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    code: '<path d="M8 8l-4 4 4 4"/><path d="M16 8l4 4-4 4"/><path d="M13 5l-2 14"/>',
    shield:
      '<path d="M12 3l7 3v6c0 4.4-3 7.7-7 9-4-1.3-7-4.6-7-9V6l7-3z"/><path d="M9 12l2 2 4-4"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    alert:
      '<path d="M12 4l9 16H3l9-16z"/><path d="M12 10v4"/><path d="M12 17.2v.2"/>',
    x: '<path d="M18 6L6 18M6 6l12 12"/>',
    trash:
      '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
    edit: '<path d="M4 20h4l10-10-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8"/><path d="M17 4l3 3"/><path d="M14 7l3 3"/>',
    download:
      '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M4 20h16"/>',
    refresh:
      '<path d="M20 11a8 8 0 0 0-14-4L4 9"/><path d="M4 4v5h5"/><path d="M4 13a8 8 0 0 0 14 4l2-2"/><path d="M20 20v-5h-5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    file: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 12h4M10 16h4"/>',
    back: '<path d="M19 12H5"/><path d="M11 6l-6 6 6 6"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    eye: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="2.5"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    layers:
      '<path d="M12 3l9 4.5-9 4.5-9-4.5L12 3z"/><path d="M3 12l9 4.5 9-4.5"/><path d="M3 16.5L12 21l9-4.5"/>',
    bolt: '<path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z"/>',
    shieldAlert:
      '<path d="M12 3l7 3v6c0 4.4-3 7.7-7 9-4-1.3-7-4.6-7-9V6l7-3z"/><path d="M12 8v4"/><path d="M12 15.2v.2"/>',
    coins:
      '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
    yen:
      '<path d="M7 6l5 6 5-6"/><path d="M12 12v6"/><path d="M8.5 13h7M8.5 16h7"/>',
    book:
      '<path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2V5z"/><path d="M8 3v18"/><path d="M12 8h4M12 12h4"/>',
    clipboard:
      '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2"/><path d="M9 13h6M9 17h4"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    database:
      '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    settings:
      '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  };

  function icon(name, size) {
    const path = paths[name] || paths.file;
    return `<svg class="icon" width="${size || 18}" height="${size || 18}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  }

  function esc(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function toast(message, type) {
    const root = document.getElementById("toast-root");
    if (!root) return;
    const node = document.createElement("div");
    node.className = `toast toast-${type || "info"}`;
    const iconName = type === "success" ? "check" : type === "error" || type === "warn" ? "alert" : "";
    node.innerHTML = `${iconName ? icon(iconName, 18) : ""}<span>${esc(message)}</span>`;
    while (root.children.length >= 4) root.removeChild(root.firstElementChild);
    root.appendChild(node);
    requestAnimationFrame(() => node.classList.add("show"));
    setTimeout(() => {
      node.classList.remove("show");
      setTimeout(() => node.remove(), 220);
    }, 4200);
  }

  let openModal = null;

  function modal(options) {
    const opts = options || {};
    if (openModal) openModal.close();
    const root = document.getElementById("modal-root");
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    const dialog = document.createElement("div");
    dialog.className = "modal";
    if (opts.wide) dialog.classList.add("modal-wide");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.innerHTML = `
      <div class="modal-head">
        <div>
          <h3>${esc(opts.title || "")}</h3>
          ${opts.subtitle ? `<p>${esc(opts.subtitle)}</p>` : ""}
        </div>
        <button type="button" class="icon-btn" data-close aria-label="关闭">${icon("x", 18)}</button>
      </div>
      <div class="modal-body"></div>
      <div class="modal-foot"></div>`;
    const body = dialog.querySelector(".modal-body");
    if (opts.body instanceof Node) body.appendChild(opts.body);
    else if (typeof opts.body === "string") body.innerHTML = opts.body;
    const foot = dialog.querySelector(".modal-foot");
    if (opts.footer instanceof Node) foot.appendChild(opts.footer);
    else if (typeof opts.footer === "string") foot.innerHTML = opts.footer;
    if (!foot.childNodes.length) foot.remove();
    overlay.appendChild(dialog);
    root.appendChild(overlay);
    document.body.classList.add("modal-open");

    const previous = document.activeElement;
    let closed = false;
    function close() {
      if (closed) return;
      closed = true;
      overlay.classList.remove("show");
      document.body.classList.remove("modal-open");
      setTimeout(() => overlay.remove(), 160);
      document.removeEventListener("keydown", onKey);
      openModal = null;
      if (previous && previous.focus) previous.focus();
      if (typeof opts.onClose === "function") {
        try {
          opts.onClose();
        } catch (error) {
          /* closing must not throw */
        }
      }
    }
    function onKey(event) {
      if (event.key === "Escape") close();
    }
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay && opts.dismissible !== false) close();
    });
    dialog.querySelectorAll("[data-close]").forEach((button) => {
      button.addEventListener("click", close);
    });
    document.addEventListener("keydown", onKey);
    requestAnimationFrame(() => overlay.classList.add("show"));
    const focusTarget = dialog.querySelector("input, textarea, select, button:not([data-close])");
    if (focusTarget) setTimeout(() => focusTarget.focus(), 80);
    openModal = { close, dialog, overlay };
    return openModal;
  }

  function confirmDialog(options) {
    const opts = options || {};
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      const footer = document.createElement("div");
      footer.className = "modal-actions";
      footer.innerHTML = `
        <button type="button" class="btn btn-ghost" data-cancel>${esc(opts.cancelText || "取消")}</button>
        <button type="button" class="btn ${opts.danger ? "btn-danger" : "btn-primary"}" data-confirm>${esc(opts.confirmText || "确认")}</button>`;
      const instance = modal({
        title: opts.title || "确认操作",
        body: `<p class="modal-text">${esc(opts.message || "")}</p>`,
        footer,
        onClose: () => finish(false),
      });
      footer.querySelector("[data-cancel]").addEventListener("click", () => {
        finish(false);
        instance.close();
      });
      footer.querySelector("[data-confirm]").addEventListener("click", () => {
        finish(true);
        instance.close();
      });
    });
  }

  function parseDate(value) {
    if (!value) return null;
    let text = String(value);
    if (!/[zZ]$|[+-]\d{2}:?\d{2}$/.test(text)) text += "Z";
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDate(value) {
    const date = parseDate(value);
    if (!date) return "—";
    return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  }

  function formatDateTime(value) {
    const date = parseDate(value);
    if (!date) return "—";
    return date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function timeAgo(value) {
    const date = parseDate(value);
    if (!date) return "—";
    const diff = Date.now() - date.getTime();
    const minute = 60 * 1000;
    if (diff < minute) return "刚刚";
    if (diff < 60 * minute) return `${Math.floor(diff / minute)} 分钟前`;
    if (diff < 24 * 60 * minute) return `${Math.floor(diff / (60 * minute))} 小时前`;
    if (diff < 7 * 24 * 60 * minute) return `${Math.floor(diff / (24 * 60 * minute))} 天前`;
    return formatDate(value);
  }

  const STATUS = {
    queued: { label: "排队中", cls: "status-queued" },
    running: { label: "检测中", cls: "status-running" },
    succeeded: { label: "已完成", cls: "status-ok" },
    partial: { label: "部分完成", cls: "status-warn" },
    failed: { label: "失败", cls: "status-error" },
    cancelled: { label: "已取消", cls: "status-muted" },
  };

  const SEVERITY = {
    critical: { label: "严重", cls: "sev-critical" },
    high: { label: "高危", cls: "sev-high" },
    medium: { label: "中危", cls: "sev-medium" },
    low: { label: "低危", cls: "sev-low" },
    info: { label: "提示", cls: "sev-info" },
    unknown: { label: "待定", cls: "sev-unknown" },
  };

  function statusChip(status) {
    const meta = STATUS[status] || { label: status || "未知", cls: "status-muted" };
    return `<span class="status ${meta.cls}"><i></i>${esc(meta.label)}</span>`;
  }

  function closeModal() {
    if (openModal) openModal.close();
  }

  function severityBadge(severity) {
    const meta = SEVERITY[severity] || SEVERITY.unknown;
    return `<span class="sev ${meta.cls}">${meta.label}</span>`;
  }

  function formatNumber(value) {
    const number = Number(value || 0);
    return number.toLocaleString("zh-CN");
  }

  function formatDuration(seconds) {
    const value = Number(seconds || 0);
    if (!value) return "—";
    if (value < 1) return `${value.toFixed(2)} 秒`;
    if (value < 60) return `${value.toFixed(1)} 秒`;
    const minutes = Math.floor(value / 60);
    const rest = Math.round(value % 60);
    return `${minutes} 分 ${rest} 秒`;
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function emptyState(title, description, actionHtml) {
    return `<div class="empty">
      <h3>${esc(title)}</h3>
      <p>${esc(description)}</p>
      ${actionHtml ? `<div class="empty-actions">${actionHtml}</div>` : ""}
    </div>`;
  }

  function loading(text) {
    return `<div class="loading-block"><span class="spinner"></span><p>${esc(text || "加载中…")}</p></div>`;
  }

  function skeletonRows(count) {
    return Array.from({ length: count || 5 })
      .map(
        () => `<div class="skeleton-row"><span class="skeleton w-40"></span><span class="skeleton w-15"></span><span class="skeleton w-20"></span></div>`
      )
      .join("");
  }

  window.UI = {
    icon,
    esc,
    toast,
    modal,
    confirm: confirmDialog,
    closeModal,
    formatDate,
    formatDateTime,
    timeAgo,
    statusChip,
    severityBadge,
    formatNumber,
    formatDuration,
    formatBytes,
    emptyState,
    loading,
    skeletonRows,
    STATUS,
    SEVERITY,
  };
})();
