(function () {
  "use strict";

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  const DEFAULT_OPTIONS = {
    max_files: 20,
    max_model_calls: 20,
    timeout: 300,
    request_timeout: 60,
    max_file_chars: 30000,
    json_mode: false,
  };

  const PACKAGE_EXCLUDED_DIRS = new Set([
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
  ]);

  const MODEL_KEY = "watcher.model";

  function readModelConfig() {
    try {
      const saved = JSON.parse(localStorage.getItem(MODEL_KEY) || "{}");
      return {
        base_url: String(saved.base_url || ""),
        model: String(saved.model || ""),
        api_key: String(saved.api_key || ""),
      };
    } catch (error) {
      return { base_url: "", model: "", api_key: "" };
    }
  }

  function writeModelConfig(config) {
    state.model = {
      base_url: String(config.base_url || "").trim(),
      model: String(config.model || "").trim(),
      api_key: String(config.api_key || "").trim(),
    };
    localStorage.setItem(MODEL_KEY, JSON.stringify(state.model));
  }

  function clearModelConfig() {
    state.model = { base_url: "", model: "", api_key: "" };
    localStorage.removeItem(MODEL_KEY);
  }

  function modelConfigured() {
    return Boolean(state.model.base_url && state.model.model && state.model.api_key);
  }

  function maskedKey(value) {
    const text = String(value || "");
    return text ? `••••${text.slice(-4)}` : "未填写";
  }

  const state = {
    catalog: { languages: [], framework: { available: false, path: "", error: "" } },
    model: readModelConfig(),
    filters: { status: "", language: "", q: "", page: 1 },
    newScan: {
      language: null,
      types: [],
      typesLanguage: null,
      mode: "upload",
      files: [],
      code: "",
      filename: "",
      filenameTouched: false,
      repoUrl: "",
      repoRef: "",
      repoSubdir: "",
      options: Object.assign({}, DEFAULT_OPTIONS),
    },
    detailId: null,
    detailFilters: { severity: "", type: "" },
    workbench: { scanId: null, file: "", source: {}, selectedId: null, shown: 0 },
    currentScan: null,
    poll: null,
    feedback: {
      reports: [],
      selectedId: null,
      detail: null,
      items: [],
      editor: null,
      submitting: false,
      source: {},
      sourceLoading: {},
      previewKey: null,
      codeFile: "",
      codeQuery: "",
      codeSelection: null,
      codeAnchor: null,
      codeMatches: [],
      codeMatchIndex: 0,
      codeDragging: false,
    },
  };

  let routeToken = 0;

  function clearPoll() {
    if (state.poll) {
      clearInterval(state.poll);
      state.poll = null;
    }
  }

  function currentRoute() {
    const raw = (location.hash || "#/new").replace(/^#\/?/, "");
    const parts = raw.split("/").filter(Boolean);
    return { name: parts[0] || "new", id: parts[1] || null };
  }

  function languageEntry(code) {
    return (state.catalog.languages || []).find((item) => item.code === code) || null;
  }

  function languageName(code) {
    const entry = languageEntry(code);
    return entry ? entry.name : code;
  }

  function isPackageLanguage(code) {
    return code === "agent_skill";
  }

  const LANGUAGE_LOGOS = {
    java: "java",
    python: "python",
    php: "php",
    c: "cplusplus",
    cpp: "cplusplus",
    agent_skill: "bot",
  };

  function languageBadge(entry) {
    if (entry.code === "c") return "C";
    if (isPackageLanguage(entry.code)) return "AG";
    return entry.name.slice(0, 2).toUpperCase();
  }

  function languageMark(entry) {
    const logo = LANGUAGE_LOGOS[entry.code];
    return logo
      ? `<img class="lang-logo" src="/assets/lang/${logo}.svg" alt="" aria-hidden="true" width="40" height="40" />`
      : `<span class="lang-code">${UI.esc(languageBadge(entry))}</span>`;
  }

  function extensionSummary(entry) {
    if (isPackageLanguage(entry.code)) return "完整 Skill 包";
    const extensions = entry.extensions || [];
    return extensions.length > 4
      ? extensions.slice(0, 4).join(" ") + " …"
      : extensions.join(" ");
  }

  // Chinese names for CWEs the catalog lists without one (label === code).
  const DEFECT_NAMES = {
    "CWE-20": "输入验证不当",
    "CWE-352": "跨站请求伪造 CSRF",
    "CWE-434": "危险文件上传",
    "CWE-787": "越界写入",
    "CWE-835": "无限循环",
    "CWE-862": "缺少授权",
    "CWE-918": "服务端请求伪造 SSRF",
    "Prompt Injection": "提示词注入",
    "Malicious Code": "恶意代码",
    "Excessive Permissions": "权限过大",
    "Secret Exposure": "密钥泄露",
    "Supply Chain": "供应链风险",
    "Validation": "元数据校验",
  };

  // Display groups for the defect-type picker. The catalog itself is flat;
  // codes not listed here fall into「其他缺陷」.
  const DEFECT_GROUPS = [
    { label: "注入与执行", icon: "shield", codes: ["CWE-78", "CWE-89", "CWE-94", "CWE-95", "CWE-98", "CWE-470", "CWE-611"] },
    { label: "输入与请求", icon: "link", codes: ["CWE-20", "CWE-22", "CWE-79", "CWE-352", "CWE-434", "CWE-918"] },
    { label: "数据与权限", icon: "key", codes: ["CWE-295", "CWE-502", "CWE-798", "CWE-862"] },
    { label: "内存与资源", icon: "database", codes: ["CWE-125", "CWE-401", "CWE-400", "CWE-476", "CWE-772", "CWE-787"] },
    { label: "数值与逻辑", icon: "settings", codes: ["CWE-190", "CWE-191", "CWE-197", "CWE-362", "CWE-369", "CWE-606", "CWE-835"] },
    { label: "技能包审查", icon: "shield", codes: ["Prompt Injection", "Malicious Code", "Supply Chain"] },
    { label: "权限与配置", icon: "key", codes: ["Excessive Permissions", "Secret Exposure", "Validation"] },
  ];

  function defectName(item) {
    if (item.label && item.label !== item.code) return item.label;
    return DEFECT_NAMES[item.code] || "";
  }

  function groupDefectTypes(types) {
    const groups = DEFECT_GROUPS.map((group) => ({
      label: group.label,
      icon: group.icon,
      items: types.filter((item) => group.codes.includes(item.code)),
    })).filter((group) => group.items.length);
    const grouped = new Set(DEFECT_GROUPS.flatMap((group) => group.codes));
    const rest = types.filter((item) => !grouped.has(item.code));
    if (rest.length) groups.push({ label: "其他缺陷", icon: "settings", items: rest });
    return groups;
  }

  function defectLabel(code) {
    for (const language of state.catalog.languages || []) {
      const item = (language.defect_types || []).find((defect) => defect.code === code);
      if (item) return defectName(item) || item.code;
    }
    return DEFECT_NAMES[code] || code;
  }

  function defectOptionLabel(item) {
    const name = defectName(item);
    if (!/^CWE-\d+$/.test(item.code)) return name || item.code;
    return name ? `${item.code} / ${name}` : item.code;
  }

  const HIDDEN_LIMITATIONS = new Set([
    "Single-file model review only; no compilation, execution, or independent verification.",
    "Snapshot covers captured input files, not the entire repository.",
    "Generated directories and directory links are excluded during collection.",
  ]);

  const COVERAGE_TEXT = {
    "Package review uses only captured UTF-8 files; no code was executed or independently verified.":
      "包审查只基于已采集的 UTF-8 文件，不执行代码，也不做独立验证。",
    "Symlink targets, image metadata, and remote resource contents were not supplied.":
      "未提供符号链接目标、图片元数据或远程资源内容，相关检查存在缺口。",
  };

  const ERROR_LABELS = {
    MODEL_REQUEST_FAILED: "模型请求失败",
    INVALID_MODEL_OUTPUT: "模型输出无效",
    SOURCE_LIMIT: "文件数超出上限",
    SOURCE_SKIPPED: "文件被跳过",
    BUDGET_EXCEEDED: "模型调用预算用尽",
    TIMEOUT: "执行超时",
    EXECUTION_FAILED: "执行失败",
    CANCELLED: "任务已取消",
    SERVER_RESTART: "服务重启",
  };

  function coverageText(text) {
    if (!text) return "";
    const scope = /^Model reviewed (\d+)\/(\d+) captured files$/.exec(text);
    if (scope) return `模型审查了 ${scope[1]}/${scope[2]} 个已采集文件`;
    const packageScope = /^Model reviewed (\d+)\/(\d+) captured Skill files in one package$/.exec(text);
    if (packageScope) return `模型审查了 ${packageScope[1]}/${packageScope[2]} 个 Skill 包文件`;
    return COVERAGE_TEXT[text] || text;
  }

  const SOURCE_SKIP_REASONS = {
    "file exceeds the configured size limit": "文件大小超出采集上限",
    "file exceeds max_file_chars": "文件字符数超出单文件上限",
    "Additional matching files exceed max_files": "匹配文件数超出上限，其余文件未采集（数量未记录）",
    "not valid UTF-8": "文件不是有效的 UTF-8 编码",
    "source could not be read": "无法读取文件",
    "source links and non-regular files are not supported": "不支持符号链接或非常规文件",
    "Git LFS pointer skipped; actual file content was not fetched; coverage is incomplete":
      "仅获取到 Git LFS 指针，未获取实际文件内容",
  };

  function coverageGroups(scan) {
    const collectionErrors = (scan.errors || []).filter((item) =>
      ["SOURCE_LIMIT", "SOURCE_SKIPPED", "LFS_SOURCE_NOT_FETCHED"].includes(item.code)
    );
    const collectionMessages = new Set(collectionErrors.map((item) => item.message));
    const messages = [...new Set([
      ...((scan.coverage && scan.coverage.limitations) || []),
      ...collectionMessages,
    ])].filter((item) => !HIDDEN_LIMITATIONS.has(item));
    const skipped = [];
    const notes = new Map();
    for (const text of messages) {
      const separator = text.indexOf(": ");
      const path = separator >= 0 ? text.slice(0, separator) : "";
      const reason = separator >= 0 ? text.slice(separator + 2) : text;
      if (SOURCE_SKIP_REASONS[reason] || collectionMessages.has(text)) {
        skipped.push({ path, reason: SOURCE_SKIP_REASONS[reason] || reason });
      } else {
        const key = path || "通用说明";
        if (!notes.has(key)) notes.set(key, []);
        notes.get(key).push(coverageText(reason));
      }
    }
    return { skipped, notes };
  }

  function coverageMarkup(scan) {
    const { skipped, notes } = coverageGroups(scan);
    const total = Number(scan.total_files || 0);
    const done = Number(scan.completed_files || 0);
    const pending = Math.max(0, total - done);
    const active = ["queued", "running"].includes(scan.status);
    const restricted = skipped.length > 0 || pending > 0;
    const noteCount = [...notes.values()].reduce((sum, items) => sum + items.length, 0);
    const fileLabel = (path) => path.split(/[\\/]/).pop() || path;
    return `<section class="card coverage-card">
      <div class="card-head">
        <div><h2>检测范围</h2><p>已采集文件的审查进度与范围说明</p></div>
        <span class="coverage-status${restricted ? " warn" : ""}">${active ? "审查进行中" : restricted ? "存在范围限制" : "范围记录"}</span>
      </div>
      ${total ? `<div class="coverage-facts">
        <div><span>已采集文件</span><b>${UI.formatNumber(total)}</b></div>
        <div><span>已完成审查</span><b>${UI.formatNumber(done)}</b></div>
        <div><span>${active ? "待完成审查" : "未完成审查"}</span><b>${UI.formatNumber(pending)}</b></div>
      </div>` : ""}
      <p class="coverage-line${restricted ? " warn" : ""}">${UI.esc(total
        ? (pending ? `${pending} 个已采集文件${active ? "尚未" : "未"}完成审查。` : "已采集的文件均已完成审查。")
          + (skipped.length ? "另有文件在采集阶段被跳过，详见下方记录。" : "统计仅覆盖已采集文件，不代表整个仓库。")
        : (scan.coverage && scan.coverage.scope_description ? coverageText(scan.coverage.scope_description) : "未记录检测范围"))}</p>
      ${skipped.length ? `<details class="coverage-section coverage-skipped">
        <summary><span class="coverage-section-title">采集时跳过 <span class="coverage-count">${UI.formatNumber(skipped.length)} 条记录</span></span><span class="coverage-toggle" aria-hidden="true"></span></summary>
        <div class="coverage-section-body">
          <p class="coverage-hint">以下记录不计入上方已采集文件数；文件数超限记录不代表具体跳过数量。</p>
          <ul class="coverage-skip-list">${skipped.map((item) => `<li>
            <span class="coverage-file">${UI.esc(item.path ? fileLabel(item.path) : "采集限制")}${item.path ? `<small>${UI.esc(item.path)}</small>` : ""}</span>
            <span class="coverage-reason">${UI.esc(item.reason)}</span>
          </li>`).join("")}</ul>
        </div>
      </details>` : ""}
      ${noteCount ? `<details class="coverage-section">
        <summary><span class="coverage-section-title">审查局限与说明 <span class="coverage-count">${UI.formatNumber(noteCount)} 条说明</span></span><span class="coverage-toggle" aria-hidden="true"></span></summary>
        <div class="coverage-section-body">
          <p class="coverage-hint">上下文缺失等说明不等同于已确认缺陷。展开文件查看完整内容。</p>
          <div class="coverage-note-list">${[...notes].map(([path, items]) => `<details class="coverage-note">
            <summary><span class="coverage-file">${UI.esc(fileLabel(path))}${path !== "通用说明" ? `<small>${UI.esc(path)}</small>` : ""}</span><span class="coverage-count">${UI.formatNumber(items.length)} 条</span></summary>
            <ul>${items.map((item) => `<li>${UI.esc(item)}</li>`).join("")}</ul>
          </details>`).join("")}</div>
        </div>
      </details>` : ""}
    </section>`;
  }

  function errorLabel(code) {
    return ERROR_LABELS[code] || code;
  }

  function shortPath(value) {
    const parts = String(value || "").split(/[\\/]/).filter(Boolean);
    return parts.slice(-2).join("\\") || value || "";
  }

  function setActiveNav(name) {
    $$("[data-nav]").forEach((link) => {
      const key = link.getAttribute("data-nav");
      const active = key === name;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function pageHead(title, subtitle, actions) {
    return `<div class="page-head">
      <div>
        <h1>${UI.esc(title)}</h1>
        ${subtitle ? `<p>${UI.esc(subtitle)}</p>` : ""}
      </div>
      ${actions ? `<div class="page-actions">${actions}</div>` : ""}
    </div>`;
  }

  function errorPanel(error, retry) {
    const message = error && error.message ? error.message : "请求失败";
    return `<div class="card error-card">
      <div class="error-icon">${UI.icon("alert", 22)}</div>
      <div>
        <h3>加载失败</h3>
        <p>${UI.esc(message)}</p>
        ${retry ? `<button class="btn btn-ghost btn-sm" data-retry>重试</button>` : ""}
      </div>
    </div>`;
  }

  function bindRetry(handler) {
    $$("[data-retry]").forEach((button) => {
      button.addEventListener("click", handler);
    });
  }

  async function loadWorkspaceData() {
    state.catalog = await API.catalog();
  }

  /* --------------------------------------------------------------- settings */

  function formValues(form) {
    const data = {};
    new FormData(form).forEach((value, key) => {
      data[key] = String(value);
    });
    return data;
  }

  async function renderSettings(token) {
    const view = $("#view");
    const model = state.model;
    view.innerHTML =
      pageHead("模型设置", "", "") +
      `<section class="card form-card">
        <div class="card-head"><div><h2>模型服务配置</h2><p>支持 OpenAI 兼容接口</p></div><span class="pill ghost">仅保存在当前浏览器</span></div>
        <form id="model-form" class="form narrow">
          <label class="field"><span>API 根地址</span><input name="base_url" maxlength="512" placeholder="https://api.example.com/v1" value="${UI.esc(model.base_url)}" required /></label>
          <label class="field"><span>模型名称</span><input name="model" maxlength="128" placeholder="模型 ID" value="${UI.esc(model.model)}" required /></label>
          <label class="field"><span>API Key</span><input name="api_key" type="password" maxlength="512" autocomplete="off" placeholder="API Key" value="${UI.esc(model.api_key)}" required /></label>
          <div class="form-error" id="model-error" hidden></div>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary">保存配置</button>
            <button type="button" class="btn btn-ghost" id="verify-model">测试连接</button>
            <button type="button" class="btn btn-ghost danger-text" id="clear-model">清除配置</button>
          </div>
        </form>
        <div class="model-status ${modelConfigured() ? "ok" : "bad"}">
          ${UI.icon(modelConfigured() ? "check" : "alert", 16)}
          <span>${modelConfigured() ? `已配置 ${UI.esc(model.model)} / ${maskedKey(model.api_key)}` : "尚未配置模型服务"}</span>
        </div>
      </section>`;
    const form = $("#model-form");
    const errorBox = $("#model-error");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorBox.hidden = true;
      const values = formValues(form);
      if (!values.base_url || !values.model || !values.api_key) {
        errorBox.hidden = false;
        errorBox.textContent = "请填写根地址、模型名称和 API Key";
        return;
      }
      const saveButton = form.querySelector('button[type="submit"]');
      if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "测试连接中…";
      }
      try {
        const result = await API.verifyModel(values);
        if (!result.ok) {
          errorBox.hidden = false;
          errorBox.textContent = result.message || "连接测试失败，配置未保存";
          UI.toast(result.message || "连接测试失败，配置未保存", "error");
          return;
        }
        writeModelConfig(values);
        UI.toast(
          `连接测试通过，模型配置已保存${result.latency_ms ? `（${result.latency_ms} ms）` : ""}`,
          "success"
        );
        if (token === routeToken) {
          renderShell();
          handleRoute();
        }
      } catch (error) {
        const message = error.message || "连接测试失败，配置未保存";
        errorBox.hidden = false;
        errorBox.textContent = message;
        UI.toast(message, "error");
      } finally {
        if (saveButton) {
          saveButton.disabled = false;
          saveButton.textContent = "保存配置";
        }
      }
    });
    $("#verify-model").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      errorBox.hidden = true;
      const values = formValues(form);
      if (!values.base_url || !values.model || !values.api_key) {
        errorBox.hidden = false;
        errorBox.textContent = "请先填写完整配置";
        return;
      }
      button.disabled = true;
      button.textContent = "测试中…";
      try {
        const result = await API.verifyModel(values);
        if (result.ok) {
          UI.toast(
            `连接正常${result.latency_ms ? `（${result.latency_ms} ms）` : ""}，点击「保存配置」后生效`,
            "success"
          );
        } else {
          errorBox.hidden = false;
          errorBox.textContent = result.message || "连接测试失败";
          UI.toast(result.message || "连接测试失败", "error");
        }
      } catch (error) {
        const message = error.message || "连接测试失败";
        errorBox.hidden = false;
        errorBox.textContent = message;
        UI.toast(message, "error");
      } finally {
        button.disabled = false;
        button.textContent = "测试连接";
      }
    });
    $("#clear-model").addEventListener("click", async () => {
      const ok = await UI.confirm({
        title: "清除模型配置",
        message: "根地址、模型名与 API Key 都会从当前浏览器中删除。",
        confirmText: "清除",
        danger: true,
      });
      if (!ok) return;
      clearModelConfig();
      UI.toast("模型配置已清除", "success");
      renderShell();
      handleRoute();
    });
  }

  /* ----------------------------------------------------------------- shell */

  function renderShell() {
    const app = $("#app");
    const framework = state.catalog.framework || {};
    app.className = "shell shell-top";
    app.innerHTML = `
      <header class="topnav">
        <div class="topnav-inner">
          <a class="brand" href="#/new">
            <img class="brand-logo" src="/favicon.svg?v=20261119a" alt="望查 BNU-SYS" width="44" height="44" />
            <span class="brand-text"><strong>望查</strong><small>Watcher</small></span>
          </a>
          <nav class="topnav-group" aria-label="主要页面">
            <a href="#/new" data-nav="new">新建检测</a>
            <a href="#/scans" data-nav="scans">检测历史</a>
            <a href="#/dashboard" data-nav="dashboard">数据总览</a>
          </nav>
          <nav class="topnav-group end" aria-label="工具页面">
            <a href="#/feedback" data-nav="feedback">用户反馈</a>
            <a href="#/settings" data-nav="settings">模型设置</a>
            <a href="#/manual" data-nav="manual">使用手册</a>
          </nav>
        </div>
      </header>
      <main class="view" id="view"></main>
      <footer class="app-foot">
        <div class="app-foot-inner">
          <span title="${UI.esc(framework.path || "")}"><i class="foot-dot ${framework.available ? "ok" : "bad"}"></i>${framework.available ? "框架已连接" : "框架未连接"}<span class="foot-sep">·</span>BNU-SYS / Watcher</span>
          <a href="#/settings">${modelConfigured() ? `模型 ${UI.esc(state.model.model)} · ${maskedKey(state.model.api_key)}` : "模型未配置"}</a>
        </div>
      </footer>`;
    setActiveNav(currentRoute().name);
  }

  const CRUMBS = {
    dashboard: "数据总览",
    new: "新建检测",
    scans: "检测历史",
    feedback: "用户反馈",
    settings: "模型设置",
    manual: "使用手册",
  };

  async function handleRoute() {
    clearPoll();
    const token = ++routeToken;
    const route = currentRoute();
    setActiveNav(route.name);
    const crumb = $("#crumb");
    if (crumb) crumb.textContent = CRUMBS[route.name] || "新建检测";
    const view = $("#view");
    if (!view) return;
    window.scrollTo({ top: 0, behavior: "instant" });
    try {
      if (route.name === "new") await renderNewScan(token);
      else if (route.name === "scans" && route.id) await renderScanDetail(route.id, token);
      else if (route.name === "scans") await renderScanList(token);
      else if (route.name === "feedback") await renderFeedback(token);
      else if (route.name === "settings") await renderSettings(token);
      else if (route.name === "manual") renderManual();
      else await renderDashboard(token);
    } catch (error) {
      if (token !== routeToken) return;
      view.innerHTML = pageHead("出错了", "页面没有加载成功", "") + errorPanel(error, true);
      bindRetry(handleRoute);
    }
  }

  /* ------------------------------------------------------------- manual */

  function renderManual() {
    const view = $("#view");
    const toc = [
      ["manual-start", "快速开始"],
      ["manual-model", "1. 配置模型"],
      ["manual-scan", "2. 新建检测"],
      ["manual-report", "3. 解读报告"],
      ["manual-feedback", "4. 用户反馈"],
      ["manual-records", "5. 历史与总览"],
      ["manual-cost", "6. 费用与 Token"],
      ["manual-privacy", "7. 数据与隐私"],
      ["manual-faq", "8. 常见问题"],
    ]
      .map(([id, label]) => `<button type="button" data-manual-target="${id}">${label}</button>`)
      .join("");
    view.innerHTML =
      pageHead(
        "使用手册",
        "",
        `<a class="btn btn-primary" href="#/new">${UI.icon("plus", 16)}<span>新建检测</span></a>`
      ) +
      `<div class="manual">
        <aside class="manual-toc">
          <p class="manual-toc-title">目录</p>
          ${toc}
        </aside>
        <div class="manual-body">
          <section class="manual-section" id="manual-start">
            <h2>快速开始</h2>
            <p class="manual-lead">第一次使用先配置模型服务；之后每次检测只需两步，需要更换模型时回到「模型设置」修改即可。</p>
            <div class="manual-steps">
              <div class="manual-step"><span>1</span><b>配置模型</b><p>在「模型设置」中填写接口地址、模型名称和 API Key，之后可随时更换。</p></div>
              <div class="manual-step"><span>2</span><b>新建检测</b><p>选择代码类型，提交源码并勾选缺陷类型。</p></div>
              <div class="manual-step"><span>3</span><b>查看报告</b><p>核对各严重程度数量和缺陷明细。</p></div>
            </div>
            <div class="manual-callout"><b>审查方式：</b>模型逐文件进行静态审查，不编译、不执行代码；结论需人工复核。</div>
          </section>

          <section class="manual-section" id="manual-model">
            <h2>1. 配置模型</h2>
            <p>首次使用前需要配置模型服务，入口在顶部导航右侧的「模型设置」。之后如需更换模型或地址，回到同一处修改并重新保存即可。</p>
            <figure class="manual-figure">
              <img src="/assets/manual/manual-model-entry.png?v=20261120a" width="800" height="140" alt="顶部导航右侧的模型设置入口" loading="lazy" />
              <figcaption>红圈处为「模型设置」入口，位于顶部导航右侧。</figcaption>
            </figure>
            <p>填写 API 根地址、模型名称和 API Key 后，点击「保存配置」。系统会自动测试连接，通过后保存并生效；单独点击「测试连接」只验证连通性，不保存配置。</p>
            <div class="manual-callout"><b>存储范围：</b>模型配置仅保存在当前浏览器；API Key 仅用于调用所配置的模型服务，页面仅显示掩码。</div>
          </section>

          <section class="manual-section" id="manual-scan">
            <h2>2. 新建检测</h2>
            <p>按页面顺序完成四个步骤。</p>
            <ol>
              <li>选择代码类型：页面列出当前支持的全部语言与检测能力，选择与所提交代码一致的一项。</li>
              <li>提交源码：上传文件、粘贴代码或填写公开 GitHub 仓库地址。Agent Skill 仅支持上传根目录直接包含 SKILL.md 的单个包目录。</li>
              <li>勾选需要检测的缺陷类型，默认全部勾选。</li>
              <li>确认所用模型后提交（模型可在「模型设置」随时更换）。尚未配置时，可点右侧卡片里的「去配置」直接填写。</li>
            </ol>
            <h3>提交方式与限制</h3>
            <ul>
              <li>公开 GitHub 仓库的压缩包不超过 60 MB。</li>
              <li>上传文件单个不超过 2 MB，总大小不超过 12 MB，一次最多 100 个文件；超过上传限制时无法提交。</li>
              <li>实际审查还受高级参数中的文件数量和单文件字符数等限制。检测阶段跳过或未完成的文件及原因会记录在报告中。</li>
            </ul>
            <h3>任务状态</h3>
            <p>任务状态为：排队中、检测中、已完成、部分完成、失败、已取消。部分完成表示部分文件未完成审查，原因见报告的「执行错误」。</p>
            <div class="manual-callout key"><b>高级参数：</b>默认值适用于大多数场景。文件数上限决定实际送审的文件数量，模型调用次数、超时与单文件字符上限决定单个文件能否审完；调得过小会缩小审查范围，调得过大则增加耗时与费用，未明确需求时保持默认。</div>
          </section>

          <section class="manual-section" id="manual-report">
            <h2>3. 解读报告</h2>
            <p>报告页顶部为结果总览，列出候选缺陷总数和各严重程度数量；下方为检测明细。</p>
            <ul>
              <li><b>分级数量：</b>严重、高危、中危、低危、提示。</li>
              <li><b>缺陷清单：</b>按严重程度排序；选中条目可查看对应代码、解释与修复建议。</li>
              <li><b>检测范围：</b>列出实际审查的文件；执行错误列出失败或跳过的原因。</li>
            </ul>
            <figure class="manual-figure">
              <img src="/assets/manual/manual-workbench.png?v=20261120a" width="1363" height="404" alt="报告页的三栏检测明细" loading="lazy" />
              <figcaption>左侧选择文件，中间显示源码，右侧列出该文件的候选缺陷。点击右侧任一条目，中间代码会跳转到对应行（箭头所示）。</figcaption>
            </figure>
            <div class="manual-callout"><b>定位代码：</b>也可在代码区点击高亮的代码行，右侧会切换到对应的缺陷条目。</div>
            <p class="manual-note">模型结论需人工复核。</p>
          </section>

          <section class="manual-section" id="manual-feedback">
            <h2>4. 用户反馈</h2>
            <p>模型结论与代码实际情况不符时，可在报告页右上角进入「用户反馈」。</p>
            <figure class="manual-figure">
              <img src="/assets/manual/manual-feedback-entry.png?v=20261120b" width="1360" height="140" alt="报告页右上角的用户反馈入口" loading="lazy" />
              <figcaption>报告页右上角的「用户反馈」按钮。</figcaption>
            </figure>
            <p>反馈类型共四种：</p>
            <ul>
              <li><b>误报：</b>该处代码不构成所报缺陷。</li>
              <li><b>位置错误：</b>缺陷存在，但指向的文件或行号有误。</li>
              <li><b>类型错误：</b>缺陷存在，但归入的类型不符。</li>
              <li><b>漏报：</b>代码中存在报告未列出的缺陷。</li>
            </ul>
            <div class="manual-callout key"><b>代码选取：</b>反馈页会显示报告对应的源码。可用搜索框定位代码；在代码区点击或拖选片段后，起始与结束行号会自动填入表单，无需手工录入。</div>
            <div class="manual-callout"><b>结果：</b>系统按反馈重新复核并生成一份新报告，原报告及其中的反馈记录保持不变。</div>
            <div class="manual-callout warn"><b>限制：</b>Agent Skill 包报告不支持用户反馈。</div>
          </section>

          <section class="manual-section" id="manual-records">
            <h2>5. 检测历史与数据总览</h2>
            <p>所有检测任务都在顶部导航的「检测历史」中，按提交时间倒序排列。</p>
            <ul>
              <li>支持关键字搜索与状态筛选，便于查找某次历史检测。</li>
              <li>每条记录可查看报告或删除；删除后不可恢复。</li>
              <li>运行中的任务可以取消。</li>
            </ul>
            <p><b>数据总览</b>汇总累计花费、检测次数、Token 总量、候选缺陷和平均单价，并提供近 7 天检测趋势与候选缺陷分布。</p>
          </section>

          <section class="manual-section" id="manual-cost">
            <h2>6. 费用与 Token</h2>
            <p>检测记录输入与输出 Token，花费按以下公式估算：</p>
            <p><code class="manual-code">金额 = 输入 Token ÷ 100 万 × 输入单价 + 输出 Token ÷ 100 万 × 输出单价</code></p>
            <p>默认单价为输入 ¥2、输出 ¥8（每百万 Token），可在花费卡片中修改。单价仅保存在当前浏览器，实际费用以模型供应商账单为准。</p>
          </section>

          <section class="manual-section" id="manual-privacy">
            <h2>7. 数据与隐私</h2>
            <ul>
              <li>模型配置与单价保存在当前浏览器，服务端不保存 API Key。</li>
              <li>检测时源码会发送至所配置的模型服务；请勿提交密钥、口令等敏感信息。</li>
              <li>检测记录保存在服务端；删除操作不可恢复。</li>
            </ul>
          </section>

          <section class="manual-section manual-faq" id="manual-faq">
            <h2>8. 常见问题</h2>
            <details><summary>模型配置保存失败</summary><p>检查接口地址、API Key 与模型名称，并确认服务器可访问该地址。</p></details>
            <details><summary>任务长时间处于排队状态</summary><p>刷新页面查看状态；持续不变时联系管理员检查检测框架。</p></details>
            <details><summary>报告显示部分完成</summary><p>部分文件未完成审查。查看「执行错误」；已完成文件仍会给出结论。</p></details>
            <details><summary>未发现缺陷</summary><p>检测仅覆盖已采集文件和已勾选类型，不代表代码不存在缺陷。</p></details>
            <details><summary>检测范围缺失</summary><p>早期报告未保存覆盖信息；重新检测可获取完整范围。</p></details>
            <details><summary>删除记录能否恢复</summary><p>不能。</p></details>
            <details><summary>更换设备后配置丢失</summary><p>模型配置仅保存在当前浏览器，需要重新填写。</p></details>
          </section>
        </div>
      </div>`;
    $$("[data-manual-target]", view).forEach((button) => {
      button.addEventListener("click", () => {
        const target = document.getElementById(button.getAttribute("data-manual-target"));
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  /* ------------------------------------------------------------- dashboard */

  const PRICING_KEY = "watcher.pricing";
  const DEFAULT_PRICING = { input: 2, output: 8 };
  let dashboardMode = "tokens";
  let dashboardPricing = readPricing();

  function readPricing() {
    try {
      const saved = JSON.parse(localStorage.getItem(PRICING_KEY) || "{}");
      const input = Number(saved.input);
      const output = Number(saved.output);
      return {
        input: Number.isFinite(input) && input >= 0 ? input : DEFAULT_PRICING.input,
        output: Number.isFinite(output) && output >= 0 ? output : DEFAULT_PRICING.output,
      };
    } catch (error) {
      return { input: DEFAULT_PRICING.input, output: DEFAULT_PRICING.output };
    }
  }

  function writePricing(input, output) {
    dashboardPricing = { input, output };
    localStorage.setItem(PRICING_KEY, JSON.stringify(dashboardPricing));
  }

  function formatMoney(value) {
    const number = Number(value || 0);
    if (!number) return "¥0";
    return number < 0.01 ? `¥${number.toFixed(3)}` : `¥${number.toFixed(2)}`;
  }

  function tokenCost(prompt, completion) {
    return (
      (Number(prompt || 0) / 1000000) * dashboardPricing.input +
      (Number(completion || 0) / 1000000) * dashboardPricing.output
    );
  }

  function priceConfigMarkup() {
    return `<div class="price-config">
      <span class="price-config-label">计费单价（¥ / 百万 tokens）</span>
      <label>输入 <input id="price-input" type="number" min="0" step="0.01" value="${dashboardPricing.input}" /></label>
      <label>输出 <input id="price-output" type="number" min="0" step="0.01" value="${dashboardPricing.output}" /></label>
      <button type="button" class="btn btn-ghost btn-xs" id="price-save">保存单价</button>
    </div>
    <p class="field-hint">金额 = 输入 tokens × 输入单价 + 输出 tokens × 输出单价，仅作估算。</p>`;
  }

  function formatCompact(value) {
    const number = Number(value || 0);
    if (number >= 1000000000) return `${(number / 1000000000).toFixed(1)}B`;
    if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`;
    if (number >= 1000) return `${(number / 1000).toFixed(1)}K`;
    return UI.formatNumber(number);
  }

  function dailyLineChartMarkup(daily, maxValue) {
    const rows = daily || [];
    const width = 640;
    const height = 230;
    const pad = { top: 30, right: 16, bottom: 32, left: 34 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;
    const yMax = Math.max(3, Number(maxValue) || 0);
    const ticks = Math.min(5, yMax);
    const step = rows.length > 1 ? innerW / (rows.length - 1) : 0;
    const points = rows.map((item, index) => {
      const value = Number(item.count) || 0;
      return {
        x: pad.left + index * step,
        y: pad.top + innerH - (value / yMax) * innerH,
        value,
        date: item.date,
      };
    });
    const grid = Array.from({ length: ticks + 1 }, (_, index) => {
      const y = pad.top + (innerH / ticks) * index;
      const value = Math.round(yMax * (1 - index / ticks));
      return `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" stroke="#e3ecf8" stroke-width="1" />
        <text x="${pad.left - 10}" y="${y + 4}" text-anchor="end" fill="#7c8da6" font-size="11">${value}</text>`;
    }).join("");
    const coords = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`);
    const area = points.length
      ? `M ${pad.left},${pad.top + innerH} L ${coords.join(" L ")} L ${(pad.left + innerW).toFixed(1)},${pad.top + innerH} Z`
      : "";
    const dots = points
      .map(
        (point) =>
          `<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="3.4" fill="#ffffff" stroke="#2f6fb8" stroke-width="2" />`
      )
      .join("");
    const valueLabels = points
      .map(
        (point) =>
          `<text x="${point.x.toFixed(1)}" y="${(point.y - 10).toFixed(1)}" text-anchor="middle" fill="#5f6f80" font-size="11">${point.value}</text>`
      )
      .join("");
    const dateLabels = points
      .map((point) => {
        const date = new Date(point.date + "T00:00:00");
        return `<text x="${point.x.toFixed(1)}" y="${height - 8}" text-anchor="middle" fill="#7c8da6" font-size="11">${date.getMonth() + 1}/${date.getDate()}</text>`;
      })
      .join("");
    return `<svg class="line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="近 7 天提交趋势">
      <defs>
        <linearGradient id="dash-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#2f6fb8" stop-opacity="0.2" />
          <stop offset="100%" stop-color="#2f6fb8" stop-opacity="0" />
        </linearGradient>
      </defs>
      ${grid}
      ${area ? `<path d="${area}" fill="url(#dash-area)" />` : ""}
      <polyline points="${coords.join(" ")}" fill="none" stroke="#2f6fb8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      ${dots}
      ${valueLabels}
      ${dateLabels}
    </svg>`;
  }

  function kpiRatioBar(leftLabel, leftText, rightLabel, rightText, leftAmount, rightAmount) {
    const left = Number(leftAmount) || 0;
    const right = Number(rightAmount) || 0;
    const total = left + right;
    const percent = total > 0 ? Math.round((left / total) * 100) : 0;
    return `<div class="kpi-ratio">
      <div class="kpi-ratio-track"><i style="width:${percent}%"></i><b style="width:${100 - percent}%"></b></div>
      <div class="kpi-ratio-legend"><span>${leftLabel} ${leftText}</span><span>${rightLabel} ${rightText}</span></div>
    </div>`;
  }

  function kpiChip(text, kind) {
    return `<span class="kpi-chip ${kind || ""}">${text}</span>`;
  }

  function kpiCardMarkup(label, value, foot, tone, iconName) {
    return `<article class="kpi-card ${tone}">
      <div class="kpi-head">
        <span class="kpi-label">${label}</span>
      </div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-foot">${foot}</div>
    </article>`;
  }

  async function renderDashboard(token) {
    const view = $("#view");
    view.innerHTML = `<div class="dash-page">${pageHead(
      "数据总览",
      "",
      `<a class="btn btn-primary" href="#/new">${UI.icon("plus", 16)}<span>新建检测</span></a>`
    )}<div id="dashboard-body">${UI.loading("正在汇总数据…")}</div></div>`;
    const stats = await API.stats();
    if (token !== routeToken) return;
    paintDashboard(stats);
  }

  function paintDashboard(stats) {
    const body = $("#dashboard-body");
    if (!body) return;
    const costMode = dashboardMode === "cost";
    const maxDaily = Math.max(1, ...(stats.daily || []).map((item) => item.count));
    const tokenDaily = stats.token_daily || [];
    const maxTokenDaily = Math.max(
      1,
      ...tokenDaily.map((item) => Number(item.total_tokens || 0))
    );
    const severityTotal = Object.values(stats.severity || {}).reduce((sum, value) => sum + value, 0) || 1;
    const costDaily = tokenDaily.map((item) => ({
      date: item.date,
      input: tokenCost(item.prompt_tokens, 0),
      output: tokenCost(0, item.completion_tokens),
      total: tokenCost(item.prompt_tokens, item.completion_tokens),
    }));
    const costInput = tokenCost(stats.prompt_tokens, 0);
    const costOutput = tokenCost(0, stats.completion_tokens);
    const costTotal = costInput + costOutput;
    const maxCostDaily = Math.max(1e-9, ...costDaily.map((item) => item.total));

    let chartBody;
    if (costMode) {
      chartBody =
        stats.total_tokens > 0
          ? `<div class="chart token-chart">
              ${costDaily
                .map((item) => {
                  const date = new Date(item.date + "T00:00:00");
                  const label = `${date.getMonth() + 1}/${date.getDate()}`;
                  const height = item.total ? Math.max(8, Math.round((item.total / maxCostDaily) * 100)) : 3;
                  const inputPercent = item.total ? Math.round((item.input / item.total) * 100) : 0;
                  return `<div class="chart-col">
                    <div class="chart-bar-wrap">
                      <div class="token-stack ${item.total ? "" : "zero"}" style="height:${height}%">
                        ${
                          item.total
                            ? `<i class="token-prompt" style="height:${inputPercent}%"></i><i class="token-completion" style="height:${100 - inputPercent}%"></i>`
                            : ""
                        }
                        <span>${formatMoney(item.total)}</span>
                      </div>
                    </div>
                    <small>${label}</small>
                  </div>`;
                })
                .join("")}
            </div>
            <div class="token-legend">
              <span><i class="token-prompt"></i>输入 ${formatMoney(costInput)}</span>
              <span><i class="token-completion"></i>输出 ${formatMoney(costOutput)}</span>
            </div>
            ${priceConfigMarkup()}`
          : `<div class="token-empty">
              <strong>还没有可计费数据</strong>
              <p>完成检测后按天显示花费估算。</p>
            </div>
            ${priceConfigMarkup()}`;
    } else {
      chartBody =
        stats.total_tokens > 0
          ? `<div class="chart token-chart">
              ${tokenDaily
                .map((item) => {
                  const date = new Date(item.date + "T00:00:00");
                  const label = `${date.getMonth() + 1}/${date.getDate()}`;
                  const total = Number(item.total_tokens || 0);
                  const prompt = Number(item.prompt_tokens || 0);
                  const completion = Number(item.completion_tokens || 0);
                  const known = prompt + completion;
                  const height = total ? Math.max(8, Math.round((total / maxTokenDaily) * 100)) : 3;
                  const promptPercent = known ? Math.round((prompt / known) * 100) : 0;
                  const completionPercent = known ? Math.max(0, 100 - promptPercent) : 0;
                  return `<div class="chart-col">
                    <div class="chart-bar-wrap">
                      <div class="token-stack ${total ? "" : "zero"}" style="height:${height}%">
                        ${
                          total
                            ? known
                              ? `<i class="token-prompt" style="height:${promptPercent}%"></i><i class="token-completion" style="height:${completionPercent}%"></i>`
                              : `<i class="token-unknown" style="height:100%"></i>`
                            : ""
                        }
                        <span>${UI.formatNumber(total)}</span>
                      </div>
                    </div>
                    <small>${label}</small>
                  </div>`;
                })
                .join("")}
            </div>
            <div class="token-legend">
              <span><i class="token-prompt"></i>输入 ${UI.formatNumber(stats.prompt_tokens || 0)}</span>
              <span><i class="token-completion"></i>输出 ${UI.formatNumber(stats.completion_tokens || 0)}</span>
            </div>`
          : `<div class="token-empty">
              <strong>还没有 token 数据</strong>
              <p>${stats.total_scans > 0 ? "历史任务未记录 Token 用量" : "完成检测后按天显示输入与输出 Token。"}</p>
            </div>`;
    }

    const averagePrice = stats.total_tokens > 0 ? (costTotal / stats.total_tokens) * 1000000 : 0;
    const completedScans = Number(
      stats.completed_scans !== undefined
        ? stats.completed_scans
        : Math.max(0, stats.total_scans - stats.running_scans)
    );
    const kpiGrid = `<div class="kpi-grid">
      ${kpiCardMarkup(
        "累计花费",
        formatMoney(costTotal),
        kpiRatioBar("输入", formatMoney(costInput), "输出", formatMoney(costOutput), costInput, costOutput),
        "kpi-spend",
        "coins"
      )}
      ${kpiCardMarkup(
        "检测次数",
        UI.formatNumber(stats.total_scans),
        `<div class="kpi-chips">${kpiChip(
          `已完成 <b>${UI.formatNumber(completedScans)}</b>`,
          "ok"
        )}${kpiChip(`进行中 <b>${UI.formatNumber(stats.running_scans)}</b>`, stats.running_scans ? "warn" : "muted")}</div>`,
        "kpi-scans",
        "bolt"
      )}
      ${kpiCardMarkup(
        "Token 总量",
        formatCompact(stats.total_tokens),
        kpiRatioBar(
          "输入",
          formatCompact(stats.prompt_tokens),
          "输出",
          formatCompact(stats.completion_tokens),
          stats.prompt_tokens,
          stats.completion_tokens
        ),
        "kpi-tokens",
        "layers"
      )}
      ${kpiCardMarkup(
        "候选缺陷",
        UI.formatNumber(stats.total_findings),
        `<div class="kpi-chips">${kpiChip(
          `高危及以上 <b>${UI.formatNumber(stats.high_findings)}</b>`,
          stats.high_findings ? "warn" : "muted"
        )}${kpiChip(`${UI.formatNumber(stats.languages)} 种语言`, "muted")}</div>`,
        "kpi-findings",
        "shieldAlert"
      )}
      ${kpiCardMarkup(
        "平均单价",
        stats.total_tokens > 0 ? formatMoney(averagePrice) : "—",
        `<div class="kpi-chips">${kpiChip("¥ / 百万 Token", "tone")}</div>`,
        "kpi-price",
        "yen"
      )}
    </div>`;

    body.innerHTML = `
      ${kpiGrid}

      <div class="dash-grid">
        <section class="card">
          <div class="card-head">
            <div><h2>检测趋势</h2><p>最近 7 天 · 检测次数</p></div>
            <span class="card-note">共 ${UI.formatNumber(stats.daily.reduce((sum, item) => sum + item.count, 0))} 次</span>
          </div>
          ${dailyLineChartMarkup(stats.daily, maxDaily)}
        </section>

        <section class="card">
          <div class="card-head">
            <div><h2>候选缺陷分布</h2></div>
            <span class="card-note">按严重程度</span>
          </div>
          <div class="severity-list">
            ${Object.keys(UI.SEVERITY)
              .map((key) => {
                const meta = UI.SEVERITY[key];
                const value = stats.severity[key] || 0;
                const width = value ? Math.max(4, Math.round((value / severityTotal) * 100)) : 0;
                return `<div class="severity-row">
                  <span class="sev ${meta.cls}">${meta.label}</span>
                  <div class="severity-track"><i class="${meta.cls}" style="width:${width}%"></i></div>
                  <b>${value}</b>
                </div>`;
              })
              .join("")}
          </div>
        </section>
      </div>

      <section class="card token-card">
        <div class="card-head">
          <div><h2>${costMode ? "近 7 天花费估算" : "近 7 天 Token 消耗"}</h2></div>
          <div class="card-tools">
            <div class="seg" role="tablist" aria-label="展示方式">
              <button type="button" role="tab" data-dashboard-mode="tokens" class="${costMode ? "" : "active"}" aria-selected="${costMode ? "false" : "true"}">Token 用量</button>
              <button type="button" role="tab" data-dashboard-mode="cost" class="${costMode ? "active" : ""}" aria-selected="${costMode ? "true" : "false"}">花费</button>
            </div>
            <span class="card-note">${costMode ? `共 ${formatMoney(costTotal)}` : `共 ${UI.formatNumber(stats.total_tokens || 0)} tokens`}</span>
          </div>
        </div>
        ${chartBody}
      </section>

      <section class="card">
        <div class="card-head">
          <div><h2>最近检测</h2></div>
          <a class="text-link" href="#/scans">全部记录</a>
        </div>
        ${
          stats.recent.length
            ? `<div class="table-wrap"><table class="table">
                <thead><tr><th>源码</th><th>语言</th><th>状态</th><th>缺陷</th><th>提交时间</th></tr></thead>
                <tbody>${stats.recent
                  .map(
                    (scan) => `<tr class="clickable" tabindex="0" role="button" data-href="#/scans/${scan.id}">
                      <td><div class="cell-title"><span>${UI.esc(scan.source_name)}</span></div></td>
                      <td>${UI.esc(languageName(scan.language))}</td>
                      <td>${UI.statusChip(scan.status)}</td>
                      <td>${scan.status === "succeeded" || scan.status === "partial" ? `<b>${scan.finding_count}</b>` : "—"}</td>
                      <td class="muted">${UI.timeAgo(scan.created_at)}</td>
                    </tr>`
                  )
                  .join("")}</tbody>
              </table></div>`
            : UI.emptyState(
                "还没有检测记录",
                "配置模型服务后即可提交源码。",
                `<a class="btn btn-primary" href="#/new">新建检测</a>`
              )
        }
      </section>`;
    bindDashboard(stats);
  }

  function bindDashboard(stats) {
    const body = $("#dashboard-body");
    if (!body) return;
    $$("[data-dashboard-mode]", body).forEach((button) => {
      button.addEventListener("click", () => {
        dashboardMode = button.getAttribute("data-dashboard-mode");
        paintDashboard(stats);
      });
    });
    const save = $("#price-save", body);
    if (save) {
      save.addEventListener("click", () => {
        const inputField = $("#price-input", body);
        const outputField = $("#price-output", body);
        const input = Number(inputField ? inputField.value : NaN);
        const output = Number(outputField ? outputField.value : NaN);
        if (!Number.isFinite(input) || !Number.isFinite(output) || input < 0 || output < 0) {
          UI.toast("单价需要是大于等于 0 的数字", "error");
          return;
        }
        writePricing(input, output);
        UI.toast("计费单价已保存", "success");
        paintDashboard(stats);
      });
    }
    $$(".clickable", body).forEach((row) => {
      const openRow = () => {
        location.hash = row.getAttribute("data-href");
      };
      row.addEventListener("click", openRow);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openRow();
        }
      });
    });
  }

  /* -------------------------------------------------------------- new scan */

  function ensureNewScanState() {
    const languages = state.catalog.languages || [];
    if (!languages.length) return null;
    const ns = state.newScan;
    if (!languages.some((item) => item.code === ns.language)) {
      ns.language = languages[0].code;
      ns.typesLanguage = null;
    }
    const language = languageEntry(ns.language);
    if (ns.typesLanguage !== ns.language) {
      ns.types = language.defect_types.map((item) => item.code);
      ns.typesLanguage = ns.language;
    }
    if (isPackageLanguage(language.code)) {
      ns.mode = "upload";
    }
    if (!ns.filename || !ns.filenameTouched) {
      ns.filename = "snippet" + ((language.extensions || [])[0] || ".txt");
    }
    return ns;
  }

  async function renderNewScan(token) {
    const view = $("#view");
    const framework = state.catalog.framework || {};
    if (!(state.catalog.languages || []).length) {
      view.innerHTML =
        pageHead("新建检测", "需要先连接检测框架", "") +
        `<div class="card error-card">
          <div class="error-icon">${UI.icon("alert", 22)}</div>
          <div>
            <h3>没有可用的检测能力</h3>
            <p>${UI.esc(framework.error || "后端没有读取到任何语言 Skill。")}</p>
            <p class="muted mono">${UI.esc(framework.path || "")}</p>
            <button class="btn btn-ghost btn-sm" id="reload-catalog">重新读取</button>
          </div>
        </div>`;
      $("#reload-catalog").addEventListener("click", async () => {
        try {
          state.catalog = await API.catalog();
          UI.toast("已重新读取框架能力", "success");
          renderNewScan(token);
        } catch (error) {
          UI.toast(error.message, "error");
        }
      });
      return;
    }
    ensureNewScanState();
    paintNewScan();
    bindNewScan();
  }

  function paintNewScan() {
    const view = $("#view");
    const ns = state.newScan;
    const language = languageEntry(ns.language);
    const packageMode = isPackageLanguage(language.code);
    const extensions = (language.extensions || []).join("、");
    const acceptAttr = packageMode
      ? ""
      : `accept="${UI.esc((language.extensions || []).join(","))}"`;
    view.innerHTML =
      pageHead("新建检测", "", "") +
      `<form id="scan-form" class="scan-layout" novalidate>
        <div class="scan-main">
          <section class="card">
            <div class="card-head">
              <div class="step-head"><span class="step">1</span><div><h2>选择代码类型</h2></div></div>
            </div>
            <div class="lang-grid">
              ${state.catalog.languages
                .map(
                  (item) => `<button type="button" class="lang-card ${item.code === ns.language ? "active" : ""}" data-lang="${UI.esc(item.code)}">
                    ${languageMark(item)}
                    <span class="lang-text"><b>${UI.esc(item.name)}</b><small>${UI.esc(extensionSummary(item))}</small></span>
                    <span class="lang-check">${UI.icon("check", 14)}</span>
                  </button>`
                )
                .join("")}
            </div>
          </section>

          <section class="card">
            <div class="card-head">
              <div class="step-head"><span class="step">2</span><div><h2>${packageMode ? "提交 Agent Skill 包" : "提交源码"}</h2></div></div>
              ${
                packageMode
                  ? ""
                  : `<div class="segment" id="source-segment">
                      <button type="button" data-mode="upload" class="${ns.mode === "upload" ? "active" : ""}">${UI.icon("upload", 16)}上传文件</button>
                      <button type="button" data-mode="paste" class="${ns.mode === "paste" ? "active" : ""}">${UI.icon("clipboard", 16)}粘贴代码</button>
                      <button type="button" data-mode="url" class="${ns.mode === "url" ? "active" : ""}">${UI.icon("link", 16)}仓库链接</button>
                    </div>`
              }
            </div>
            <div id="source-panel">
              ${
                ns.mode === "url"
                  ? `<label class="field">
                      <span>GitHub 仓库地址</span>
                      <input id="repo-url" value="${UI.esc(ns.repoUrl)}" maxlength="300" placeholder="https://github.com/owner/repo" spellcheck="false" />
                    </label>
                    <div class="field-row">
                      <label class="field"><span>分支 / 标签（选填）</span><input id="repo-ref" value="${UI.esc(ns.repoRef)}" maxlength="120" placeholder="默认分支" spellcheck="false" /></label>
                      <label class="field"><span>子目录（选填）</span><input id="repo-subdir" value="${UI.esc(ns.repoSubdir)}" maxlength="200" placeholder="如 src/" spellcheck="false" /></label>
                    </div>
                    <p class="muted small">仅限公开仓库，支持 /tree/ 子目录链接，压缩包 ≤ 60 MB</p>`
                  : ns.mode === "upload"
                  ? `<div class="dropzone" id="dropzone" tabindex="0" role="button">
                      <div class="drop-icon">${UI.icon("upload", 24)}</div>
                      <strong>${packageMode ? "拖拽 Skill 包文件到此处，或点击上传" : "拖拽文件到此处，或点击上传"}</strong>
                      <span>${packageMode ? "完整 Skill 包（含 SKILL.md） · 单文件 ≤ 2 MB · 最多 100 个文件" : `支持 ${UI.esc(extensions)} · 单文件 ≤ 2 MB · 最多 100 个文件`}</span>
                    </div>
                    <div class="drop-actions">
                      <button type="button" class="btn btn-ghost btn-sm" id="pick-file">${UI.icon("upload", 16)}选择文件</button>
                      <button type="button" class="btn btn-ghost btn-sm" id="pick-dir">${UI.icon("folder", 16)}选择文件夹</button>
                      ${packageMode ? '<span class="muted small">包根目录需包含 SKILL.md</span>' : ""}
                    </div>
                    <input type="file" id="file-input" multiple ${acceptAttr} hidden />
                    <input type="file" id="dir-input" webkitdirectory multiple hidden />
                    <div id="file-list" class="file-list"></div>`
                  : `<label class="field">
                      <span>文件名</span>
                      <input id="paste-filename" value="${UI.esc(ns.filename)}" maxlength="120" />
                    </label>
                    <label class="field">
                      <span>代码内容</span>
                      <textarea id="paste-code" class="code-input" rows="14" placeholder="粘贴 ${UI.esc(language.name)} 源码" spellcheck="false">${UI.esc(ns.code)}</textarea>
                    </label>
                    <p class="muted small" id="max-chars-hint">单文件上限 ${UI.formatNumber(ns.options.max_file_chars || 30000)} 字符，可在高级参数中调整</p>`
              }
            </div>
          </section>

          <section class="card">
            <div class="card-head">
              <div class="step-head"><span class="step">3</span><div><h2>选择缺陷类型</h2></div></div>
              <div class="chip-actions">
                <button type="button" class="link-btn" id="select-all">全选</button>
                <button type="button" class="link-btn" id="select-none">清空</button>
              </div>
            </div>
            <div class="chip-groups">
              ${groupDefectTypes(language.defect_types)
                .map(
                  (group) => `<div class="chip-group">
                    <span class="chip-group-label">${UI.icon(group.icon, 17)}${UI.esc(group.label)}</span>
                    <div class="chip-grid">
                      ${group.items
                        .map((item) => {
                          const name = defectName(item);
                          const showCode = /^CWE-/.test(item.code);
                          return `<label class="chip">
                            <input type="checkbox" value="${UI.esc(item.code)}" ${ns.types.includes(item.code) ? "checked" : ""} />
                            <span>${showCode ? `<b>${UI.esc(item.code)}</b>` : ""}${UI.esc(name || item.code)}</span>
                          </label>`;
                        })
                        .join("")}
                    </div>
                  </div>`
                )
                .join("")}
            </div>
          </section>
        </div>

        <aside class="scan-side">
          <section class="card side-form">
            <div class="step-head"><span class="step">4</span><div><h2>确认模型并提交</h2></div></div>
            ${
              modelConfigured()
                ? `<div class="model-box">
                    <div><span>模型</span><b>${UI.esc(state.model.model)}</b></div>
                    <div><span>根地址</span><b class="mono">${UI.esc(state.model.base_url)}</b></div>
                    <div><span>API Key</span><b>${maskedKey(state.model.api_key)}</b></div>
                  </div>
                  <p class="field-hint"><a class="text-link" href="#/settings">修改配置</a></p>`
                : `<div class="inline-warning">${UI.icon("key", 18)}<div><b>未配置模型服务</b><p>需要 API 根地址、模型名称和 API Key。</p><a class="text-link" href="#/settings">去配置</a></div></div>`
            }

            <details class="advanced">
              <summary>高级参数</summary>
              <div class="field-row">
                <label class="field"><span>最多文件数</span><input type="number" id="opt-max-files" min="1" max="200" value="${ns.options.max_files}" /></label>
                <label class="field"><span>最多模型调用</span><input type="number" id="opt-max-calls" min="1" max="200" value="${ns.options.max_model_calls}" /></label>
              </div>
              <div class="field-row">
                <label class="field"><span>总超时（秒）</span><input type="number" id="opt-timeout" min="30" max="3600" value="${ns.options.timeout}" /></label>
                <label class="field"><span>单请求超时（秒）</span><input type="number" id="opt-request-timeout" min="10" max="600" value="${ns.options.request_timeout}" /></label>
              </div>
              <label class="field"><span>单文件最大字符数</span><input type="number" id="opt-max-chars" min="1000" max="200000" value="${ns.options.max_file_chars}" /></label>
              <label class="checkbox-line"><input type="checkbox" id="opt-json-mode" ${ns.options.json_mode ? "checked" : ""} /><span>请求供应商 JSON 模式</span></label>
            </details>

            <div class="form-error" id="scan-error" hidden></div>
            <button type="submit" class="btn btn-primary btn-block" id="scan-submit"><span>开始检测</span></button>
            <p class="submit-note">${packageMode ? "整个 Skill 包计 1 次模型调用" : "每个匹配文件调用一次模型"}</p>
          </section>
        </aside>
      </form>`;
  }

  function bindNewScan() {
    const ns = state.newScan;
    const form = $("#scan-form");
    const errorBox = $("#scan-error");

    function showError(message) {
      errorBox.hidden = false;
      errorBox.textContent = message;
    }

    $$("[data-lang]").forEach((button) => {
      button.addEventListener("click", () => {
        const code = button.getAttribute("data-lang");
        if (code === ns.language) return;
        saveSourceInputs();
        ns.language = code;
        ns.typesLanguage = null;
        ns.files = [];
        ns.filenameTouched = false;
        ensureNewScanState();
        paintNewScan();
        bindNewScan();
      });
    });

    function saveSourceInputs() {
      const paste = $("#paste-code");
      if (paste) ns.code = paste.value;
      const filename = $("#paste-filename");
      if (filename) {
        ns.filename = filename.value;
        ns.filenameTouched = true;
      }
      const repoUrl = $("#repo-url");
      if (repoUrl) ns.repoUrl = repoUrl.value.trim();
      const repoRef = $("#repo-ref");
      if (repoRef) ns.repoRef = repoRef.value.trim();
      const repoSubdir = $("#repo-subdir");
      if (repoSubdir) ns.repoSubdir = repoSubdir.value.trim();
    }

    $$("[data-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        const mode = button.getAttribute("data-mode");
        if (mode === ns.mode) {
          if (mode === "upload") {
            const input = $("#file-input");
            if (input) input.click();
          }
          return;
        }
        saveSourceInputs();
        ns.mode = mode;
        paintNewScan();
        bindNewScan();
      });
    });

    const dropzone = $("#dropzone");
    const fileInput = $("#file-input");
    const dirInput = $("#dir-input");
    if (dropzone && fileInput) {
      dropzone.addEventListener("click", () => fileInput.click());
      dropzone.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          fileInput.click();
        }
      });
      ["dragenter", "dragover"].forEach((name) =>
        dropzone.addEventListener(name, (event) => {
          event.preventDefault();
          dropzone.classList.add("dragging");
        })
      );
      ["dragleave", "drop"].forEach((name) =>
        dropzone.addEventListener(name, (event) => {
          event.preventDefault();
          dropzone.classList.remove("dragging");
        })
      );
      dropzone.addEventListener("drop", (event) => {
        addFiles(Array.from(event.dataTransfer.files || []), false);
      });
      fileInput.addEventListener("change", () => {
        addFiles(Array.from(fileInput.files || []), false);
        fileInput.value = "";
      });
      $("#pick-file").addEventListener("click", () => fileInput.click());
      $("#pick-dir").addEventListener("click", () => dirInput.click());
      dirInput.addEventListener("change", () => {
        addFiles(Array.from(dirInput.files || []), true);
        dirInput.value = "";
      });
    }

    const list = $("#file-list");
    if (list) paintFileList();

    const pasteCode = $("#paste-code");
    if (pasteCode) {
      pasteCode.addEventListener("input", () => {
        ns.code = pasteCode.value;
      });
      pasteCode.addEventListener("keydown", (event) => {
        if (event.key === "Tab") {
          event.preventDefault();
          const start = pasteCode.selectionStart;
          const end = pasteCode.selectionEnd;
          pasteCode.value = pasteCode.value.slice(0, start) + "    " + pasteCode.value.slice(end);
          pasteCode.selectionStart = pasteCode.selectionEnd = start + 4;
          ns.code = pasteCode.value;
        }
      });
    }
    const pasteName = $("#paste-filename");
    if (pasteName) {
      pasteName.addEventListener("input", () => {
        ns.filename = pasteName.value;
        ns.filenameTouched = true;
      });
    }
    const repoUrl = $("#repo-url");
    if (repoUrl) {
      repoUrl.addEventListener("input", () => {
        ns.repoUrl = repoUrl.value.trim();
      });
    }
    const repoRef = $("#repo-ref");
    if (repoRef) {
      repoRef.addEventListener("input", () => {
        ns.repoRef = repoRef.value.trim();
      });
    }
    const repoSubdir = $("#repo-subdir");
    if (repoSubdir) {
      repoSubdir.addEventListener("input", () => {
        ns.repoSubdir = repoSubdir.value.trim();
      });
    }

    $$(".chip input").forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          if (!ns.types.includes(checkbox.value)) ns.types.push(checkbox.value);
        } else {
          ns.types = ns.types.filter((code) => code !== checkbox.value);
        }
      });
    });
    $("#select-all").addEventListener("click", () => {
      ns.types = languageEntry(ns.language).defect_types.map((item) => item.code);
      $$(".chip input").forEach((checkbox) => (checkbox.checked = true));
    });
    $("#select-none").addEventListener("click", () => {
      ns.types = [];
      $$(".chip input").forEach((checkbox) => (checkbox.checked = false));
    });

    const optionBindings = [
      ["#opt-max-files", "max_files"],
      ["#opt-max-calls", "max_model_calls"],
      ["#opt-timeout", "timeout"],
      ["#opt-request-timeout", "request_timeout"],
      ["#opt-max-chars", "max_file_chars"],
    ];
    optionBindings.forEach(([selector, key]) => {
      const input = $(selector);
      if (input) {
        input.addEventListener("input", () => {
          ns.options[key] = Number(input.value);
          if (key === "max_file_chars") {
            const hint = $("#max-chars-hint");
            if (hint) {
              const typed = Number(input.value);
              const shown = Number.isFinite(typed) && typed > 0 ? typed : 30000;
              hint.textContent = `单文件上限 ${UI.formatNumber(shown)} 字符，可在高级参数中调整`;
            }
          }
        });
      }
    });
    const jsonMode = $("#opt-json-mode");
    if (jsonMode) {
      jsonMode.addEventListener("change", () => {
        ns.options.json_mode = jsonMode.checked;
      });
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorBox.hidden = true;
      const language = languageEntry(ns.language);
      if (!language) return showError("请选择代码类型");
      if (!ns.types.length) return showError("至少选择一种缺陷类型");
      if (!modelConfigured()) return showError("请先在「模型设置」中填写根地址、模型和 API Key");
      if (ns.mode === "upload" && !ns.files.length) {
        return showError(isPackageLanguage(ns.language) ? "请上传包含 SKILL.md 的 Agent Skill 包" : "请选择要检测的源码文件");
      }
      if (
        isPackageLanguage(ns.language) &&
        !ns.files.some((item) => String(item.path).split("/").pop() === "SKILL.md")
      ) {
        return showError("请在 Agent Skill 包根目录放置 SKILL.md，一次上传一个包");
      }
      if (ns.mode === "paste") {
        const code = $("#paste-code").value;
        ns.code = code;
        if (!code.trim()) return showError("请粘贴需要检测的代码");
        ns.filename = $("#paste-filename").value.trim();
        if (!ns.filename) return showError("请填写文件名");
      }
      if (ns.mode === "url") {
        ns.repoUrl = $("#repo-url").value.trim();
        ns.repoRef = $("#repo-ref").value.trim();
        ns.repoSubdir = $("#repo-subdir").value.trim();
        if (!ns.repoUrl) return showError("请填写 GitHub 仓库地址");
        if (!/^(https?:\/\/)?(www\.)?github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+/i.test(ns.repoUrl)) {
          return showError("仓库地址需形如 https://github.com/owner/repo");
        }
      }
      const button = $("#scan-submit");
      button.disabled = true;
      button.innerHTML = `<span class="spinner small"></span><span>正在提交…</span>`;
      try {
        const formData = new FormData();
        formData.append("language", ns.language);
        formData.append("defect_types", JSON.stringify(ns.types));
        formData.append("base_url", state.model.base_url);
        formData.append("model", state.model.model);
        formData.append("api_key", state.model.api_key);
        formData.append("max_files", String(ns.options.max_files));
        formData.append("max_model_calls", String(ns.options.max_model_calls));
        formData.append("timeout", String(ns.options.timeout));
        formData.append("request_timeout", String(ns.options.request_timeout));
        formData.append("max_file_chars", String(ns.options.max_file_chars));
        formData.append("json_mode", ns.options.json_mode ? "true" : "false");
        if (ns.mode === "paste") {
          formData.append("source_kind", "paste");
          formData.append("code", ns.code);
          formData.append("filename", ns.filename);
        } else if (ns.mode === "url") {
          formData.append("source_kind", "url");
          formData.append("repo_url", ns.repoUrl);
          formData.append("repo_ref", ns.repoRef);
          formData.append("repo_subdir", ns.repoSubdir);
        } else {
          formData.append("source_kind", "upload");
          formData.append("paths", JSON.stringify(ns.files.map((item) => item.path)));
          ns.files.forEach((item) => formData.append("files", item.file, item.file.name));
        }
        const scan = await API.createScan(formData);
        state.newScan.files = [];
        state.newScan.code = "";
        state.newScan.filenameTouched = false;
        UI.toast("任务已提交", "success");
        location.hash = `#/scans/${scan.id}`;
      } catch (error) {
        showError(error.message || "提交失败");
        UI.toast(error.message || "提交失败", "error");
      } finally {
        button.disabled = false;
        button.innerHTML = `<span>开始检测</span>`;
      }
    });
  }

  function addFiles(fileList, keepPaths) {
    const ns = state.newScan;
    const language = languageEntry(ns.language);
    if (!language) return;
    const packageMode = isPackageLanguage(language.code);
    const extensions = (language.extensions || []).map((item) => item.toLowerCase());
    let added = 0;
    let skipped = 0;
    for (const file of fileList) {
      const path = keepPaths && file.webkitRelativePath ? file.webkitRelativePath : file.name;
      if (packageMode && path.split("/").some((part) => PACKAGE_EXCLUDED_DIRS.has(part))) {
        skipped += 1;
        continue;
      }
      if (!packageMode && !extensions.some((extension) => path.toLowerCase().endsWith(extension))) {
        skipped += 1;
        continue;
      }
      if (ns.files.length >= 100) {
        UI.toast("单次最多上传 100 个文件", "warn");
        break;
      }
      const key = `${path}|${file.size}|${file.lastModified}`;
      if (ns.files.some((item) => item.key === key)) continue;
      ns.files.push({ file, path, key });
      added += 1;
    }
    paintFileList();
    if (added) UI.toast(`已加入 ${added} 个文件`, "success");
    if (skipped) {
      UI.toast(
        packageMode
          ? `已跳过 ${skipped} 个排除目录中的文件`
          : `已跳过 ${skipped} 个非 ${language.extensions.join("/")} 文件`,
        "warn"
      );
    }
  }

  function paintFileList() {
    const list = $("#file-list");
    if (!list) return;
    const ns = state.newScan;
    if (!ns.files.length) {
      list.innerHTML = `<p class="muted small">尚未选择文件。</p>`;
      return;
    }
    list.innerHTML = ns.files
      .map(
        (item, index) => `<div class="file-row">
          <div class="file-main"><b title="${UI.esc(item.path)}">${UI.esc(item.path)}</b><small>${UI.formatBytes(item.file.size)}</small></div>
          <button type="button" class="icon-btn" data-remove-file="${index}" aria-label="移除">${UI.icon("x", 16)}</button>
        </div>`
      )
      .join("");
    $$("[data-remove-file]", list).forEach((button) => {
      button.addEventListener("click", () => {
        ns.files.splice(Number(button.getAttribute("data-remove-file")), 1);
        paintFileList();
      });
    });
  }

  /* ------------------------------------------------------------- scan list */

  const SOURCE_KIND_LABELS = {
    upload: "文件上传",
    paste: "粘贴代码",
    url: "GitHub 仓库",
    feedback: "反馈复核",
    retry: "失败文件重试",
  };

  function scanProgressCell(scan) {
    const total = Number(scan.total_files || 0);
    const done = Number(scan.completed_files || 0);
    const text = total ? `${UI.formatNumber(done)} / ${UI.formatNumber(total)}` : "—";
    if (!(scan.status === "queued" || scan.status === "running") || !total) return text;
    const percent = Math.min(100, Math.round((done / total) * 100));
    return `${text}<span class="cell-progress"><i style="width:${percent}%"></i></span>`;
  }

  /** Delete a scan; when it has feedback children, offer to remove them together. */
  async function deleteScanRecord(id) {
    try {
      await API.deleteScan(id);
      return true;
    } catch (error) {
      if (error.status !== 409 || !/反馈/.test(error.message || "")) throw error;
      const ok = await UI.confirm({
        title: "连同后续报告一起删除",
        message: `${error.message}。后续报告与本报告会同时删除，且无法恢复。`,
        confirmText: "一并删除",
        danger: true,
      });
      if (!ok) return false;
      await API.deleteScan(id, true);
      return true;
    }
  }

  async function renderScanList(token) {
    const view = $("#view");
    view.innerHTML =
      pageHead("检测历史", "", `<a class="btn btn-primary" href="#/new">${UI.icon("plus", 16)}<span>新建检测</span></a>`) +
      `<section class="card">
        <div class="filter-bar">
          <label class="search-box">${UI.icon("search", 16)}<input id="scan-search" placeholder="搜索任务名称或模型" value="${UI.esc(state.filters.q)}" /></label>
          <select id="filter-status">
            <option value="">全部状态</option>
            ${["queued", "running", "succeeded", "partial", "failed", "cancelled"]
              .map((key) => `<option value="${key}" ${state.filters.status === key ? "selected" : ""}>${UI.STATUS[key].label}</option>`)
              .join("")}
          </select>
          <select id="filter-language">
            <option value="">全部语言</option>
            ${(state.catalog.languages || [])
              .map((item) => `<option value="${item.code}" ${state.filters.language === item.code ? "selected" : ""}>${UI.esc(item.name)}</option>`)
              .join("")}
          </select>
          <button type="button" class="btn btn-ghost" id="refresh-scans">${UI.icon("refresh", 16)}刷新</button>
        </div>
        <div id="scan-table">${UI.loading("正在读取记录…")}</div>
      </section>`;
    bindListControls(token);
    await fetchScanPage(token);
  }

  function bindListControls(token) {
    const search = $("#scan-search");
    let timer = null;
    search.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        state.filters.q = search.value.trim();
        state.filters.page = 1;
        fetchScanPage(token);
      }, 320);
    });
    $("#filter-status").addEventListener("change", (event) => {
      state.filters.status = event.target.value;
      state.filters.page = 1;
      fetchScanPage(token);
    });
    $("#filter-language").addEventListener("change", (event) => {
      state.filters.language = event.target.value;
      state.filters.page = 1;
      fetchScanPage(token);
    });
    $("#refresh-scans").addEventListener("click", () => fetchScanPage(token));
  }

  async function fetchScanPage(token) {
    const holder = $("#scan-table");
    if (!holder) return;
    try {
      const data = await API.scans({
        page: state.filters.page,
        page_size: 10,
        status: state.filters.status,
        language: state.filters.language,
        q: state.filters.q,
      });
      if (token !== routeToken) return;
      const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
      if (state.filters.page > totalPages) {
        state.filters.page = totalPages;
        return fetchScanPage(token);
      }
      if (!data.items.length) {
        holder.innerHTML = UI.emptyState(
          state.filters.q || state.filters.status || state.filters.language ? "没有匹配的任务" : "还没有检测记录",
          state.filters.q || state.filters.status || state.filters.language
            ? "调整筛选条件后再试。"
            : "提交源码后，检测任务会显示在这里。",
          `<a class="btn btn-primary" href="#/new">新建检测</a>`
        );
        return;
      }
      holder.innerHTML = `
        <div class="table-wrap"><table class="table scan-table">
          <thead><tr><th>任务 / 来源</th><th>语言</th><th>状态</th><th>文件进度</th><th>候选缺陷</th><th>Tokens</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            ${data.items
              .map(
                (scan) => `<tr>
                  <td><a class="cell-title" href="#/scans/${scan.id}"><span>${UI.esc(scan.source_name)}</span></a><small class="cell-sub">${UI.esc(SOURCE_KIND_LABELS[scan.source_kind] || "源码")} · #${UI.esc(String(scan.id).slice(0, 6))}${scan.model_name ? ` · ${UI.esc(scan.model_name)}` : ""}</small></td>
                  <td>${UI.esc(languageName(scan.language))}</td>
                  <td>${UI.statusChip(scan.status)}${scan.status === "running" && scan.status_detail ? `<small class="cell-sub">${UI.esc(scan.status_detail)}</small>` : ""}</td>
                  <td class="num">${scanProgressCell(scan)}</td>
                  <td class="num">${scan.status === "succeeded" || scan.status === "partial" ? `<b>${scan.finding_count}</b> <span class="muted">条</span>` : "—"}</td>
                  <td class="num">${scan.total_tokens ? UI.formatNumber(scan.total_tokens) : "—"}</td>
                  <td class="muted num" title="${UI.esc(UI.formatDateTime(scan.created_at))}">${UI.timeAgo(scan.created_at)}</td>
                  <td><div class="row-actions">
                    <a class="text-link" href="#/scans/${scan.id}">${scan.status === "queued" || scan.status === "running" ? "查看进度" : "查看报告"}</a>
                    ${
                      scan.status === "queued" || scan.status === "running"
                        ? `<button type="button" class="link-btn danger-text" data-cancel-scan="${scan.id}">取消</button>`
                        : ""
                    }
                    ${
                      ["succeeded", "partial", "failed", "cancelled"].includes(scan.status)
                        ? `<button type="button" class="icon-btn danger" data-delete-scan="${scan.id}" title="删除">${UI.icon("trash", 15)}</button>`
                        : ""
                    }
                  </div></td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table></div>
        <div class="pagination">
          <span>共 ${UI.formatNumber(data.total)} 条 / 第 ${data.page}/${totalPages} 页</span>
          <div>
            <button type="button" class="btn btn-ghost btn-sm" data-page="${data.page - 1}" ${data.page <= 1 ? "disabled" : ""}>上一页</button>
            <button type="button" class="btn btn-ghost btn-sm" data-page="${data.page + 1}" ${data.page >= totalPages ? "disabled" : ""}>下一页</button>
          </div>
        </div>`;
      $$("[data-page]").forEach((button) => {
        button.addEventListener("click", () => {
          state.filters.page = Number(button.getAttribute("data-page"));
          fetchScanPage(token);
        });
      });
      $$("[data-cancel-scan]").forEach((button) => {
        button.addEventListener("click", async () => {
          const id = button.getAttribute("data-cancel-scan");
          const ok = await UI.confirm({
            title: "取消检测任务",
            message: "正在进行的模型请求会被中止，已产生的部分结果可能不会归档。",
            confirmText: "取消任务",
            danger: true,
          });
          if (!ok) return;
          button.disabled = true;
          try {
            await API.cancelScan(id);
            UI.toast("正在取消任务…", "info");
            fetchScanPage(token);
          } catch (error) {
            button.disabled = false;
            UI.toast(error.message, "error");
          }
        });
      });
      $$("[data-delete-scan]").forEach((button) => {
        button.addEventListener("click", async () => {
          const id = button.getAttribute("data-delete-scan");
          const ok = await UI.confirm({
            title: "删除检测记录",
            message: "任务、源码快照与报告都会被删除，且无法恢复。",
            confirmText: "删除",
            danger: true,
          });
          if (!ok) return;
          try {
            const removed = await deleteScanRecord(id);
            if (!removed) return;
            UI.toast("记录已删除", "success");
            fetchScanPage(token);
          } catch (error) {
            UI.toast(error.message, "error");
          }
        });
      });
    } catch (error) {
      if (token !== routeToken) return;
      holder.innerHTML = errorPanel(error, () => fetchScanPage(token));
      bindRetry(() => fetchScanPage(token));
    }
  }

  /* --------------------------------------------------------------- feedback */

  const FEEDBACK_KINDS = {
    false_positive: "这不是漏洞",
    false_negative: "漏掉了漏洞",
    location: "位置标错了",
    classification: "缺陷类型判断错了",
  };

  const FEEDBACK_STATUS = {
    retain: "保留原缺陷",
    replace: "已修正缺陷",
    withdraw: "已撤回缺陷",
    added: "已新增缺陷",
    already_covered: "已被覆盖",
    no_supported_omission: "未发现新增",
    not_applied: "未应用",
    pending: "处理中",
    failed: "失败",
    budget_exhausted: "预算不足",
  };

  function feedbackKindLabel(kind) {
    return FEEDBACK_KINDS[kind] || kind || "";
  }

  function feedbackStatusLabel(status) {
    return FEEDBACK_STATUS[status] || status || "";
  }

  async function submitFeedbackBatch() {
    const fb = state.feedback;
    if (fb.submitting) return;
    if (!fb.items.length) {
      UI.toast("请先添加至少一条反馈", "error");
      return;
    }
    if (!modelConfigured()) {
      UI.toast("请先在「模型设置」中配置模型服务", "error");
      return;
    }
    fb.submitting = true;
    paintFeedback();
    try {
      const items = fb.items.map(({ label, ...rest }) => rest);
      const scan = await API.createFeedback({
        scan_id: fb.selectedId,
        items,
        base_url: state.model.base_url,
        model: state.model.model,
        api_key: state.model.api_key,
      });
      fb.items = [];
      fb.editor = null;
      fb.submitting = false;
      UI.toast("反馈已提交，模型正在复核", "success");
      location.hash = `#/scans/${scan.id}`;
    } catch (error) {
      fb.submitting = false;
      paintFeedback();
      UI.toast(error.message || "提交失败", "error");
    }
  }

  function selectedFeedbackReport() {
    const fb = state.feedback;
    return fb.reports.find((item) => item.id === fb.selectedId) || null;
  }

  function resetFeedbackCode() {
    const fb = state.feedback;
    fb.source = {};
    fb.sourceLoading = {};
    fb.previewKey = null;
    fb.codeFile = "";
    fb.codeQuery = "";
    fb.codeSelection = null;
    fb.codeAnchor = null;
    fb.codeMatches = [];
    fb.codeMatchIndex = 0;
    fb.codeDragging = false;
  }

  function resetFeedbackSelection() {
    state.feedback.selectedId = null;
    state.feedback.detail = null;
    state.feedback.items = [];
    state.feedback.editor = null;
    resetFeedbackCode();
  }

  async function renderFeedback(token) {
    const view = $("#view");
    view.innerHTML = UI.loading("正在读取可反馈报告…");
    const fb = state.feedback;
    const route = currentRoute();
    if (route.name === "feedback" && route.id && fb.selectedId !== route.id) {
      fb.selectedId = route.id;
      fb.items = [];
      fb.editor = null;
      resetFeedbackCode();
    }
    fb.reports = await API.feedbackReports();
    if (token !== routeToken) return;
    if (fb.selectedId && !fb.reports.some((item) => item.id === fb.selectedId)) {
      resetFeedbackSelection();
    }
    if (fb.selectedId) {
      fb.detail = await API.scan(fb.selectedId);
      if (token !== routeToken) return;
      const files = fb.detail.files || [];
      if (!files.some((file) => file.path === fb.codeFile)) {
        fb.codeFile = files.length ? files[0].path : "";
        fb.codeSelection = null;
        fb.codeAnchor = null;
      }
      const findings = fb.detail.findings || [];
      if (fb.previewKey && !findings.some((finding) => finding.finding_key === fb.previewKey)) {
        fb.previewKey = null;
      }
    } else {
      fb.detail = null;
      fb.editor = null;
    }
    paintFeedback();
  }

  function feedbackProseMarkup(value) {
    return String(value || "").split(/(`[^`\r\n]+`)/g).map((part) =>
      part.startsWith("`") && part.endsWith("`") && part.length > 2
        ? `<code>${UI.esc(part.slice(1, -1))}</code>`
        : UI.esc(part)
    ).join("");
  }

  function feedbackSummaryMarkup(scan) {
    const summary = scan.feedback_summary;
    const items = (summary && summary.items) || [];
    if (!items.length) return "";
    const kinds = { false_positive: "误报反馈", false_negative: "漏报反馈", location: "位置反馈", classification: "类型反馈" };
    return `<section class="card feedback-results-card">
      <div class="card-head">
        <div><h2>反馈处理结果</h2></div>
        <span class="feedback-summary-count">${items.length} 条反馈</span>
      </div>
      <div class="feedback-summary-list">
        ${items
          .map((row) => {
            const entry = row.feedback || {};
            const tone = ["replace", "withdraw", "added", "already_covered"].includes(row.status) ? "updated"
              : ["not_applied", "failed", "budget_exhausted"].includes(row.status) ? "attention" : "neutral";
            const opinion = row.review_reason || row.reason;
            return `<article class="feedback-summary-item">
              <div class="feedback-summary-top">
              <header class="feedback-summary-head">
                <h3>${UI.esc(kinds[entry.kind] || feedbackKindLabel(entry.kind) || "反馈")}</h3>
                <span class="feedback-summary-status ${tone}">${UI.esc(feedbackStatusLabel(row.status) || "未记录状态")}</span>
              </header>
              ${entry.path || entry.finding_id || (row.resulting_finding_ids || []).length ? `<div class="feedback-summary-target">${entry.path ? `<code>${UI.esc(entry.path)}</code>` : ""}${entry.finding_id ? `<span>原条目 <code>${UI.esc(entry.finding_id)}</code></span>` : ""}${(row.resulting_finding_ids || []).length ? `<span>结果条目 ${row.resulting_finding_ids.map((id) => `<code>${UI.esc(id)}</code>`).join("、")}</span>` : ""}</div>` : ""}
              </div>
              <div class="feedback-summary-grid">
                <section class="feedback-summary-user">
                  <h4>用户理由</h4>
                  <div class="feedback-summary-prose">${feedbackProseMarkup(entry.reason || "未填写理由")}</div>
                </section>
                <section class="feedback-summary-review">
                  <h4>${row.review_reason ? "复核意见" : "模型回复"}</h4>
                  <div class="feedback-summary-prose">${feedbackProseMarkup(opinion || "暂无处理意见")}</div>
                </section>
              </div>
              ${row.review_reason && row.reason ? `<details class="feedback-summary-response">
                <summary><span class="feedback-response-toggle feedback-response-show">查看完整模型回复</span><span class="feedback-response-toggle feedback-response-hide">收起完整模型回复</span></summary>
                <div class="feedback-summary-prose">${feedbackProseMarkup(row.reason)}</div>
              </details>` : ""}
            </article>`;
          })
          .join("")}
      </div>
    </section>`;
  }

  const FEEDBACK_ACTIONS = [
    {
      kind: "false_positive",
      label: "这不是漏洞",
      title: "说明为什么这不是漏洞",
      placeholder: "例如：这里的参数在上一行已经做了白名单校验，不会被注入。",
    },
    {
      kind: "location",
      label: "位置标错了",
      title: "修正这条缺陷的位置",
      placeholder: "例如：问题实际出现在第 18 行，这里只是普通的变量定义。",
    },
    {
      kind: "classification",
      label: "类型判断错了",
      title: "指出正确的缺陷类型",
      placeholder: "例如：这里执行的是系统命令，应该归为命令注入。",
    },
  ];

  function feedbackFindingRange(finding) {
    return finding.end_line && finding.end_line !== finding.start_line
      ? `${finding.start_line}-${finding.end_line}`
      : `${finding.start_line}`;
  }

  function feedbackTypeOptions(scan, placeholder) {
    const types = (languageEntry(scan.language) || { defect_types: [] }).defect_types;
    return `<option value="">${UI.esc(placeholder || "请选择")}</option>${types
      .map(
        (item) =>
          `<option value="${UI.esc(item.code)}">${UI.esc(defectOptionLabel(item))}</option>`
      )
      .join("")}`;
  }

  function feedbackEditorMarkup(finding, scan) {
    const editor = state.feedback.editor;
    const action = FEEDBACK_ACTIONS.find((item) => item.kind === editor.kind);
    return `<div class="fb-editor">
      <div class="fb-editor-head">
        <b>${UI.esc(action ? action.title : "补充说明")}</b>
        <button type="button" class="link-btn" data-fb-cancel>取消</button>
      </div>
      ${
        editor.kind === "location"
          ? `<div class="field-row">
              <label class="field"><span>正确起始行</span><input id="fb-editor-start" type="number" min="1" value="${finding.start_line || ""}" /></label>
              <label class="field"><span>正确结束行（可选）</span><input id="fb-editor-end" type="number" min="1" value="${finding.end_line || finding.start_line || ""}" /></label>
            </div>`
          : ""
      }
      ${
        editor.kind === "classification"
          ? `<label class="field"><span>你认为正确的类型</span><select id="fb-editor-type">${feedbackTypeOptions(scan, "请选择")}</select></label>`
          : ""
      }
      <label class="field"><span>理由</span>
        <textarea id="fb-editor-reason" placeholder="${UI.esc(action ? action.placeholder : "")}"></textarea>
      </label>
      <div class="form-actions">
        <button type="button" class="btn btn-primary btn-sm" data-fb-save>加入待提交</button>
        <button type="button" class="btn btn-ghost btn-sm" data-fb-cancel>取消</button>
      </div>
    </div>`;
  }

  function feedbackCodeLinesMarkup(text, options) {
    const opts = options || {};
    const lines = String(text).replace(/\r\n/g, "\n").split("\n");
    if (lines.length && lines[lines.length - 1] === "") lines.pop();
    const hits = new Map();
    (opts.findings || []).forEach((finding) => {
      const start = finding.start_line || 1;
      const end = Math.max(start, finding.end_line || start);
      for (let line = start; line <= end; line += 1) {
        if (!hits.has(line)) hits.set(line, finding);
      }
    });
    const current = opts.currentKey
      ? (opts.findings || []).find((finding) => finding.finding_key === opts.currentKey)
      : null;
    const currentStart = current ? current.start_line || 1 : 0;
    const currentEnd = current
      ? Math.max(currentStart, current.end_line || currentStart)
      : -1;
    return lines
      .map((line, index) => {
        const number = index + 1;
        const hit = hits.get(number);
        const selected =
          opts.selection && number >= opts.selection.start && number <= opts.selection.end;
        const classes = ["code-line"];
        if (opts.selectable) classes.push("fb-select-line");
        if (hit) classes.push("hit", `hit-${hit.severity || "unknown"}`);
        if (number >= currentStart && number <= currentEnd) classes.push("hit-current");
        if (selected) classes.push("selected");
        return `<div class="${classes.join(" ")}" data-line="${number}"><span class="ln">${number}</span><span class="lc">${UI.esc(line) || " "}</span></div>`;
      })
      .join("");
  }

  function feedbackSourceBlock(scan, path, options) {
    const fb = state.feedback;
    if (!path) return `<div class="fb-code-empty">没有可查看的文件。</div>`;
    const text = fb.source[path];
    if (text === undefined) return `<div class="fb-code-empty">正在读取源码…</div>`;
    if (text === null) return `<div class="fb-code-empty">无法读取该文件的源码副本。</div>`;
    const findings = (scan.findings || []).filter((finding) => finding.path === path);
    return feedbackCodeLinesMarkup(text, Object.assign({ findings }, options));
  }

  function feedbackPreviewMarkup(scan) {
    const fb = state.feedback;
    const findings = scan.findings || [];
    if (!findings.length) {
      return `<div class="fb-code-head"><span class="fb-code-title">原代码</span></div><div class="fb-code-empty">这份报告没有候选缺陷。</div>`;
    }
    const finding =
      findings.find((item) => item.finding_key === fb.previewKey) || findings[0];
    const fileFindings = findings.filter((item) => item.path === finding.path);
    const index = fileFindings.findIndex((item) => item.finding_key === finding.finding_key);
    const stepNav =
      fileFindings.length > 1
        ? `<span class="fb-code-step">
            <button type="button" class="btn btn-ghost btn-xs" data-fb-step="-1" ${index <= 0 ? "disabled" : ""}>上一处</button>
            <span class="muted small">本文件第 ${index + 1} / ${fileFindings.length} 条</span>
            <button type="button" class="btn btn-ghost btn-xs" data-fb-step="1" ${index >= fileFindings.length - 1 ? "disabled" : ""}>下一处</button>
          </span>`
        : "";
    return `<div class="fb-code-head">
      <span class="fb-code-title">原代码</span>
      <span class="mono" title="${UI.esc(finding.path)}">${UI.esc(shortPath(finding.path))}</span>
      <span class="muted small">第 ${feedbackFindingRange(finding)} 行</span>
      ${stepNav}
    </div>
    <div class="fb-code-body">${feedbackSourceBlock(scan, finding.path, { selectable: false, currentKey: finding.finding_key })}</div>`;
  }

  function feedbackCodeBodyMarkup(scan) {
    return feedbackSourceBlock(scan, state.feedback.codeFile, {
      selectable: true,
      selection: state.feedback.codeSelection,
    });
  }

  function feedbackCodeScroll(body, row) {
    if (!body || !row) return;
    body.scrollTop = Math.max(0, row.offsetTop - body.clientHeight / 2);
  }

  function feedbackPreviewScroll(host) {
    const body = host.querySelector(".fb-code-body");
    if (!body) return;
    const row =
      body.querySelector(".code-line.hit-current") || body.querySelector(".code-line.hit");
    feedbackCodeScroll(body, row);
  }

  function paintFeedbackPreview(scan) {
    const host = $("#fb-review-code");
    const wrap = $(".fb-review");
    const open = !!state.feedback.previewKey;
    if (wrap) wrap.classList.toggle("has-preview", open);
    if (!host) return;
    host.innerHTML = feedbackPreviewMarkup(scan);
    $$("[data-fb-preview]").forEach((button) => {
      const current = button.getAttribute("data-fb-preview") === state.feedback.previewKey;
      button.classList.toggle("active", current);
      button.setAttribute("aria-expanded", current ? "true" : "false");
      button.textContent = current ? "收起原代码" : "查看原代码";
    });
    if (open) feedbackPreviewScroll(host);
  }

  /** Move the preview to the previous/next finding inside the same file. */
  function stepFeedbackPreview(scan, step) {
    const fb = state.feedback;
    const findings = scan.findings || [];
    const current = findings.find((item) => item.finding_key === fb.previewKey);
    if (!current) return;
    const fileFindings = findings.filter((item) => item.path === current.path);
    const index = fileFindings.findIndex((item) => item.finding_key === current.finding_key);
    const next = fileFindings[index + step];
    if (!next) return;
    fb.previewKey = next.finding_key;
    paintFeedbackPreview(scan);
  }

  function paintFeedbackCodeArea(scan) {
    const host = $("#fb-code-body");
    if (!host) return;
    host.innerHTML = feedbackCodeBodyMarkup(scan);
    applyFeedbackSearch();
    paintFeedbackSelection();
  }

  function focusFeedbackMatch(index, scroll) {
    const fb = state.feedback;
    const total = fb.codeMatches.length;
    const counter = $("#fb-code-match-count");
    if (!total) {
      fb.codeMatchIndex = 0;
      if (counter) counter.textContent = "0/0";
      return;
    }
    fb.codeMatchIndex = ((index % total) + total) % total;
    fb.codeMatches.forEach((row) => row.classList.remove("search-current"));
    const row = fb.codeMatches[fb.codeMatchIndex];
    row.classList.add("search-current");
    if (counter) counter.textContent = `${fb.codeMatchIndex + 1}/${total}`;
    if (scroll) feedbackCodeScroll($("#fb-code-body"), row);
  }

  function applyFeedbackSearch() {
    const fb = state.feedback;
    const host = $("#fb-code-body");
    if (!host) return;
    const query = (fb.codeQuery || "").trim().toLowerCase();
    fb.codeMatches = [];
    $$(".code-line", host).forEach((row) => {
      row.classList.remove("search-hit", "search-current");
      if (!query) return;
      const text = (row.querySelector(".lc") || row).textContent.toLowerCase();
      if (text.includes(query)) {
        row.classList.add("search-hit");
        fb.codeMatches.push(row);
      }
    });
    fb.codeMatchIndex = 0;
    if (fb.codeMatches.length) {
      focusFeedbackMatch(0, true);
    } else {
      const counter = $("#fb-code-match-count");
      if (counter) counter.textContent = "0/0";
    }
  }

  function paintFeedbackSelection() {
    const fb = state.feedback;
    const host = $("#fb-code-body");
    if (host) {
      $$(".fb-select-line", host).forEach((row) => {
        const line = Number(row.getAttribute("data-line"));
        row.classList.toggle(
          "selected",
          !!fb.codeSelection && line >= fb.codeSelection.start && line <= fb.codeSelection.end
        );
      });
    }
    const startField = $("#fb-fn-start");
    const endField = $("#fb-fn-end");
    if (startField) startField.value = fb.codeSelection ? String(fb.codeSelection.start) : "";
    if (endField) endField.value = fb.codeSelection ? String(fb.codeSelection.end) : "";
    const hint = $("#fb-code-selection");
    if (hint) {
      hint.textContent = fb.codeSelection
        ? `已选择第 ${fb.codeSelection.start}${fb.codeSelection.end !== fb.codeSelection.start ? `-${fb.codeSelection.end}` : ""} 行，已自动填入下方。`
        : "点击或拖选代码行，行号自动填入下方";
    }
  }

  async function loadFeedbackSource(scan, path) {
    const fb = state.feedback;
    if (!path || fb.source[path] !== undefined || fb.sourceLoading[path]) return;
    fb.sourceLoading[path] = true;
    try {
      fb.source[path] = await API.source(scan.id, path);
    } catch (error) {
      fb.source[path] = null;
    }
    fb.sourceLoading[path] = false;
  }

  async function preloadFeedbackSources(scan) {
    const fb = state.feedback;
    const findings = scan.findings || [];
    const preview =
      findings.find((finding) => finding.finding_key === fb.previewKey) || findings[0];
    const paths = [];
    if (preview) paths.push(preview.path);
    if (fb.codeFile && !paths.includes(fb.codeFile)) paths.push(fb.codeFile);
    for (const path of paths) {
      if (fb.source[path] !== undefined) continue;
      await loadFeedbackSource(scan, path);
      if (state.feedback.selectedId !== scan.id) return;
      if (fb.codeFile === path) paintFeedbackCodeArea(scan);
      if (preview && preview.path === path) paintFeedbackPreview(scan);
    }
  }

  function feedbackFindingMarkup(finding, scan) {
    const fb = state.feedback;
    const key = finding.finding_key;
    const editing = fb.editor && fb.editor.findingKey === key;
    const previewing = fb.previewKey === key;
    const marked = fb.items.filter((item) => item.finding_id === key);
    return `<article class="fb-finding${editing ? " editing" : ""}">
      <div class="fb-finding-head">
        ${UI.severityBadge(finding.severity)}
        <span class="defect-code">${UI.esc(finding.defect_type)}</span>
        <span class="finding-title">${UI.esc(finding.title)}</span>
        <span class="fb-finding-line" title="${UI.esc(finding.path)}">${UI.esc(shortPath(finding.path))}:${feedbackFindingRange(finding)}</span>
      </div>
      <p class="fb-finding-desc">${UI.esc(finding.description)}</p>
      ${
        marked.length
          ? `<div class="fb-marked">${marked
              .map(
                (item) =>
                  `<span class="pill">已标记：${UI.esc(feedbackKindLabel(item.kind))}</span>`
              )
              .join("")}</div>`
          : ""
      }
      <div class="fb-finding-actions">
        ${FEEDBACK_ACTIONS.map(
          (action) =>
            `<button type="button" class="btn btn-ghost btn-xs" data-fb-action="${action.kind}" data-fb-key="${UI.esc(key)}">${UI.esc(action.label)}</button>`
        ).join("")}
        <button type="button" class="btn btn-ghost btn-xs fb-preview-btn${previewing ? " active" : ""}" data-fb-preview="${UI.esc(key)}">${previewing ? "收起原代码" : "查看原代码"}</button>
      </div>
      ${editing ? feedbackEditorMarkup(finding, scan) : ""}
    </article>`;
  }

  function feedbackFalseNegativeMarkup(scan) {
    const files = scan.files || [];
    const fb = state.feedback;
    const selection = fb.codeSelection;
    return `<section class="card">
      <div class="step-head fb-step">
        <span class="step">3</span>
        <div><h2>补充漏报</h2></div>
      </div>
      <div class="fb-code-browser">
        <div class="fb-code-toolbar">
          <label class="field fb-code-file"><span>文件</span>
            <select id="fb-fn-file">
              ${files
                .map(
                  (file) =>
                    `<option value="${UI.esc(file.path)}" ${file.path === fb.codeFile ? "selected" : ""}>${UI.esc(file.path)}</option>`
                )
                .join("")}
            </select>
          </label>
          <div class="fb-code-search">
            <input id="fb-code-search" type="search" autocomplete="off" spellcheck="false" placeholder="搜索代码" value="${UI.esc(fb.codeQuery)}" />
            <span class="fb-code-match" id="fb-code-match-count">0/0</span>
            <button type="button" class="btn btn-ghost btn-xs" data-fb-search-prev>上一个</button>
            <button type="button" class="btn btn-ghost btn-xs" data-fb-search-next>下一个</button>
          </div>
        </div>
        <div class="fb-code-hint" id="fb-code-selection">点击或拖选代码行，行号自动填入下方</div>
        <div class="fb-code-body" id="fb-code-body">${feedbackCodeBodyMarkup(scan)}</div>
      </div>
      <div class="fb-form fb-fn-form">
        <label class="field"><span>理由</span>
          <textarea id="fb-fn-reason" placeholder="位置、触发条件、影响"></textarea>
        </label>
        <div class="field-row">
          <label class="field"><span>起始行</span><input id="fb-fn-start" type="number" min="1" placeholder="点击代码或拖选" value="${selection ? selection.start : ""}" /></label>
          <label class="field"><span>结束行</span><input id="fb-fn-end" type="number" min="1" placeholder="自动填入" value="${selection ? selection.end : ""}" /></label>
        </div>
        <label class="field"><span>缺陷类型（可选）</span>
          <select id="fb-fn-type">${feedbackTypeOptions(scan, "不确定")}</select>
        </label>
        <div class="form-actions">
          <button type="button" class="btn btn-ghost" data-fb-fn-add>加入待提交</button>
        </div>
      </div>
    </section>`;
  }

  function feedbackBasketMarkup() {
    const fb = state.feedback;
    return `<section class="card fb-basket">
      <div class="step-head fb-step">
        <span class="step">4</span>
        <div><h2>确认并提交</h2></div>
      </div>
      ${
        fb.items.length
          ? `<div class="feedback-batch">${fb.items
              .map(
                (item, index) => `<div class="feedback-batch-item">
                  <div><b>${UI.esc(feedbackKindLabel(item.kind))}</b><span class="mono">${UI.esc(item.label || item.path || "")}</span></div>
                  <p>${UI.esc(item.reason)}</p>
                  ${
                    item.defect_type
                      ? `<p class="muted small">建议类型：${UI.esc(item.defect_type)}</p>`
                      : ""
                  }
                  ${
                    item.start_line
                      ? `<p class="muted small">建议行号：${UI.esc(item.start_line)}${item.end_line && item.end_line !== item.start_line ? `-${UI.esc(item.end_line)}` : ""}</p>`
                      : ""
                  }
                  <button type="button" class="icon-btn danger" data-remove-feedback="${index}" title="移除">${UI.icon("trash", 15)}</button>
                </div>`
              )
              .join("")}</div>`
          : `<p class="muted padded">暂无待提交反馈</p>`
      }
      <div class="form-actions">
        <button type="button" class="btn btn-primary btn-block" id="feedback-submit" ${fb.items.length && !fb.submitting ? "" : "disabled"}>${fb.submitting ? "正在提交…" : `提交${fb.items.length ? ` ${fb.items.length} 条` : ""}反馈`}</button>
      </div>
      ${
        modelConfigured()
          ? ""
          : `<p class="field-hint">提交前需在「模型设置」中配置模型服务</p>`
      }
    </section>`;
  }

  function feedbackReportMarkup(scan) {
    const findings = scan.findings || [];
    const files = scan.files || [];
    return `<section class="card">
        <div class="card-head">
          <div>
            <h2>${UI.esc(scan.source_name)}</h2>
            <p>${UI.esc(languageName(scan.language))} · 模型 ${UI.esc(scan.model_name || "未记录")} · ${findings.length} 条候选缺陷 · 检测于 ${UI.timeAgo(scan.created_at)}</p>
          </div>
          <a class="text-link" href="#/scans/${scan.id}">查看完整报告</a>
        </div>
        <p class="muted small">复核后生成新报告，原报告保留。</p>
      </section>

      ${scan.feedback_summary ? feedbackSummaryMarkup(scan) : ""}

      <div class="scan-layout">
        <div class="scan-main">
          <section class="card">
            <div class="step-head fb-step">
              <span class="step">2</span>
              <div><h2>核对候选缺陷</h2></div>
            </div>
            ${
              findings.length
                ? `<div class="fb-review${state.feedback.previewKey ? " has-preview" : ""}">
                    <div class="fb-review-list">
                      <div class="fb-findings">${findings
                        .map((finding) => feedbackFindingMarkup(finding, scan))
                        .join("")}</div>
                    </div>
                    <div class="fb-review-code" id="fb-review-code">${feedbackPreviewMarkup(scan)}</div>
                  </div>`
                : `<p class="muted padded">这份报告没有候选缺陷，漏报可在下方补充。</p>`
            }
          </section>
          ${files.length ? feedbackFalseNegativeMarkup(scan) : ""}
        </div>
        <aside class="scan-side">${feedbackBasketMarkup()}</aside>
      </div>`;
  }

  function paintFeedback() {
    const view = $("#view");
    const fb = state.feedback;
    const selected = selectedFeedbackReport();
    const rows = fb.reports.length
      ? fb.reports
          .map(
            (report) => `<tr class="clickable ${report.id === fb.selectedId ? "active" : ""}" tabindex="0" role="button" data-feedback-id="${report.id}">
              <td>
                <div class="cell-title"><span>${UI.esc(report.source_name)}</span></div>
                <span class="cell-sub">${UI.esc(languageName(report.language))} · ${report.finding_count} 条候选缺陷 · ${UI.timeAgo(report.created_at)}</span>
              </td>
              <td>${UI.statusChip(report.status)}</td>
              <td class="muted">${report.id === fb.selectedId ? "当前报告" : "选择"}</td>
            </tr>`
          )
          .join("")
      : "";
    view.innerHTML =
      pageHead(
        "用户反馈",
        "",
        `<button class="btn btn-ghost" id="refresh-feedback">${UI.icon("refresh", 15)}刷新</button>`
      ) +
      `<section class="card">
        <div class="step-head fb-step">
          <span class="step">1</span>
          <div><h2>选择检测报告</h2></div>
        </div>
        ${
          rows
            ? `<div class="table-wrap"><table class="table">
                <thead><tr><th>报告</th><th>状态</th><th></th></tr></thead>
                <tbody>${rows}</tbody>
              </table></div>`
            : UI.emptyState(
                "还没有可反馈的报告",
                "完成源码检测后可反馈；Agent Skill 报告暂不支持。",
                `<a class="btn btn-primary" href="#/new">新建检测</a>`
              )
        }
      </section>` +
      (selected && fb.detail
        ? feedbackReportMarkup(fb.detail)
        : fb.reports.length
        ? `<section class="card"><p class="muted padded">选择一份报告后开始反馈</p></section>`
        : "");
    bindFeedback();
  }

  function bindFeedback() {
    const token = routeToken;
    const detail = state.feedback.detail;
    $("#refresh-feedback").addEventListener("click", () => renderFeedback(token));
    const selectReport = (id) => {
      state.feedback.selectedId = id;
      state.feedback.items = [];
      state.feedback.editor = null;
      resetFeedbackCode();
      history.replaceState(null, "", `#/feedback/${id}`);
      renderFeedback(token);
    };
    $$("[data-feedback-id]").forEach((row) => {
      const id = row.getAttribute("data-feedback-id");
      row.addEventListener("click", () => selectReport(id));
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectReport(id);
        }
      });
    });

    $$("[data-fb-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-fb-key");
        const kind = button.getAttribute("data-fb-action");
        const fb = state.feedback;
        if (fb.items.some((item) => item.finding_id === key && item.kind === kind)) {
          UI.toast("这条结果已经添加过同类反馈", "info");
          return;
        }
        fb.editor = { findingKey: key, kind };
        paintFeedback();
      });
    });

    $$("[data-fb-preview]").forEach((button) => {
      button.addEventListener("click", async () => {
        const fb = state.feedback;
        if (!detail) return;
        const key = button.getAttribute("data-fb-preview");
        fb.previewKey = fb.previewKey === key ? null : key;
        paintFeedbackPreview(detail);
        if (!fb.previewKey) return;
        const finding = (detail.findings || []).find((item) => item.finding_key === key);
        if (finding && fb.source[finding.path] === undefined) {
          await loadFeedbackSource(detail, finding.path);
          if (state.feedback.selectedId === detail.id) paintFeedbackPreview(detail);
        }
      });
    });

    const previewHost = $("#fb-review-code");
    if (previewHost) {
      previewHost.addEventListener("click", (event) => {
        const button = event.target.closest("[data-fb-step]");
        if (!button || !detail) return;
        stepFeedbackPreview(detail, Number(button.getAttribute("data-fb-step")));
      });
    }

    const codeFile = $("#fb-fn-file");
    if (codeFile) {
      codeFile.addEventListener("change", async () => {
        const fb = state.feedback;
        if (!detail) return;
        fb.codeFile = codeFile.value;
        fb.codeSelection = null;
        fb.codeAnchor = null;
        fb.codeMatchIndex = 0;
        paintFeedbackCodeArea(detail);
        if (fb.source[fb.codeFile] === undefined) {
          await loadFeedbackSource(detail, fb.codeFile);
          if (state.feedback.selectedId === detail.id) paintFeedbackCodeArea(detail);
        }
      });
    }

    const search = $("#fb-code-search");
    if (search) {
      search.addEventListener("input", () => {
        state.feedback.codeQuery = search.value;
        state.feedback.codeMatchIndex = 0;
        applyFeedbackSearch();
      });
      search.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        focusFeedbackMatch(state.feedback.codeMatchIndex + 1, true);
      });
    }
    $$("[data-fb-search-prev]").forEach((button) => {
      button.addEventListener("click", () =>
        focusFeedbackMatch(state.feedback.codeMatchIndex - 1, true)
      );
    });
    $$("[data-fb-search-next]").forEach((button) => {
      button.addEventListener("click", () =>
        focusFeedbackMatch(state.feedback.codeMatchIndex + 1, true)
      );
    });

    const codeBody = $("#fb-code-body");
    if (codeBody) {
      codeBody.addEventListener("mousedown", (event) => {
        const row = event.target.closest(".fb-select-line");
        if (!row) return;
        event.preventDefault();
        const fb = state.feedback;
        const line = Number(row.getAttribute("data-line"));
        if (event.shiftKey && fb.codeAnchor) {
          fb.codeSelection = {
            start: Math.min(fb.codeAnchor, line),
            end: Math.max(fb.codeAnchor, line),
          };
        } else {
          fb.codeAnchor = line;
          fb.codeSelection = { start: line, end: line };
        }
        fb.codeDragging = true;
        paintFeedbackSelection();
        window.addEventListener(
          "mouseup",
          () => {
            fb.codeDragging = false;
          },
          { once: true }
        );
      });
      codeBody.addEventListener("mouseover", (event) => {
        const fb = state.feedback;
        if (!fb.codeDragging) return;
        const row = event.target.closest(".fb-select-line");
        if (!row) return;
        const line = Number(row.getAttribute("data-line"));
        fb.codeSelection = {
          start: Math.min(fb.codeAnchor, line),
          end: Math.max(fb.codeAnchor, line),
        };
        paintFeedbackSelection();
      });
    }

    $$("[data-fb-cancel]").forEach((button) => {
      button.addEventListener("click", () => {
        state.feedback.editor = null;
        paintFeedback();
      });
    });

    const saveFinding = () => {
      const fb = state.feedback;
      if (!fb.editor || !fb.detail) return;
      const finding = (fb.detail.findings || []).find(
        (item) => item.finding_key === fb.editor.findingKey
      );
      if (!finding) {
        fb.editor = null;
        paintFeedback();
        return;
      }
      const reasonField = $("#fb-editor-reason");
      const text = (reasonField ? reasonField.value : "").trim();
      if (!text) {
        UI.toast("请填写反馈理由", "error");
        if (reasonField) reasonField.focus();
        return;
      }
      const item = {
        kind: fb.editor.kind,
        reason: text,
        finding_id: finding.finding_key,
        label: `${finding.defect_type} / ${finding.title}`,
      };
      if (fb.editor.kind === "classification") {
        const typeField = $("#fb-editor-type");
        const type = typeField ? typeField.value : "";
        if (!type) {
          UI.toast("请选择你认为正确的缺陷类型", "error");
          return;
        }
        item.defect_type = type;
      }
      if (fb.editor.kind === "location") {
        const startField = $("#fb-editor-start");
        const endField = $("#fb-editor-end");
        const start = Number(startField ? startField.value : 0) || 0;
        const end = Number(endField ? endField.value : 0) || 0;
        if (start && end && end < start) {
          UI.toast("结束行不能小于起始行", "error");
          return;
        }
        if (start) item.start_line = start;
        if (end) item.end_line = end;
      }
      fb.items.push(item);
      fb.editor = null;
      UI.toast("已加入待提交", "success");
      paintFeedback();
    };
    $$("[data-fb-save]").forEach((button) =>
      button.addEventListener("click", saveFinding)
    );

    const addFalseNegative = () => {
      const fb = state.feedback;
      const fileField = $("#fb-fn-file");
      const reasonField = $("#fb-fn-reason");
      const file = fileField ? fileField.value : "";
      const text = (reasonField ? reasonField.value : "").trim();
      if (!file) {
        UI.toast("请选择文件", "error");
        return;
      }
      if (!text) {
        UI.toast("请填写漏报理由", "error");
        if (reasonField) reasonField.focus();
        return;
      }
      const startField = $("#fb-fn-start");
      const endField = $("#fb-fn-end");
      const start = Number(startField ? startField.value : 0) || 0;
      const end = Number(endField ? endField.value : 0) || 0;
      if (start && end && end < start) {
        UI.toast("结束行不能小于起始行", "error");
        return;
      }
      const typeField = $("#fb-fn-type");
      const item = {
        kind: "false_negative",
        reason: text,
        path: file,
        label: `漏报 / ${shortPath(file)}`,
      };
      if (typeField && typeField.value) item.defect_type = typeField.value;
      if (start) item.start_line = start;
      if (end) item.end_line = end;
      fb.items.push(item);
      UI.toast("已加入待提交", "success");
      paintFeedback();
    };
    const falseNegativeButton = $("[data-fb-fn-add]");
    if (falseNegativeButton) {
      falseNegativeButton.addEventListener("click", addFalseNegative);
    }

    const editor = $(".fb-editor");
    if (editor) {
      const reasonField = $("#fb-editor-reason");
      if (reasonField) reasonField.focus({ preventScroll: true });
      editor.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    $$("[data-remove-feedback]").forEach((button) => {
      button.addEventListener("click", () => {
        state.feedback.items.splice(Number(button.getAttribute("data-remove-feedback")), 1);
        paintFeedback();
      });
    });

    const submit = $("#feedback-submit");
    if (submit) submit.addEventListener("click", () => submitFeedbackBatch());

    if (detail) {
      applyFeedbackSearch();
      paintFeedbackSelection();
      const previewHost = $("#fb-review-code");
      if (previewHost) feedbackPreviewScroll(previewHost);
      preloadFeedbackSources(detail);
    }
  }

  /* ----------------------------------------------------------- scan detail */

  async function renderScanDetail(id, token) {
    if (token !== undefined && token !== routeToken) return;
    const view = $("#view");
    view.innerHTML = `<div class="detail-loading">${UI.loading("正在读取检测结果…")}</div>`;
    const scan = await API.scan(id);
    if (token !== routeToken) return;
    if (state.detailId !== id) {
      state.detailId = id;
      state.detailFilters = { severity: "", type: "" };
    }
    state.currentScan = scan;
    paintScanDetail(scan, token);
    if (scan.status === "queued" || scan.status === "running") startPoll(id, token);
  }

  function findingEvidence(finding) {
    const evidence = Array.isArray(finding.evidence) ? finding.evidence : [];
    const code = evidence.find((item) => item.kind === "code_excerpt");
    const trace = evidence.find((item) => item.kind === "analysis_trace");
    return { code, trace };
  }

  /* ------------------------------------------------------------ workbench */

  const WB_ALL = "";

  function wbFindings(scan, file) {
    const filters = state.detailFilters;
    return (scan.findings || []).filter((finding) => {
      if (filters.severity && finding.severity !== filters.severity) return false;
      if (filters.type && finding.defect_type !== filters.type) return false;
      if (file && finding.path !== file) return false;
      return true;
    });
  }

  function wbFileCounts(scan) {
    const counts = new Map();
    (scan.findings || []).forEach((finding) => {
      counts.set(finding.path, (counts.get(finding.path) || 0) + 1);
    });
    return counts;
  }

  function wbFileList(scan) {
    const paths = (scan.files || []).map((file) => file.path);
    const known = new Set(paths);
    (scan.findings || []).forEach((finding) => {
      if (finding.path && !known.has(finding.path)) {
        known.add(finding.path);
        paths.push(finding.path);
      }
    });
    return paths;
  }

  function wbDefaultFile(scan) {
    const counts = wbFileCounts(scan);
    const withHits = wbFileList(scan).find((path) => counts.get(path));
    return withHits || WB_ALL;
  }

  function wbFileRow(path, label, count) {
    const active = state.workbench.file === path ? " active" : "";
    return `<button type="button" class="wb-file${active}" data-wb-file="${UI.esc(path)}">
      <span>${UI.esc(label)}</span>${count ? `<b>${count}</b>` : ""}
    </button>`;
  }

  function wbCodeMarkup(scan) {
    const wb = state.workbench;
    if (!wb.file) return `<div class="wb-empty">选择左侧文件查看源码</div>`;
    const text = wb.source[wb.file];
    if (text === undefined) return `<div class="wb-empty">正在读取源码…</div>`;
    if (text === null) return `<div class="wb-empty">无法读取该文件的源码副本</div>`;
    const lines = String(text).replace(/\r\n/g, "\n").split("\n");
    if (lines.length && lines[lines.length - 1] === "") lines.pop();
    const hits = new Map();
    wbFindings(scan, wb.file).forEach((finding) => {
      const start = finding.start_line || 1;
      const end = Math.max(start, finding.end_line || start);
      for (let line = start; line <= end; line += 1) {
        if (!hits.has(line)) hits.set(line, finding);
      }
    });
    return lines
      .map((line, index) => {
        const number = index + 1;
        const hit = hits.get(number);
        const cls = hit ? ` hit hit-${hit.severity || "unknown"}` : "";
        return `<div class="code-line${cls}" data-line="${number}"><span class="ln">${number}</span><span class="lc">${UI.esc(line) || " "}</span></div>`;
      })
      .join("");
  }

  function wbHitMarkup(finding) {
    const active = finding.id === state.workbench.selectedId;
    const range =
      finding.end_line && finding.end_line !== finding.start_line
        ? `${finding.start_line}-${finding.end_line}`
        : `${finding.start_line}`;
    const evidence = findingEvidence(finding);
    const typeName = /^CWE-\d+$/.test(finding.defect_type) ? finding.defect_type : defectLabel(finding.defect_type);
    return `<article class="wb-hit${active ? " active" : ""}" data-finding="${finding.id}">
      <button type="button" class="wb-hit-select" data-wb-select="${finding.id}" aria-expanded="${active}">
      <span class="wb-hit-head">
        ${UI.severityBadge(finding.severity)}
        <code${typeName !== finding.defect_type ? ' class="wb-hit-type-name"' : ""} title="${UI.esc(finding.defect_type)}">${UI.esc(typeName)}</code>
        <span class="wb-hit-line">第 ${range} 行</span>
      </span>
      <span class="wb-hit-title">${UI.esc(finding.title)}</span>
      <span class="wb-hit-path" title="${UI.esc(finding.path)}">${UI.esc(finding.path)}</span>
      </button>
      ${
        active
          ? `<div class="wb-hit-body">
              <h3 class="wb-hit-label">问题说明</h3>
              <p class="pre-line">${UI.esc(finding.description)}</p>
              <button type="button" class="wb-locate" data-wb-location="${finding.id}">${UI.icon("code", 14)}定位源码 · 第 ${range} 行</button>
              ${evidence.code ? `<details class="wb-evidence"><summary>代码证据<span aria-hidden="true"></span></summary><pre class="code-view" tabindex="0" aria-label="代码证据">${UI.esc(evidence.code.summary || "")}</pre></details>` : ""}
              ${evidence.trace ? `<details class="wb-evidence"><summary>分析过程<span aria-hidden="true"></span></summary><p class="pre-line">${UI.esc(evidence.trace.summary || "")}</p></details>` : ""}
            </div>`
          : ""
      }
    </article>`;
  }

  function wbHitsMarkup(scan) {
    if (!(scan.findings || []).length) {
      return `<div class="wb-empty">${scan.status === "succeeded" ? "未发现候选缺陷" : "暂无候选缺陷"}</div>`;
    }
    const list = wbFindings(scan, state.workbench.file);
    if (!list.length) {
      const filtered = state.detailFilters.severity || state.detailFilters.type;
      return `<div class="wb-empty">${
        filtered ? "当前筛选条件下没有结果" : "该文件没有候选缺陷，可在左侧选择带数字的文件"
      }</div>`;
    }
    return list.map(wbHitMarkup).join("");
  }

  function wbPaint(scan) {
    const wb = state.workbench;
    const filesHost = $("#wb-files");
    const codeHost = $("#wb-code");
    const hitsHost = $("#wb-hits");
    if (!filesHost || !codeHost || !hitsHost) return;

    const counts = wbFileCounts(scan);
    const paths = wbFileList(scan);
    const total = (scan.findings || []).length;
    filesHost.innerHTML =
      `<div class="wb-col-head"><span>文件 ${paths.length}</span></div>` +
      wbFileRow(WB_ALL, "全部文件", total) +
      paths.map((path) => wbFileRow(path, path, counts.get(path) || 0)).join("");

    const file = (scan.files || []).find((item) => item.path === wb.file);
    $("#wb-code-head").innerHTML = wb.file
      ? `<span class="mono" title="${UI.esc(wb.file)}">${UI.esc(wb.file)}</span>
         <span>${file ? `${file.line_count} 行 · ${UI.formatBytes(file.size_bytes)}` : ""}</span>`
      : `<span>全部文件</span><span>点击右侧条目跳转到源码</span>`;

    codeHost.innerHTML = wbCodeMarkup(scan);
    $("#wb-count").textContent = String(wbFindings(scan, wb.file).length);
    hitsHost.innerHTML = wbHitsMarkup(scan);
  }

  function wbScrollTo(finding) {
    const codeHost = $("#wb-code");
    const line = codeHost && codeHost.querySelector(`.code-line[data-line="${finding.start_line || 1}"]`);
    if (line) {
      line.scrollIntoView({ block: "center", behavior: "smooth" });
      line.classList.add("active");
      setTimeout(() => line.classList.remove("active"), 1600);
    }
    const hit = $(`[data-finding="${finding.id}"]`);
    if (hit) hit.scrollIntoView({ block: "nearest" });
  }

  async function wbInit(scan) {
    const wb = state.workbench;
    if (wb.scanId !== scan.id) {
      wb.scanId = scan.id;
      wb.file = wbDefaultFile(scan);
      wb.source = {};
      wb.selectedId = null;
      wb.shown = (scan.findings || []).length;
    }
    wbPaint(scan);
    if (wb.file && wb.source[wb.file] === undefined) {
      try {
        wb.source[wb.file] = await API.source(scan.id, wb.file);
      } catch (error) {
        wb.source[wb.file] = null;
      }
      if (state.workbench.scanId === scan.id && state.workbench.file === wb.file) wbPaint(scan);
    }
  }

  async function wbOpenFile(scan, path) {
    const wb = state.workbench;
    wb.file = path;
    wb.selectedId = null;
    wbPaint(scan);
    if (!path || wb.source[path] !== undefined) return;
    try {
      wb.source[path] = await API.source(scan.id, path);
    } catch (error) {
      wb.source[path] = null;
    }
    if (state.workbench.scanId === scan.id && state.workbench.file === path) wbPaint(scan);
  }

  async function wbSelectFinding(scan, id) {
    const wb = state.workbench;
    const finding = (scan.findings || []).find((item) => item.id === id);
    if (!finding) return;
    if (wb.selectedId === id && wb.file === finding.path && wb.source[wb.file] !== undefined) {
      wbScrollTo(finding);
      return;
    }
    wb.selectedId = id;
    if (wb.file !== finding.path) wb.file = finding.path;
    if (wb.file && wb.source[wb.file] === undefined) {
      wbPaint(scan);
      try {
        wb.source[wb.file] = await API.source(scan.id, wb.file);
      } catch (error) {
        wb.source[wb.file] = null;
      }
      if (state.workbench.scanId !== scan.id) return;
    }
    wbPaint(scan);
    wbScrollTo(finding);
  }

  function eventsMarkup(events) {
    const list = (events || []).slice(-8);
    if (!list.length) return `<p class="muted small">暂无进度事件。</p>`;
    return `<ol class="timeline">${list
      .map(
        (event) => `<li class="${event.level === "error" ? "error" : event.level === "warn" ? "warn" : ""}">
          <span class="timeline-time">${UI.formatDateTime(event.created_at)}</span>
          <span>${UI.esc(event.message)}</span>
        </li>`
      )
      .join("")}</ol>`;
  }

  function scanSeverityCounts(scan) {
    const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    (scan.findings || []).forEach((finding) => {
      const key = String(finding.severity || "info");
      if (counts[key] !== undefined) counts[key] += 1;
    });
    return counts;
  }

  function scanResultVisualMarkup(scan) {
    const counts = scanSeverityCounts(scan);
    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
    let gate;
    if (scan.status === "queued" || scan.status === "running") {
      gate = { label: "检测中", cls: "muted" };
    } else if (!["succeeded", "partial"].includes(scan.status)) {
      gate = { label: "无结论", cls: "muted" };
    } else if (scan.status === "partial") {
      gate = { label: "未审查完", cls: "warn" };
    } else if (counts.critical + counts.high > 0) {
      gate = { label: "发现高危", cls: "bad" };
    } else if (counts.medium > 0) {
      gate = { label: "建议检查", cls: "warn" };
    } else {
      gate = { label: "未发现问题", cls: "ok" };
    }
    const filesWithFindings = new Set((scan.findings || []).map((finding) => finding.path)).size;
    const finished = ["succeeded", "partial"].includes(scan.status);
    const headline = finished
      ? total
        ? `发现 ${UI.formatNumber(total)} 条候选缺陷`
        : "未发现候选缺陷"
      : gate.label;
    return `<section class="card result-summary">
      <div class="result-summary-main">
        <span class="result-verdict gate-${gate.cls}">${gate.label}</span>
        <h2>${headline}</h2>
        <p class="result-meta">
          <span>已审查 ${UI.formatNumber(scan.completed_files)} / ${UI.formatNumber(scan.total_files || 0)} 个文件</span>
          <span>${UI.formatNumber(filesWithFindings)} 个文件含候选缺陷</span>
          <span>${UI.formatNumber(scan.model_calls)} 次模型调用</span>
          <span>${UI.formatNumber(scan.total_tokens || 0)} tokens</span>
          <span>耗时 ${UI.formatDuration(scan.duration_seconds)}</span>
        </p>
      </div>
      <div class="result-severities">
        ${Object.keys(counts)
          .map(
            (key) => `<div class="result-sev result-sev-${key}${counts[key] ? "" : " zero"}">
              <b>${UI.formatNumber(counts[key])}</b><span>${UI.SEVERITY[key].label}</span>
            </div>`
          )
          .join("")}
      </div>
    </section>`;
  }

  function paintScanDetail(scan, token) {
    const view = $("#view");
    const active = scan.status === "queued" || scan.status === "running";
    const progress =
      scan.total_files > 0
        ? Math.min(100, Math.round((scan.completed_files / scan.total_files) * 100))
        : 0;
    const language = languageName(scan.language);
    const defectOptions = (state.catalog.languages.find((item) => item.code === scan.language) || { defect_types: [] }).defect_types;
    view.innerHTML = `
      <div class="page-head detail-head">
        <div>
          <a class="back-link" href="#/scans">${UI.icon("back", 15)}返回检测历史</a>
          <div class="detail-title-row">
            <h1>${UI.esc(scan.source_name)}</h1>
            <span class="status-slot" data-scan-status>${UI.statusChip(scan.status)}</span>
          </div>
          <p>${UI.esc(language)} / ${UI.esc(scan.model_name || "未记录模型")}${scan.source_kind === "feedback" ? " / 用户反馈复核" : ""}${scan.repo_url ? ` / <a class="text-link" href="${UI.esc(scan.repo_url)}" target="_blank" rel="noreferrer">在 GitHub 查看</a>` : ""} / ${UI.formatDateTime(scan.created_at)}</p>
        </div>
        <div class="page-actions">
          ${scan.parent_scan_id ? `<a class="btn btn-ghost" href="#/scans/${scan.parent_scan_id}">原始报告</a>` : ""}
          ${["succeeded", "partial"].includes(scan.status) && scan.language !== "agent_skill" ? `<a class="btn btn-ghost" href="#/feedback/${scan.id}">用户反馈</a>` : ""}
          ${active ? `<button type="button" class="btn btn-ghost" id="cancel-scan">取消任务</button>` : ""}
          ${scan.has_report ? `<button type="button" class="btn btn-ghost" id="download-report">${UI.icon("download", 15)}导出 JSON</button>` : ""}
          ${!active ? `<button type="button" class="btn btn-ghost danger-text" id="delete-scan">${UI.icon("trash", 15)}删除</button>` : ""}
          <a class="btn btn-primary" href="#/new">${UI.icon("plus", 16)}新建检测</a>
        </div>
      </div>

      ${
        active
          ? `<section class="card progress-card">
              <div class="progress-head">
                <div>
                  <h2>${scan.status === "queued" ? "等待调度" : "检测进行中"}</h2>
                  <p data-status-detail>${UI.esc(scan.status_detail || "正在准备")}</p>
                </div>
                <span class="progress-count" data-progress-count>${scan.completed_files}/${scan.total_files || "—"}</span>
              </div>
              <div class="progress ${scan.total_files ? "" : "indeterminate"}"><i data-progress-bar style="width:${progress}%"></i></div>
              <div class="timeline-wrap" data-timeline>${eventsMarkup(scan.events)}</div>
            </section>`
          : ""
      }

      ${
        ["failed", "partial", "cancelled"].includes(scan.status)
          ? `<div class="banner banner-${scan.status === "failed" ? "error" : "warn"}">
              ${UI.icon("alert", 18)}
              <div><b>${UI.esc(scan.status_detail || UI.STATUS[scan.status].label)}</b><p>${UI.esc(scan.error_message || (scan.errors && scan.errors[0] && scan.errors[0].message) || "详见下方执行错误与检测范围")}</p>
                ${scan.retry_file_count > 0 ? `<button type="button" class="btn btn-ghost btn-sm" id="retry-scan">重试失败文件（${UI.formatNumber(scan.retry_file_count)}）</button>` : ""}
              </div>
            </div>`
          : ""
      }

      ${scanResultVisualMarkup(scan)}

      ${scan.feedback_summary ? feedbackSummaryMarkup(scan) : ""}

      <section class="workbench" id="workbench">
        <div class="wb-col wb-files" id="wb-files"></div>
        <div class="wb-col wb-center">
          <div class="wb-col-head" id="wb-code-head"></div>
          <div class="wb-code" id="wb-code"></div>
        </div>
        <div class="wb-col wb-hits">
          <div class="wb-col-head">
            <span>候选缺陷 <b id="wb-count">${scan.finding_count}</b></span>
            <div class="wb-filter">
              <select data-filter-severity>
                <option value="">全部等级</option>
                ${Object.keys(UI.SEVERITY)
                  .map((key) => `<option value="${key}" ${state.detailFilters.severity === key ? "selected" : ""}>${UI.SEVERITY[key].label}</option>`)
                  .join("")}
              </select>
              <select data-filter-type>
                <option value="">全部类型</option>
                ${defectOptions
                  .map((item) => `<option value="${UI.esc(item.code)}" ${state.detailFilters.type === item.code ? "selected" : ""}>${UI.esc(defectOptionLabel(item))}</option>`)
                  .join("")}
              </select>
            </div>
          </div>
          <div class="wb-hit-list" id="wb-hits"></div>
        </div>
      </section>

      <div class="detail-grid detail-grid-stack">
        ${coverageMarkup(scan)}
        <section class="card execution-errors">
          <div class="card-head"><div><h2>执行错误</h2></div></div>
          ${
            (scan.errors || []).length
              ? `<ul class="error-list">${scan.errors
                  .map((item) => `<li><span class="execution-error-label" title="${UI.esc(item.code)}">${UI.esc(errorLabel(item.code))}</span><span class="execution-error-message">${UI.esc(item.message)}</span></li>`)
                  .join("")}</ul>`
              : `<p class="muted small">无</p>`
          }
        </section>
      </div>`;

    const severitySelect = $("[data-filter-severity]");
    const typeSelect = $("[data-filter-type]");
    if (severitySelect) {
      severitySelect.addEventListener("change", () => {
        state.detailFilters.severity = severitySelect.value;
        wbPaint(scan);
      });
    }
    if (typeSelect) {
      typeSelect.addEventListener("change", () => {
        state.detailFilters.type = typeSelect.value;
        wbPaint(scan);
      });
    }

    const bench = $("#workbench");
    if (bench) {
      bench.addEventListener("click", (event) => {
        const fileButton = event.target.closest("[data-wb-file]");
        if (fileButton) {
          wbOpenFile(scan, fileButton.getAttribute("data-wb-file"));
          return;
        }
        const hit = event.target.closest("[data-wb-select], [data-wb-location]");
        if (hit) {
          wbSelectFinding(scan, Number(hit.getAttribute("data-wb-select") || hit.getAttribute("data-wb-location")));
          return;
        }
        const line = event.target.closest(".code-line.hit");
        if (line) {
          const number = Number(line.getAttribute("data-line"));
          const target = wbFindings(scan, state.workbench.file).find((finding) => {
            const start = finding.start_line || 1;
            const end = Math.max(start, finding.end_line || start);
            return number >= start && number <= end;
          });
          if (target) wbSelectFinding(scan, target.id);
        }
      });
      wbInit(scan);
    }

    const cancel = $("#cancel-scan");
    if (cancel) {
      cancel.addEventListener("click", async () => {
        const ok = await UI.confirm({
          title: "取消检测任务",
          message: "正在进行的模型请求会被中止，已产生的部分结果可能不会归档。",
          confirmText: "取消任务",
          danger: true,
        });
        if (!ok) return;
        cancel.disabled = true;
        try {
          await API.cancelScan(scan.id);
          UI.toast("正在取消任务…", "info");
          setTimeout(() => {
            if (token === routeToken) renderScanDetail(scan.id, token);
          }, 900);
        } catch (error) {
          UI.toast(error.message, "error");
          cancel.disabled = false;
        }
      });
    }
    const download = $("#download-report");
    const retry = $("#retry-scan");
    if (retry) {
      retry.addEventListener("click", async () => {
        if (!modelConfigured()) {
          UI.toast("请先在「模型设置」中配置模型服务", "error");
          return;
        }
        retry.disabled = true;
        try {
          const { base_url, model, api_key } = state.model;
          const task = await API.retryScan(scan.id, { base_url, model, api_key });
          UI.toast("重试任务已提交", "success");
          if (token === routeToken) location.hash = `#/scans/${task.id}`;
        } catch (error) {
          UI.toast(error.message || "重试提交失败", "error");
        } finally {
          retry.disabled = false;
        }
      });
    }
    if (download) {
      download.addEventListener("click", async () => {
        download.disabled = true;
        try {
          await window.downloadReport(scan.id);
        } catch (error) {
          UI.toast(error.message || "下载失败", "error");
        } finally {
          download.disabled = false;
        }
      });
    }
    const remove = $("#delete-scan");
    if (remove) {
      remove.addEventListener("click", async () => {
        const ok = await UI.confirm({
          title: "删除检测记录",
          message: "任务、源码快照与报告都会被删除，且无法恢复。",
          confirmText: "删除",
          danger: true,
        });
        if (!ok) return;
        try {
          const removed = await deleteScanRecord(scan.id);
          if (!removed) return;
          UI.toast("记录已删除", "success");
          location.hash = "#/scans";
        } catch (error) {
          UI.toast(error.message, "error");
        }
      });
    }
  }

  function patchScanProgress(scan) {
    state.currentScan = scan;
    const statusSlot = $("[data-scan-status]");
    if (statusSlot) statusSlot.innerHTML = UI.statusChip(scan.status);
    const detail = $("[data-status-detail]");
    if (detail) detail.textContent = scan.status_detail || "";
    const count = $("[data-progress-count]");
    if (count) count.textContent = `${scan.completed_files}/${scan.total_files || "—"}`;
    const bar = $("[data-progress-bar]");
    if (bar) {
      const percent = scan.total_files
        ? Math.min(100, Math.round((scan.completed_files / scan.total_files) * 100))
        : 0;
      bar.style.width = `${percent}%`;
    }
    const timeline = $("[data-timeline]");
    if (timeline) timeline.innerHTML = eventsMarkup(scan.events);
    if (state.workbench.scanId === scan.id && (scan.findings || []).length !== state.workbench.shown) {
      state.workbench.shown = (scan.findings || []).length;
      wbPaint(scan);
    }
  }

  function startPoll(id, token) {
    clearPoll();
    const terminal = ["succeeded", "partial", "failed", "cancelled"];
    state.poll = setInterval(async () => {
      const route = currentRoute();
      if (route.name !== "scans" || route.id !== id || token !== routeToken) {
        clearPoll();
        return;
      }
      try {
        const scan = await API.scan(id);
        if (!state.currentScan || state.currentScan.id !== id) {
          clearPoll();
          return;
        }
        if (terminal.includes(scan.status)) {
          clearPoll();
          state.currentScan = scan;
          paintScanDetail(scan, token);
          if (scan.status === "succeeded") UI.toast("检测完成", "success");
          else if (scan.status === "partial") UI.toast("检测部分完成，请查看错误与范围限制", "warn");
          else if (scan.status === "failed") UI.toast(scan.error_message || "检测失败", "error");
          else UI.toast("任务已取消", "info");
          return;
        }
        patchScanProgress(scan);
      } catch (error) {
        if (error.status === 404) clearPoll();
      }
    }, 2500);
  }

  /* ------------------------------------------------------------------ boot */

  async function boot() {
    window.addEventListener("hashchange", handleRoute);
    try {
      await loadWorkspaceData();
      if (!location.hash) history.replaceState(null, "", "#/new");
      renderShell();
      handleRoute();
    } catch (error) {
      const app = $("#app");
      app.className = "boot";
      app.innerHTML = `<div class="boot-mark">W</div>
        <p>无法连接后端：${UI.esc(error.message || "请确认服务已启动")}</p>
        <button class="btn btn-primary" id="boot-retry">重新加载</button>`;
      $("#boot-retry").addEventListener("click", () => location.reload());
    }
  }

  boot();
})();
