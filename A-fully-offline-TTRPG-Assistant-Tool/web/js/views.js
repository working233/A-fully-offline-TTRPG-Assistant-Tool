/* 视图层：每个 View 导出 {title, sub, render(root)}，由 app.js 负责挂载。
   统一约定：破坏性操作必须先 confirm；操作结果交给 toast 提示。 */
const Views = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function html(tag, attrs = {}, inner = "") {
    const a = Object.entries(attrs).map(([k, v]) => `${k}="${esc(v)}"`).join(" ");
    return `<${tag} ${a}>${inner}</${tag}>`;
  }
  function toast(msg, kind = "ok") { window.Toast(msg, kind); }
  const confirmBox = (msg) => window.confirm(msg);

  /** 播一次动画：`先移除 class → 强制回流 → 再加`，保证连续触发时动画能重播。 */
  function pulse(el, cls = "shake") {
    if (!el) return;
    el.classList.remove(cls);
    void el.offsetWidth;
    el.classList.add(cls);
    setTimeout(() => el.classList.remove(cls), 720);
  }

  /** 角色卡的肖像金框：有立绘就显示图，没有就退回姓名首字徽记。 */
  function portraitFrame(data, src) {
    const name = String(data.name || "未命名");
    const initial = name.trim().slice(0, 1) || "?";
    const sub = [data.klass, data.race].filter(Boolean).join(" · ");
    return `<div class="portrait-frame">
      <div class="portrait-inner">
        ${src ? `<img src="${src}" alt="肖像：${esc(name)}" />`
              : `<span class="portrait-fallback">${esc(initial)}</span>`}
      </div>
      <div class="portrait-caption">
        <strong>${esc(name)}</strong>
        <span>${esc(sub || "尚无职业 / 种族")}</span>
      </div>
    </div>`;
  }

  /** 怪物卡的符文框：同样是个金框，中间放挑战等级。 */
  function runeFrame(data) {
    return `<div class="portrait-frame rune">
      <div class="portrait-inner"><span class="portrait-fallback">${esc(String(data.cr || "?"))}</span></div>
      <div class="portrait-caption">
        <strong>${esc(data.name || "未命名")}</strong>
        <span>挑战等级 CR</span>
      </div>
    </div>`;
  }

  /** 读取角色立绘：portrait 字段是跑团目录内的相对路径，服务端返回 base64。 */
  async function loadPortrait(rel) {
    if (!rel) return null;
    try {
      const r = await API.get(`/api/files/content?path=${encodeURIComponent(rel)}`);
      return r && r.base64 ? `data:${r.mime || "image/png"};base64,${r.base64}` : null;
    } catch (e) {
      return null;  // 找不到图就退回文字徽记，不打扰用户
    }
  }

  async function reload() { await window.App.refresh(); }

  /* ============================ 跑团管理 ============================ */
  const campaigns = {
    title: "跑团管理",
    sub: "每个跑团是一份自包含文件夹，可直接复制、压缩备份或迁移到另一台设备",
    async render(root) {
      const data = await API.get("/api/campaigns");
      const active = data.active;
      const cards = data.items.length ? data.items.map((c) => `
        <div class="card" style="margin-bottom:12px">
          <div class="row between">
            <div>
              <h2>${esc(c.name)} ${c.is_active ? '<span class="badge green">当前</span>' : ""}</h2>
              <p class="sub">${esc(c.system)} · DM：${esc(c.dm || "未设置")} · 创建于 ${esc((c.created_at || "").slice(0, 10))}</p>
              <p class="small muted">${esc(c.description || "暂无简介")}</p>
              <p class="small muted">角色 ${c.counts?.characters ?? 0} · 怪物 ${c.counts?.monsters ?? 0} ·
                 剧情 ${c.counts?.stories ?? 0} · 地图 ${c.counts?.maps ?? 0} · 笔记 ${c.counts?.notes ?? 0} · 日志 ${c.counts?.log_lines ?? 0}</p>
            </div>
            <div class="row">
              ${c.is_active ? '<span class="badge blue">使用中</span>'
                : `<button class="btn primary" data-act="activate" data-id="${esc(c.id)}">切换</button>`}
              <button class="btn" data-act="backup" data-id="${esc(c.id)}">备份</button>
              <button class="btn danger" data-act="delete" data-id="${esc(c.id)}">删除</button>
            </div>
          </div>
        </div>`).join("") : `<div class="empty">还没有跑团，先在右侧创建一个。</div>`;

      root.innerHTML = `
        <div class="grid cols-2">
          <div style="flex:2">
            <div class="card">
              <h2>新建跑团</h2>
              <p class="sub">会自动生成 characters / monsters / maps / notes / stories / logs / assets 目录</p>
              <div class="field"><label>名称</label><input id="cp-name" placeholder="例如：空心灯塔" /></div>
              <div class="field"><label>规则</label>
                <select id="cp-system"><option>DND 5e</option><option>COC 7th</option><option>泛用/无规则</option><option>自定义</option></select>
              </div>
              <div class="field"><label>DM / 主持人</label><input id="cp-dm" /></div>
              <div class="field"><label>简介</label><textarea id="cp-desc" rows="3"></textarea></div>
              <button class="btn primary" id="cp-create">创建并切换</button>
            </div>
          </div>
          <div>${cards}</div>
        </div>`;

      root.querySelector("#cp-create").onclick = async () => {
        const name = root.querySelector("#cp-name").value.trim();
        if (!name) return toast("请填写跑团名称", "error");
        await API.post("/api/campaigns", {
          name, system: root.querySelector("#cp-system").value,
          dm: root.querySelector("#cp-dm").value.trim(),
          description: root.querySelector("#cp-desc").value.trim(),
        });
        toast(`已创建跑团：${name}`);
        await reload();
      };
      root.querySelectorAll("[data-act]").forEach((btn) => {
        btn.onclick = async () => {
          const id = btn.dataset.id;
          const act = btn.dataset.act;
          try {
            if (act === "activate") {
              await API.post(`/api/campaigns/${id}/activate`);
              toast("已切换跑团");
              await reload();
            } else if (act === "backup") {
              const r = await API.post("/api/backups", { campaign: id });
              toast(`已备份到 ${r.file}`);
            } else if (act === "delete") {
              if (!confirmBox("删除后进入回收站，可在「回收站 / 备份」中恢复。确认删除？")) return;
              await API.del(`/api/campaigns/${id}`);
              toast("已移入回收站");
              await reload();
            }
          } catch (e) { toast(e.message, "error"); }
        };
      });
    },
  };

  /* ====================== 角色卡 / 怪物卡 ====================== */
  function entityView(kind) {
    const label = kind === "character" ? "角色卡" : "怪物卡";
    // 注意：REST 资源名是复数（characters/monsters），而 Schema/模板用的是单数（character/monster）
    const path = kind === "character" ? "characters" : "monsters";
    return {
      title: label + "管理",
      sub: "表单由服务端 Schema 动态生成；新增小众规则只需改 schema 字段定义（表单会自动长出对应输入框）",
      async render(root) {
        const [schema, list] = await Promise.all([
          API.get(`/api/schemas/${kind}`), API.get(`/api/${path}`),
        ]);
        root.innerHTML = `<div class="grid cols-2">
          <div class="card" style="max-height:70vh;overflow:auto">
            <div class="row between"><h2>${label}列表</h2>
              <button class="btn primary" id="new-btn">新建</button></div>
            <div id="entity-list">${renderList(list.items)}</div>
          </div>
          <div class="card" id="editor-pane"><div class="empty">从左侧选择一张卡，或点击「新建」</div></div>
        </div>`;

        function renderList(items) {
          if (!items.length) return `<div class="empty">暂无${label}</div>`;
          return items.map((it) => `
            <div class="list-item" data-slug="${esc(it.slug)}">
              <div>
                <div class="title">${esc(it.name)} <span class="badge">${esc(it.system)}</span></div>
                <div class="meta">${kind === "character"
                  ? `Lv.${it.summary.level ?? "-"} ${esc(it.summary.klass)} · HP ${esc(it.summary.hp)} · AC ${esc(it.summary.ac)}`
                  : `CR ${esc(it.summary.cr)} · ${esc(it.summary.type)} · HP ${esc(it.summary.hp)} · AC ${esc(it.summary.ac)}`}</div>
              </div>
              <button class="btn small ghost" data-open="${esc(it.slug)}">编辑</button>
            </div>`).join("");
        }

        const pane = root.querySelector("#editor-pane");
        async function open(slug) {
          let data;
          if (slug === "__new__") {
            data = await API.get(`/api/templates/${kind}?system=DND 5e`);
            data._isNew = true;
          } else {
            data = await API.get(`/api/${path}/${encodeURIComponent(slug)}`);
          }
          const list = Array.isArray((schema.fields || [])) ? schema.fields : [];
          const portraitSrc = kind === "character" ? await loadPortrait(data.portrait) : null;
          const frameHtml = kind === "character" ? portraitFrame(data, portraitSrc) : runeFrame(data);
          pane.innerHTML = `
            <div class="row between">
              <h2>${slug === "__new__" ? "新建" : "编辑"}${label}</h2>
              <div class="row">
                <button class="btn" id="toggle-json">查看 JSON</button>
                ${slug === "__new__" ? "" : `<button class="btn" id="dup">复制</button>
                  <button class="btn danger" id="del">删除</button>`}
                <button class="btn primary" id="save">保存</button>
              </div>
            </div>
            ${slug === "__new__" ? "" : `<div class="row" style="margin:8px 0">
                <span class="small muted">HP 快捷：</span>
                <button class="btn" data-hp="-5">-5</button><button class="btn" data-hp="-1">-1</button>
                <button class="btn" data-hp="1">+1</button><button class="btn" data-hp="5">+5</button>
              </div>`}
            ${frameHtml}
            <div id="form-area">${list.map((f) => buildField(f, data, "")).join("")}</div>
            <div id="json-area" style="display:none">
              <textarea class="editor" id="json-raw">${esc(JSON.stringify(stripMeta(data), null, 2))}</textarea>
            </div>
            <div id="err" class="field-err"></div>`;

          pane.querySelector("#toggle-json").onclick = (e) => {
            const showingJson = pane.querySelector("#json-area").style.display !== "none";
            if (showingJson) {
              pane.querySelector("#json-area").style.display = "none";
              pane.querySelector("#form-area").style.display = "";
              e.target.textContent = "查看 JSON";
            } else {
              pane.querySelector("#json-area").style.display = "";
              pane.querySelector("#form-area").style.display = "none";
              e.target.textContent = "返回表单";
            }
          };
          pane.querySelector("#save").onclick = async () => {
            pane.querySelector("#err").textContent = "";
            let payload;
            try {
              const showingJson = pane.querySelector("#json-area").style.display !== "none";
              payload = showingJson
                ? JSON.parse(pane.querySelector("#json-raw").value)
                : collectForm(pane.querySelector("#form-area"), data);
            } catch (e) {
              pane.querySelector("#err").textContent = "JSON 解析失败：" + e.message;
              return;
            }
            try {
              if (slug === "__new__") {
                await API.post(`/api/${path}`, payload);
                toast("已创建");
                await reload();
              } else {
                await API.put(`/api/${path}/${encodeURIComponent(slug)}`, payload);
                toast("已保存");
                await open(slug);
              }
            } catch (e2) {
              pane.querySelector("#err").textContent = e2.message;
              toast(e2.message, "error");
            }
          };
          if (slug !== "__new__") {
            pane.querySelector("#del").onclick = async () => {
              if (!confirmBox(`删除「${data.name}」？可在回收站恢复。`)) return;
              await API.del(`/api/${path}/${encodeURIComponent(slug)}`);
              toast("已移入回收站");
              await reload();
            };
            pane.querySelector("#dup").onclick = async () => {
              await API.post(`/api/${path}/${encodeURIComponent(slug)}/duplicate`, {});
              toast("已创建副本");
              await reload();
            };
            pane.querySelectorAll("[data-hp]").forEach((b) => b.onclick = async () => {
              await API.post(`/api/${path}/${encodeURIComponent(slug)}/hp`, { delta: Number(b.dataset.hp) });
              await open(slug);
            });
          }
        }

        function stripMeta(d) { const c = { ...d }; delete c._slug; delete c._isNew; return c; }

        function buildField(f, data, prefix) {
          const path = prefix ? `${prefix}.${f.key}` : f.key;
          const value = getPath(data, f.key, prefix);
          switch (f.type) {
            case "string":
              return `<div class="field"><label>${esc(f.label)}</label>
                <input data-path="${esc(path)}" value="${esc(value ?? "")}" placeholder="${esc(f.placeholder || "")}" /></div>`;
            case "number":
              return `<div class="field"><label>${esc(f.label)}</label>
                <input type="number" data-path="${esc(path)}" value="${esc(value ?? f.default ?? 0)}" /></div>`;
            case "textarea":
              return `<div class="field"><label>${esc(f.label)}</label>
                <textarea rows="3" data-path="${esc(path)}">${esc(value ?? "")}</textarea></div>`;
            case "enum":
              return `<div class="field"><label>${esc(f.label)}</label><select data-path="${esc(path)}">
                ${(f.options || []).map((o) => `<option ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("")}
                ${(f.options || []).includes(value) ? "" : `<option selected>${esc(value ?? "")}</option>`}
              </select></div>`;
            case "map":
              return `<div class="field"><label>${esc(f.label)}</label>
                <textarea rows="4" data-path="${esc(path)}" data-kind="map">${esc(mapToText(value))}</textarea>
                <div class="hint">每行一条，格式：键: 值</div></div>`;
            case "list":
              if (f.item_type === "object") {
                return `<div class="field"><label>${esc(f.label)}（JSON 数组）</label>
                  <textarea rows="5" data-path="${esc(path)}" data-kind="json">${esc(JSON.stringify(value ?? [], null, 2))}</textarea></div>`;
              }
              return `<div class="field"><label>${esc(f.label)}</label>
                <textarea rows="4" data-path="${esc(path)}" data-kind="list">${esc((value || []).join("\n"))}</textarea>
                <div class="hint">每行一项</div></div>`;
            case "group":
              return `<div class="card" style="margin:10px 0;box-shadow:none">
                <h2 style="font-size:13px">${esc(f.label)}</h2>
                ${(f.children || []).map((c) => buildField(c, value || {}, path)).join("")}</div>`;
            default:
              return `<div class="field"><label>${esc(f.label)}（原始 JSON）</label>
                <textarea rows="3" data-path="${esc(path)}" data-kind="json">${esc(JSON.stringify(value ?? null))}</textarea></div>`;
          }
        }

        function getPath(data, key, prefix) {
          const src = prefix ? (getPath(data, prefix.split(".")[0], "") || {}) : data;
          if (prefix && prefix.includes(".")) {
            const parts = prefix.split(".");
            let cur = data;
            for (const p of parts) cur = cur ? cur[p] ?? {} : {};
            return cur ? cur[key] : undefined;
          }
          return src ? src[key] : undefined;
        }

        function mapToText(value) {
          if (!value || typeof value !== "object") return "";
          return Object.entries(value).map(([k, v]) => `${k}: ${v}`).join("\n");
        }

        function collectForm(formArea, original) {
          const out = JSON.parse(JSON.stringify(stripMeta(original)));
          formArea.querySelectorAll("[data-path]").forEach((ctrl) => {
            const kindAttr = ctrl.dataset.kind;
            const raw = ctrl.value;
            let value;
            if (kindAttr === "map") {
              value = {};
              raw.split("\n").forEach((line) => {
                const [k, ...rest] = line.split(":");
                if (k && k.trim()) value[k.trim()] = parseScalar(rest.join(":").trim());
              });
            } else if (kindAttr === "list") {
              value = raw.split("\n").map((x) => x.trim()).filter(Boolean);
            } else if (kindAttr === "json") {
              value = raw.trim() ? JSON.parse(raw) : [];
            } else if (ctrl.type === "number") {
              value = raw === "" ? 0 : Number(raw);
            } else {
              value = raw;
            }
            setPath(out, ctrl.dataset.path, value);
          });
          return out;
        }

        function parseScalar(s) {
          if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s);
          return s;
        }

        function setPath(obj, path, value) {
          const parts = path.split(".");
          let cur = obj;
          for (let i = 0; i < parts.length - 1; i++) {
            if (cur[parts[i]] === undefined || cur[parts[i]] === null) cur[parts[i]] = {};
            cur = cur[parts[i]];
          }
          cur[parts[parts.length - 1]] = value;
        }

        root.querySelector("#new-btn").onclick = () => open("__new__");
        root.querySelectorAll("[data-open]").forEach((b) => b.onclick = () => open(b.dataset.open));
        root.querySelectorAll(".list-item").forEach((it) =>
          it.onclick = (e) => { if (!e.target.closest("[data-open]")) open(it.dataset.slug); });
        if (list.items.length) open(list.items[0].slug);
      },
    };
  }

  /* ============================ 骰子 ============================ */
  const dice = {
    title: "骰子系统",
    sub: "支持 d4/d6/d8/d10/d12/d20 与任意自定义表达式、调整值、优劣势、期望值与概率",
    async render(root) {
      const [schema] = await Promise.all([API.get("/api/dice/history?limit=60")]);
      const history = schema.items || [];
      root.innerHTML = `
        <div class="grid cols-2">
          <div>
            <div class="card">
              <h2>快捷投掷</h2>
              <p class="sub">选面数 → 设数量与调整值 → 投掷</p>
              <div class="quick-dice">${[4, 6, 8, 10, 12, 20, 100].map((s) =>
                `<button data-sides="${s}">d${s}</button>`).join("")}</div>
              <div class="row" style="margin-top:12px">
                <label class="small">数量 <input id="d-count" type="number" value="1" min="1" max="100" style="width:70px" /></label>
                <label class="small">调整值 <input id="d-mod" type="number" value="0" style="width:80px" /></label>
                <select id="d-adv"><option value="none">正常</option><option value="advantage">优势</option><option value="disadvantage">劣势</option></select>
                <input id="d-label" placeholder="标签（如 攻击检定）" style="flex:1;min-width:140px" />
              </div>
              <div class="row" style="margin-top:10px">
                <input id="d-expr" placeholder="或直接输入表达式：2d6+3 / 4d6kh3 / d20+5" style="flex:1;min-width:200px" />
                <button class="btn primary" id="roll">投掷</button>
              </div>
              <div class="small muted" id="expect-hint" style="margin-top:8px"></div>
            </div>
            <div class="card" id="result-card" style="display:none"></div>
          </div>
          <div>
            <div class="card">
              <div class="row between"><h2>投掷历史</h2><button class="btn" id="clear">清空</button></div>
              <div id="hist"></div>
            </div>
          </div>
        </div>`;

      const count = root.querySelector("#d-count"), mod = root.querySelector("#d-mod");
      const expr = root.querySelector("#d-expr"), label = root.querySelector("#d-label");
      const adv = root.querySelector("#d-adv"), hint = root.querySelector("#expect-hint");
      const card = root.querySelector("#result-card");

      function currentExpr(sides) {
        const c = Math.max(1, parseInt(count.value || "1", 10));
        const m = parseInt(mod.value || "0", 10) || 0;
        const base = `${c}d${sides || 20}`;
        return base + (m ? (m > 0 ? `+${m}` : `${m}`) : "");
      }
      async function updateHint() {
        const e = expr.value.trim() || currentExpr(20);
        try {
          const r = await API.get(`/api/dice/expected?expr=${encodeURIComponent(e)}&advantage=${adv.value}`);
          hint.textContent = `表达式 ${e} 的期望值：${r.expected}`;
        } catch (err) { hint.textContent = "期望值：" + err.message; }
      }
      root.querySelectorAll("[data-sides]").forEach((b) => b.onclick = async () => {
        expr.value = currentExpr(b.dataset.sides);
        pulse(b, "shake");                 // 抓起骰子抖一下
        await doRoll(expr.value);
      });
      expr.oninput = count.oninput = mod.oninput = () => updateHint();
      adv.onchange = () => updateHint();
      root.querySelector("#roll").onclick = async () => {
        pulse(root.querySelector("#roll"), "shake");
        await doRoll(expr.value.trim() || currentExpr(20));
      };
      root.querySelector("#clear").onclick = async () => { await API.del("/api/dice/history"); toast("已清空"); renderHistory([]); };
      expr.onkeydown = (e) => { if (e.key === "Enter") doRoll(expr.value.trim()); };

      async function doRoll(value) {
        expr.value = value;
        try {
          const r = await API.post("/api/dice/roll", {
            expression: value, advantage: adv.value === "none" ? null : adv.value,
            label: label.value.trim(),
          });
          renderResult(r);
          const h = await API.get("/api/dice/history?limit=60");
          renderHistory(h.items);
        } catch (e) { toast(e.message, "error"); }
      }

      function renderResult(r) {
        card.style.display = "";
        let chipIndex = 0;   // 用 --i 做错峰入场，骰点像被依次掷出来
        const terms = (r.terms || []).map((t) => `
          <div style="margin-bottom:6px">
            <span class="badge">${esc(t.notation)}</span>
            ${(t.rolls || []).map((v) => `<span class="dice-chip ${t.dropped && t.dropped.length && !t.kept.includes(v) ? "dropped" : ""}" style="--i:${chipIndex++}">${v}</span>`).join("")}
            <span class="small muted">小计 ${t.subtotal}（期望 ${t.expected}）</span>
          </div>`).join("");
        const probDc = Number(r.notation.includes("d20") ? 15 : 0);
        card.innerHTML = `
          <div class="row between">
            <div>
              <div class="dice-total ${r.critical === "crit" ? "crit" : ""}">${r.total}</div>
              <div class="small muted">${esc(r.expression)} ${r.modifier ? `(调整值 ${r.modifier > 0 ? "+" : ""}${r.modifier})` : ""}
                ${r.advantage !== "none" ? `· ${r.advantage === "advantage" ? "优势" : "劣势"}` : ""}
                ${r.critical === "crit" ? "· 暴击！" : r.critical === "fumble" ? "· 大失败" : ""}</div>
            </div>
            <div class="row">
              <button class="btn" id="prob">成功率</button>
              <button class="btn" id="again">再投一次</button>
            </div>
          </div>
          <div style="margin-top:12px">${terms}</div>
          <div class="small muted" style="margin-top:8px">期望值 ${r.expected} · ${esc(r.timestamp)}</div>`;
        pulse(card, "cup-shake");   // 骰盅晃一晃再开盖
        card.querySelector("#again").onclick = () => doRoll(expr.value.trim());
        card.querySelector("#prob").onclick = async () => {
          const dc = prompt("计算「结果 ≥ 该值」的概率？", String(probDc || 10));
          if (!dc) return;
          try {
            const p = await API.get(`/api/dice/probability?expr=${encodeURIComponent(expr.value.trim())}&dc=${encodeURIComponent(dc)}`);
            toast(`${p.expression} ≥ ${p.dc} 的概率：${p.probability_percent}%`);
          } catch (e) { toast(e.message, "error"); }
        };
      }

      function renderHistory(items) {
        const box = root.querySelector("#hist");
        if (!items.length) { box.innerHTML = `<div class="empty">暂无记录</div>`; return; }
        box.innerHTML = items.slice().reverse().map((r) => `
          <div class="list-item">
            <div>
              <div class="title">${r.total} <span class="small muted">${esc(r.expression)}</span>
                ${r.critical === "crit" ? '<span class="badge red">暴击</span>' : ""}
                ${r.critical === "fumble" ? '<span class="badge amber">大失败</span>' : ""}</div>
              <div class="meta">${esc((r.timestamp || "").slice(11, 19))} ${esc(r.label || "")}</div>
            </div>
            <button class="btn ghost" data-copy="${esc(r.expression)}">复用</button>
          </div>`).join("");
        box.querySelectorAll("[data-copy]").forEach((b) => b.onclick = () => { expr.value = b.dataset.copy; updateHint(); });
      }

      renderHistory(history);
      updateHint();
    },
  };

  /* ============================ 剧情编辑器 ============================ */
  const stories = {
    title: "剧情编辑器",
    sub: "主线 / 分支 / 结局节点，支持条件跳转、拖拽布局与 Graphviz DOT 导出",
    async render(root) {
      const list = await API.get("/api/stories");
      root.innerHTML = `
        <div class="card">
          <div class="row between">
            <div class="row">
              <select id="story-select">${(list.items || []).map((s) =>
                `<option value="${esc(s.slug)}">${esc(s.title)}（${s.nodes} 节点 / ${s.endings} 结局）</option>`).join("")}</select>
              <button class="btn" id="new-story">新建剧情</button>
              <button class="btn" id="validate">图谱校验</button>
              <button class="btn" id="layout">自动布局</button>
              <button class="btn" id="dot">导出 DOT</button>
            </div>
            <span id="title-badge" class="badge blue">未选择</span>
          </div>
          <div id="issues" style="margin-top:10px"></div>
        </div>
        <div class="grid cols-2">
          <div class="card" style="min-width:520px">
            <h2>剧情图</h2>
            <p class="sub">拖动节点调整位置自动保存；点击节点进行编辑</p>
            <div class="story-canvas" id="canvas"></div>
          </div>
          <div class="card" id="node-pane"><div class="empty">点击左侧节点开始编辑</div></div>
        </div>
        <div class="card" id="dot-pane" style="display:none">
          <div class="row between"><h2>Graphviz DOT</h2>
            <div class="row"><button class="btn" id="copy-dot">复制</button><button class="btn" id="dl-dot">下载 .dot</button></div></div>
          <p class="sub sub">执行 <code>dot -Tsvg story.dot -o story.svg</code> 即可得到矢量流程图</p>
          <textarea class="editor" id="dot-text" rows="14"></textarea>
        </div>`;

      const sel = root.querySelector("#story-select");
      const canvas = root.querySelector("#canvas");
      const pane = root.querySelector("#node-pane");
      let story = null;

      async function load(slug) {
        story = await API.get(`/api/stories/${encodeURIComponent(slug)}`);
        root.querySelector("#title-badge").textContent = story.title;
        draw();
        renderIssues(null);
      }

      function draw() {
        canvas.innerHTML = "";
        if (!story) return;
        const ids = story.nodes.map((n) => n.id);
        // 连线层
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", "node-link");
        svg.style.position = "absolute"; svg.style.left = "0"; svg.style.top = "0";
        svg.style.width = "3000px"; svg.style.height = "1400px";
        canvas.appendChild(svg);
        const pos = (id) => story.nodes.find((n) => n.id === id)?.position || { x: 0, y: 0 };
        const edges = [];
        story.nodes.forEach((n) => {
          if (n.next && ids.includes(n.next)) edges.push([n.id, n.next, "继续", n.type]);
          (n.choices || []).forEach((c) => {
            if (c.target && ids.includes(c.target)) edges.push([n.id, c.target, c.label || "分支", "choice"]);
          });
        });
        edges.forEach(([a, b, label, type]) => {
          const p1 = pos(a), p2 = pos(b);
          const x1 = p1.x + 190, y1 = p1.y + 40, x2 = p2.x, y2 = p2.y + 40;
          const d = `M ${x1} ${y1} C ${x1 + 60} ${y1}, ${x2 - 60} ${y2}, ${x2} ${y2}`;
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          path.setAttribute("d", d);
          path.setAttribute("fill", "none");
          path.setAttribute("stroke", type === "choice" ? "#a98bff" : "#ffc978");
          path.setAttribute("stroke-width", "1.6");
          if (type === "choice") path.setAttribute("stroke-dasharray", "5 4");
          svg.appendChild(path);
          const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
          t.setAttribute("x", (x1 + x2) / 2); t.setAttribute("y", (y1 + y2) / 2 - 4);
          t.setAttribute("font-size", "11"); t.setAttribute("fill", "#d9c7a3");
          t.setAttribute("text-anchor", "middle"); t.textContent = label;
          svg.appendChild(t);
        });
        // 节点层
        story.nodes.forEach((n) => {
          const box = document.createElement("div");
          box.className = `node-box ${n.type}`;
          box.style.left = `${n.position?.x ?? 40}px`;
          box.style.top = `${n.position?.y ?? 40}px`;
          box.dataset.id = n.id;
          box.innerHTML = `<div class="node-title">${esc(n.title)}</div>
            <div class="node-text">${esc((n.text || "").slice(0, 60))}</div>
            <div class="small" style="margin-top:6px">
              <span class="badge">${esc(n.type)}</span>
              <span class="badge">${(n.choices || []).length} 分支</span></div>`;
          box.onclick = () => {
            canvas.querySelectorAll(".node-box").forEach((b) => b.classList.remove("selected"));
            box.classList.add("selected");
            editNode(n.id);
          };
          let dragging = false, offset = { x: 0, y: 0 };
          box.onmousedown = (e) => {
            dragging = true;
            offset = { x: e.offsetX, y: e.offsetY };
            const move = (ev) => {
              if (!dragging) return;
              const rect = canvas.getBoundingClientRect();
              box.style.left = `${ev.clientX - rect.left + canvas.scrollLeft - offset.x}px`;
              box.style.top = `${ev.clientY - rect.top + canvas.scrollTop - offset.y}px`;
            };
            const up = async (ev) => {
              dragging = false;
              document.removeEventListener("mousemove", move);
              document.removeEventListener("mouseup", up);
              const rect = canvas.getBoundingClientRect();
              const nx = Math.max(0, Math.round(ev.clientX - rect.left + canvas.scrollLeft - offset.x));
              const ny = Math.max(0, Math.round(ev.clientY - rect.top + canvas.scrollTop - offset.y));
              await API.put(`/api/stories/${encodeURIComponent(story._slug)}/nodes/${encodeURIComponent(n.id)}`,
                { position: { x: nx, y: ny } });
              n.position = { x: nx, y: ny };
            };
            document.addEventListener("mousemove", move);
            document.addEventListener("mouseup", up);
          };
          canvas.appendChild(box);
        });
      }

      function options(selected) {
        return story.nodes.map((n) =>
          `<option value="${esc(n.id)}" ${selected === n.id ? "selected" : ""}>${esc(n.title)}</option>`).join("");
      }

      function editNode(id) {
        const n = story.nodes.find((x) => x.id === id);
        if (!n) return;
        pane.innerHTML = `
          <div class="row between"><h2>节点：${esc(n.title)}</h2>
            <button class="btn danger" id="del-node">删除节点</button></div>
          <div class="field"><label>标题</label><input id="n-title" value="${esc(n.title)}" /></div>
          <div class="field"><label>类型</label>
            <select id="n-type">${["main", "branch", "ending"].map((t) =>
              `<option value="${t}" ${n.type === t ? "selected" : ""}>${t === "main" ? "主线" : t === "branch" ? "分支" : "结局"}</option>`).join("")}
            </select></div>
          <div class="field" id="ending-wrap" style="display:${n.type === "ending" ? "" : "none"}">
            <label>结局类型</label>
            <select id="n-ending">${["good", "bad", "neutral", "open"].map((t) =>
              `<option value="${t}" ${n.ending_type === t ? "selected" : ""}>${t}</option>`).join("")}</select></div>
          <div class="field"><label>正文</label><textarea id="n-text" rows="6">${esc(n.text || "")}</textarea></div>
          <div class="field"><label>标签（逗号分隔）</label><input id="n-tags" value="${esc((n.tags || []).join(","))}" /></div>
          <div class="field"><label>直连下一节点</label>
            <select id="n-next"><option value="">（无）</option>${options(n.next)}</select></div>
          <div class="field">
            <label>分支选择</label>
            <div id="choices"></div>
            <button class="btn" id="add-choice" style="margin-top:6px">+ 新增分支</button>
          </div>
          <div class="row"><button class="btn primary" id="save-node">保存节点</button>
            <span class="small muted">删除节点会自动重连父节点，避免图谱断裂</span></div>`;

        const choicesBox = pane.querySelector("#choices");
        function renderChoices() {
          choicesBox.innerHTML = (n.choices || []).map((c, i) => `
            <div class="card" style="box-shadow:none;margin-bottom:8px" data-i="${i}">
              <div class="field"><label>选项文案</label><input data-c="label" value="${esc(c.label || "")}" /></div>
              <div class="field"><label>跳转目标</label><select data-c="target">${options(c.target)}</select></div>
              <div class="field"><label>条件（JSON，可留空）</label>
                <textarea rows="2" data-c="condition">${esc(c.condition ? JSON.stringify(c.condition) : "")}</textarea>
                <div class="hint">例：{"type":"flag","flag":"has_brass_key","equals":true} 或 {"type":"skill","skill":"侦查"}</div></div>
              <div class="field"><label>效果（JSON 数组）</label>
                <textarea rows="2" data-c="effects">${esc(JSON.stringify(c.effects || []))}</textarea></div>
              <button class="btn danger" data-del-c="${i}">删除此分支</button>
            </div>`).join("") || `<div class="small muted">暂无分支</div>`;
          choicesBox.querySelectorAll("[data-del-c]").forEach((b) => b.onclick = () => {
            n.choices.splice(Number(b.dataset.delC), 1); renderChoices();
          });
        }
        renderChoices();
        pane.querySelector("#add-choice").onclick = () => {
          n.choices = n.choices || [];
          n.choices.push({ id: "c" + Date.now(), label: "新选项", target: story.nodes[0].id, condition: null, effects: [] });
          renderChoices();
        };
        pane.querySelector("#n-type").onchange = (e) =>
          pane.querySelector("#ending-wrap").style.display = e.target.value === "ending" ? "" : "none";
        pane.querySelector("#save-node").onclick = async () => {
          const patch = {
            title: pane.querySelector("#n-title").value.trim(),
            type: pane.querySelector("#n-type").value,
            text: pane.querySelector("#n-text").value,
            tags: pane.querySelector("#n-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
            next: pane.querySelector("#n-next").value || null,
          };
          if (patch.type === "ending") patch.ending_type = pane.querySelector("#n-ending").value;
          choicesBox.querySelectorAll("[data-i]").forEach((row, i) => {
            n.choices[i].label = row.querySelector('[data-c="label"]').value.trim();
            n.choices[i].target = row.querySelector('[data-c="target"]').value;
            const cond = row.querySelector('[data-c="condition"]').value.trim();
            n.choices[i].condition = cond ? JSON.parse(cond) : null;
            const eff = row.querySelector('[data-c="effects"]').value.trim();
            n.choices[i].effects = eff ? JSON.parse(eff) : [];
          });
          patch.choices = n.choices;
          try {
            await API.put(`/api/stories/${encodeURIComponent(story._slug)}/nodes/${encodeURIComponent(id)}`, patch);
            toast("节点已保存");
            await load(story._slug);
          } catch (e) { toast(e.message, "error"); }
        };
        pane.querySelector("#del-node").onclick = async () => {
          if (!confirmBox("删除该节点？父节点会自动接上它的后继，原内容进入回收站不可恢复判断前请确认。")) return;
          await API.del(`/api/stories/${encodeURIComponent(story._slug)}/nodes/${encodeURIComponent(id)}`);
          toast("节点已删除并重连线");
          await load(story._slug);
        };
      }

      function renderIssues(report) {
        const box = root.querySelector("#issues");
        if (!report) { box.innerHTML = ""; return; }
        box.innerHTML = `<span class="badge ${report.valid ? "green" : "red"}">${report.valid ? "校验通过" : "存在错误"}</span>
          ${(report.errors || []).map((e) => `<div class="field-err">· ${esc(e)}</div>`).join("")}
          ${(report.warnings || []).map((w) => `<div class="small" style="color:#ffc38f">· 提示：${esc(w)}</div>`).join("")}`;
      }

      sel.onchange = () => load(sel.value);
      root.querySelector("#new-story").onclick = async () => {
        const t = await API.get("/api/schemas/story");
        await API.post("/api/stories", { title: "新剧情", system: "DND 5e" });
        toast("已创建剧情"); await reload();
      };
      root.querySelector("#validate").onclick = async () => {
        try { renderIssues(await API.get(`/api/stories/${encodeURIComponent(sel.value)}/validate`)); }
        catch (e) { toast(e.message, "error"); }
      };
      root.querySelector("#layout").onclick = async () => {
        const r = await API.get(`/api/stories/${encodeURIComponent(sel.value)}/layout`);
        for (const [id, p] of Object.entries(r.positions)) {
          await API.put(`/api/stories/${encodeURIComponent(sel.value)}/nodes/${encodeURIComponent(id)}`, { position: p });
        }
        toast("已重新布局"); await load(sel.value);
      };
      root.querySelector("#dot").onclick = async () => {
        const dot = await API.get(`/api/stories/${encodeURIComponent(sel.value)}/dot`);
        const paneDot = root.querySelector("#dot-pane");
        paneDot.style.display = "";
        root.querySelector("#dot-text").value = dot;
        paneDot.scrollIntoView({ behavior: "smooth" });
      };
      root.querySelector("#copy-dot").onclick = () => {
        const t = root.querySelector("#dot-text"); t.select(); document.execCommand("copy"); toast("已复制");
      };
      root.querySelector("#dl-dot").onclick = () => {
        const blob = new Blob([root.querySelector("#dot-text").value], { type: "text/plain;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = `${sel.value}.dot`; a.click();
      };

      if ((list.items || []).length) {
        sel.value = list.items[0].slug;
        await load(sel.value);
      } else {
        canvas.innerHTML = `<div class="empty">暂无剧情，点击上方「新建剧情」</div>`;
      }
    },
  };

  /* ============================ 文件与笔记 ============================ */
  const files = {
    title: "文件与笔记",
    sub: "双模式：结构化 JSON 由各功能页编辑，此处主要处理纯文本笔记与资源文件",
    async render(root) {
      root.innerHTML = `<div class="grid cols-2">
        <div class="card" style="max-height:74vh;overflow:auto">
          <div class="row between"><h2>目录树</h2>
            <div class="row"><button class="btn" id="new-file">新建文件</button><button class="btn" id="refresh">刷新</button></div></div>
          <div class="tree" id="tree"></div>
        </div>
        <div class="card">
          <div class="row between"><h2 id="file-name">未选择文件</h2>
            <div class="row"><button class="btn primary" id="save-file" disabled>保存</button>
              <button class="btn danger" id="del-file" disabled>删除</button></div></div>
          <textarea class="editor" id="file-content" placeholder="选择一个左侧文件开始编辑（Ctrl+S 保存）"></textarea>
        </div>
      </div>`;

      const treeBox = root.querySelector("#tree");
      const nameEl = root.querySelector("#file-name");
      const contentEl = root.querySelector("#file-content");
      const saveBtn = root.querySelector("#save-file");
      const delBtn = root.querySelector("#del-file");
      let current = "";

      async function loadTree() {
        const tree = await API.get("/api/files?depth=4");
        const rows = [];
        const walk = (nodes, level) => (nodes || []).forEach((n) => {
          rows.push({ ...n, level });
          if (n.children) walk(n.children, level + 1);
        });
        walk(tree.nodes, 0);
        treeBox.innerHTML = rows.map((n) => `
          <div class="tree-row" data-path="${esc(n.path)}" data-type="${esc(n.type)}">
            ${Array.from({ length: n.level }).map(() => `<span class="tree-indent"></span>`).join("")}
            <span>${n.type === "dir" ? "📁" : n.type === "image" ? "🖼️" : n.type === "text" ? "📄" : "📦"}</span>
            <span>${esc(n.name)}</span>
            ${n.type === "dir" ? "" : `<span class="small muted">${(n.size / 1024).toFixed(1)}KB</span>`}
          </div>`).join("");
        treeBox.querySelectorAll(".tree-row").forEach((r) => r.onclick = () => openFile(r.dataset.path, r.dataset.type));
      }

      async function openFile(path, type) {
        treeBox.querySelectorAll(".tree-row").forEach((r) => r.classList.toggle("active", r.dataset.path === path));
        if (type === "dir" || type === "image") return;
        try {
          const r = await API.get(`/api/files/content?path=${encodeURIComponent(path)}`);
          current = path;
          nameEl.textContent = path;
          contentEl.value = r.content || "";
          saveBtn.disabled = false; delBtn.disabled = false;
        } catch (e) { toast(e.message, "error"); }
      }

      saveBtn.onclick = async () => {
        await API.put("/api/files", { path: current, content: contentEl.value });
        toast("已保存（原子写入）");
        await loadTree();
      };
      delBtn.onclick = async () => {
        if (!confirmBox(`删除 ${current}？会移入回收站，可恢复。`)) return;
        await API.del(`/api/files?path=${encodeURIComponent(current)}`);
        toast("已移入回收站");
        current = ""; contentEl.value = ""; nameEl.textContent = "未选择文件";
        await loadTree();
      };
      contentEl.onkeydown = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveBtn.click(); } };
      root.querySelector("#refresh").onclick = loadTree;
      root.querySelector("#new-file").onclick = async () => {
        const p = prompt("新建文件路径（相对跑团目录，如 notes/session-02.txt）", "notes/new-note.txt");
        if (!p) return;
        await API.put("/api/files", { path: p, content: "# 新笔记\n\n" });
        toast("已创建");
        await loadTree();
      };
      await loadTree();
    },
  };

  /* ============================ 跑团记录 ============================ */
  const records = {
    title: "跑团记录",
    sub: "时间线日志 + 玩家花名册 + LOOT 战利品台账，一键导出 Markdown",
    async render(root) {
      const [logs, party] = await Promise.all([
        API.get("/api/records/logs?limit=200"), API.get("/api/records/party")]);
      const types = { event: "事件", combat: "战斗", roleplay: "扮演", loot: "战利品", dice: "检定", milestone: "里程碑" };
      root.innerHTML = `
        <div class="grid cols-2">
          <div>
            <div class="card">
              <h2>记录一条日志</h2>
              <div class="row" style="margin-bottom:8px">
                <select id="log-type">${Object.entries(types).map(([k, v]) =>
                  `<option value="${k}">${v}</option>`).join("")}</select>
                <input id="log-actor" placeholder="当事人 / 角色" style="width:150px" />
                <input id="log-tags" placeholder="标签，逗号分隔" style="flex:1" />
              </div>
              <textarea id="log-text" rows="3" placeholder="发生了什么？"></textarea>
              <div class="row" style="margin-top:8px"><button class="btn primary" id="log-add">写入日志</button></div>
            </div>
            <div class="card">
              <div class="row between"><h2>时间线</h2><span class="small muted">${logs.items.length} 条</span></div>
              <div id="timeline">${logs.items.slice().reverse().map((r) => `
                <div class="list-item">
                  <div>
                    <div class="title"><span class="badge blue">${types[r.type] || r.type}</span>
                      ${r.actor ? `<strong>${esc(r.actor)}</strong>：` : ""} ${esc(r.text)}</div>
                    <div class="meta">${esc(r.timestamp)} ${(r.tags || []).map((t) => `#${esc(t)}`).join(" ")}</div>
                  </div>
                </div>`).join("") || `<div class="empty">暂无记录</div>`}</div>
            </div>
          </div>
          <div>
            <div class="card">
              <h2>玩家花名册</h2>
              <div class="row" style="margin-bottom:8px">
                <input id="p-name" placeholder="玩家名" style="width:120px" />
                <input id="p-char" placeholder="角色名" style="width:140px" />
                <input id="p-contact" placeholder="联系方式 / 时间" style="flex:1" />
                <button class="btn primary" id="p-add">添加</button>
              </div>
              <table><tr><th>玩家</th><th>角色</th><th>备注</th><th></th></tr>
                ${(party.players || []).map((p) => `
                  <tr><td><strong>${esc(p.name)}</strong></td><td>${esc(p.character)}</td>
                    <td class="small muted">${esc(p.contact)}</td>
                    <td><button class="btn ghost" data-del-p="${esc(p.id)}">移除</button></td></tr>`).join("") || ""}
              </table>
            </div>
            <div class="card">
              <div class="row between"><h2>LOOT 战利品</h2>
                <span class="small muted">合计 ${party.loot?.length ?? 0} 项</span></div>
              <div class="row" style="margin-bottom:8px">
                <input id="l-name" placeholder="物品名" style="flex:2" />
                <input id="l-qty" type="number" value="1" style="width:70px" />
                <input id="l-value" placeholder="价值" style="width:110px" />
                <input id="l-owner" placeholder="持有者" style="width:110px" />
                <button class="btn primary" id="l-add">入账</button>
              </div>
              <table><tr><th>物品</th><th>数量</th><th>价值</th><th>持有</th><th>状态</th><th></th></tr>
                ${(party.loot || []).map((l) => `
                  <tr><td>${esc(l.name)}</td><td>${esc(l.qty)}</td><td>${esc(l.value)}</td>
                    <td>${esc(l.owner || "队伍")}</td>
                    <td>${esc(l.status)}</td>
                    <td><button class="btn ghost" data-del-l="${esc(l.id)}">×</button></td></tr>`).join("") || ""}
              </table>
            </div>
            <div class="card">
              <h2>导出</h2>
              <p class="sub">导出 Markdown（含玩家名单、LOOT 台账与时间线），便于发到群里复盘</p>
              <button class="btn primary" id="export">生成 Markdown</button>
              <textarea class="editor" id="md" rows="10" style="margin-top:10px"></textarea>
            </div>
          </div>
        </div>`;

      root.querySelector("#log-add").onclick = async () => {
        const text = root.querySelector("#log-text").value.trim();
        if (!text) return toast("内容为空", "error");
        await API.post("/api/records/logs", {
          text, type: root.querySelector("#log-type").value,
          actor: root.querySelector("#log-actor").value.trim(),
          tags: root.querySelector("#log-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
        });
        toast("已写入日志"); await reload();
      };
      root.querySelector("#p-add").onclick = async () => {
        await API.post("/api/records/party", {
          name: root.querySelector("#p-name").value.trim(),
          character: root.querySelector("#p-char").value.trim(),
          contact: root.querySelector("#p-contact").value.trim(),
        });
        toast("已添加玩家"); await reload();
      };
      root.querySelectorAll("[data-del-p]").forEach((b) => b.onclick = async () => {
        await API.del(`/api/records/party?player_id=${b.dataset.delP}`); toast("已移除"); await reload();
      });
      root.querySelector("#l-add").onclick = async () => {
        await API.post("/api/records/loot", {
          name: root.querySelector("#l-name").value.trim(),
          qty: Number(root.querySelector("#l-qty").value || 1),
          value: root.querySelector("#l-value").value.trim(),
          owner: root.querySelector("#l-owner").value.trim(),
        });
        toast("已入账"); await reload();
      };
      root.querySelectorAll("[data-del-l]").forEach((b) => b.onclick = async () => {
        await API.del(`/api/records/loot/${b.dataset.delL}`); toast("已删除"); await reload();
      });
      root.querySelector("#export").onclick = async () => {
        root.querySelector("#md").value = await API.get("/api/records/export?format=md");
        toast("已生成");
      };
    },
  };

  /* ============================ 回收站 / 备份 ============================ */
  const trash = {
    title: "回收站 / 备份",
    sub: "删除一律进回收站而非物理删除；备份为整包 zip，可直接拷到另一台设备",
    async render(root) {
      const [items, backups] = await Promise.all([API.get("/api/trash"), API.get("/api/backups")]);
      root.innerHTML = `
        <div class="grid cols-2">
          <div class="card">
            <div class="row between"><h2>回收站</h2>
              <div class="row"><button class="btn danger" id="empty">清空回收站</button></div></div>
            <p class="sub">所有删除都保留原始路径信息，可一键还原</p>
            ${(items.items || []).map((t) => `
              <div class="list-item">
                <div>
                  <div class="title"><span class="badge">${esc(t.kind)}</span> ${esc(t.origin || t.original_path)}</div>
                  <div class="meta">${esc(t.deleted_at)} · ${((t.size || 0) / 1024).toFixed(1)}KB</div>
                </div>
                <div class="row">
                  <button class="btn" data-restore="${esc(t.token)}">还原</button>
                  <button class="btn danger" data-purge="${esc(t.token)}">彻底删除</button>
                </div>
              </div>`).join("") || `<div class="empty">回收站是空的</div>`}
          </div>
          <div class="card">
            <div class="row between"><h2>备份</h2>
              <div class="row">
                <button class="btn primary" id="bk-one">备份当前跑团</button>
                <button class="btn" id="bk-all">全量备份</button>
              </div></div>
            <p class="sub">保存目录：${esc(backups.items.length ? "数据目录 / _backups" : "数据目录 / _backups")}</p>
            <table><tr><th>文件</th><th>范围</th><th>大小</th><th></th></tr>
              ${(backups.items || []).map((b) => `
                <tr><td>${esc(b.file)}</td><td>${esc(b.scope)}</td>
                  <td>${(b.size / 1024).toFixed(1)}KB</td>
                  <td><button class="btn ghost" data-restore-bk="${esc(b.file)}">还原</button></td></tr>`).join("") || ""}
            </table>
            <div class="card note" style="box-shadow:none;margin-top:12px">
              <h2>迁移提示</h2>
              <p class="sub">把整个数据目录（或 _backups 下的 zip）拷到另一台机器，启动本工具并执行「还原」即可继续。</p>
            </div>
          </div>
        </div>`;

      root.querySelectorAll("[data-restore]").forEach((b) => b.onclick = async () => {
        await API.post("/api/trash/restore", { token: b.dataset.restore });
        toast("已还原"); await reload();
      });
      root.querySelectorAll("[data-purge]").forEach((b) => b.onclick = async () => {
        if (!confirmBox("彻底删除后不可恢复，确认？")) return;
        await API.del(`/api/trash?token=${b.dataset.purge}`); toast("已彻底删除"); await reload();
      });
      root.querySelector("#empty").onclick = async () => {
        if (!confirmBox("清空回收站？所有条目将被物理删除。")) return;
        await API.del("/api/trash"); toast("已清空"); await reload();
      };
      root.querySelector("#bk-one").onclick = async () => {
        const r = await API.post("/api/backups", { campaign: API.getCampaign() });
        toast("已生成：" + r.file); await reload();
      };
      root.querySelector("#bk-all").onclick = async () => {
        const r = await API.post("/api/backups", { campaign: null });
        toast("已生成全量备份：" + r.file); await reload();
      };
      root.querySelectorAll("[data-restore-bk]").forEach((b) => b.onclick = async () => {
        await API.post("/api/backups/restore", { file: b.dataset.restoreBk });
        toast("已还原"); await reload();
      });
    },
  };

  return {
    campaigns, dice, stories, files, records, trash,
    characters: entityView("character"),
    monsters: entityView("monster"),
  };
})();
