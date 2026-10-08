/* API 客户端：统一封装 fetch，负责心跳、错误提示与当前跑团参数的自动附加。 */
const API = (() => {
  let activeCampaign = "";

  async function request(method, path, body) {
    let url = path;
    if (path.startsWith("/api/") && !/[?&]campaign=/.test(url) && path !== "/api/campaigns"
        && !path.startsWith("/api/backups") && !path.startsWith("/api/trash")) {
      const sep = url.includes("?") ? "&" : "?";
      if (/^\/api\/(characters|monsters|stories|files|records|dice)/.test(path) && activeCampaign) {
        url += sep + "campaign=" + encodeURIComponent(activeCampaign);
      }
    }
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const res = await fetch(url, options);
    const text = await res.text();
    let payload;
    if (res.headers.get("content-type")?.includes("application/json")) {
      payload = JSON.parse(text);
    } else {
      payload = text;
    }
    if (res.status >= 400) {
      const err = (payload && payload.error) || { message: text || res.statusText };
      const e = new Error(err.message || "请求失败");
      e.code = err.code;
      e.details = err.details;
      throw e;
    }
    return payload && typeof payload === "object" && "ok" in payload ? payload.data : payload;
  }

  return {
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, b),
    put: (p, b) => request("PUT", p, b),
    patch: (p, b) => request("PATCH", p, b),
    del: (p, b) => request("DELETE", p, b),
    raw: request,
    setCampaign(id) { activeCampaign = id; },
    getCampaign() { return activeCampaign; },
    ping: () => request("POST", "/api/ping", {}).catch(() => null),
  };
})();
