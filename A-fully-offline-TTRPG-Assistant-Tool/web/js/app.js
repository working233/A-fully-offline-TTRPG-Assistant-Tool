/* 应用外壳：导航切换、跑团下拉、心跳与全局提示。 */
window.Toast = function (message, kind = "ok") {
  const box = document.getElementById("toast");
  const item = document.createElement("div");
  item.className = "toast-item " + (kind === "error" ? "error" : kind === "ok" ? "ok" : "");
  item.textContent = message;
  box.appendChild(item);
  setTimeout(() => { item.style.opacity = "0"; item.style.transition = "opacity .2s"; }, 2600);
  setTimeout(() => item.remove(), 2900);
};

const App = (() => {
  let currentView = location.hash.replace("#", "") || "dice";
  let campaigns = [];

  async function api(fn, fallback = null) {
    try { return await fn(); }
    catch (e) { window.Toast(e.message, "error"); return fallback; }
  }

  async function loadCampaigns() {
    const data = await api(() => API.get("/api/campaigns"), { items: [], active: "" });
    campaigns = data.items || [];
    document.getElementById("data-root").textContent = data.data_root || "";
    const sel = document.getElementById("campaign-select");
    sel.innerHTML = campaigns.map((c) =>
      `<option value="${c.id}" ${c.is_active ? "selected" : ""}>${c.name}</option>`).join("")
      || `<option value="">（无跑团）</option>`;
    API.setCampaign(data.active || "");
    sel.onchange = async () => {
      await api(() => API.post(`/api/campaigns/${sel.value}/activate`));
      window.Toast("已切换跑团");
      await refresh();
    };
  }

  async function render() {
    const view = Views[currentView] || Views.dice;
    document.getElementById("view-title").textContent = view.title;
    document.getElementById("view-sub").textContent = view.sub;
    document.querySelectorAll(".nav-item").forEach((b) =>
      b.classList.toggle("active", b.dataset.view === currentView));
    const content = document.getElementById("content");
    content.scrollTop = 0;
    content.innerHTML = `<div class="empty">加载中…</div>`;
    try {
      await view.render(content);
      // 切换视图时内容像被烛火照亮一样渐入；连续切换靠强制回流重播动画
      content.classList.remove("view-enter");
      void content.offsetWidth;
      content.classList.add("view-enter");
    } catch (e) {
      content.innerHTML = `<div class="card"><h2>加载失败</h2>
        <p class="sub">${e.message}</p></div>`;
    }
  }

  async function refresh() {
    await loadCampaigns();
    await render();
  }

  function bindNav() {
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.onclick = () => {
        currentView = btn.dataset.view;
        location.hash = currentView;
        render();
      };
    });
  }

  function startHeartbeat() {
    const dot = document.getElementById("status-dot");
    const text = document.getElementById("status-text");
    setInterval(async () => {
      try {
        await fetch("/api/ping", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        dot.classList.remove("off");
        text.textContent = "本地服务运行中";
      } catch {
        dot.classList.add("off");
        text.textContent = "本地服务已停止";
      }
    }, 5000);
  }

  (async function boot() {
    bindNav();
    await loadCampaigns();
    await render();
    startHeartbeat();
  })();

  return { refresh, setView: (v) => { currentView = v; location.hash = v; render(); } };
})();
window.App = App;
