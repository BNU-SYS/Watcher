(function () {
  class ApiError extends Error {
    constructor(message, status, payload) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.payload = payload;
    }
  }

  function detailMessage(payload) {
    if (!payload) return "请求失败，请稍后重试";
    if (typeof payload === "string" && payload.trim()) return payload;
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail
        .map((item) => {
          const field = Array.isArray(item.loc)
            ? item.loc.filter((part) => part !== "body").join(".")
            : "";
          const text = item.msg || "参数不正确";
          return field ? `${field}：${text}` : text;
        })
        .join("；");
    }
    return payload.message || "请求失败，请稍后重试";
  }

  function qs(params) {
    const search = new URLSearchParams();
    Object.keys(params || {}).forEach((key) => {
      const value = params[key];
      if (value !== undefined && value !== null && value !== "") {
        search.set(key, value);
      }
    });
    return search.toString();
  }

  async function request(path, options) {
    const opts = options || {};
    const headers = Object.assign({}, opts.headers || {});
    const init = { method: opts.method || "GET", headers };
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.json);
    } else if (opts.body !== undefined) {
      init.body = opts.body;
    }

    let response;
    try {
      response = await fetch(`/api${path}`, init);
    } catch (error) {
      throw new ApiError("网络连接失败，请确认后端服务正在运行", 0, null);
    }

    if (response.status === 204) return null;

    const type = response.headers.get("content-type") || "";
    let payload = null;
    if (type.includes("application/json")) {
      try {
        payload = await response.json();
      } catch (error) {
        payload = null;
      }
    } else {
      payload = await response.text();
    }
    if (!response.ok) {
      throw new ApiError(detailMessage(payload), response.status, payload);
    }
    return payload;
  }

  async function downloadReport(scanId) {
    const response = await fetch(`/api/scans/${scanId}/report`);
    if (!response.ok) throw new ApiError("报告下载失败", response.status, null);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `watcher-${scanId}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.API = {
    ApiError,
    catalog: () => request("/catalog"),
    health: () => request("/health"),
    verifyModel: (data) => request("/model/verify", { method: "POST", json: data }),
    stats: () => request("/scans/stats"),
    scans: (params) => request(`/scans?${qs(params)}`),
    scan: (id) => request(`/scans/${id}`),
    feedbackReports: () => request("/feedback/reports"),
    createFeedback: (data) => request("/feedback", { method: "POST", json: data }),
    findings: (id, params) => request(`/scans/${id}/findings?${qs(params)}`),
    createScan: (formData) => request("/scans", { method: "POST", body: formData }),
    retryScan: (id, data) => request(`/scans/${id}/retry`, { method: "POST", json: data }),
    cancelScan: (id) => request(`/scans/${id}/cancel`, { method: "POST" }),
    deleteScan: (id, cascade) => request(`/scans/${id}${cascade ? "?cascade=true" : ""}`, { method: "DELETE" }),
    source: (id, path) =>
      request(`/scans/${id}/source?path=${encodeURIComponent(path)}`),
  };
  window.downloadReport = downloadReport;
})();
