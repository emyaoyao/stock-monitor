// 买点监控 PWA · 前端逻辑
// 数据走同域 ./outputs/*.json（无 token 也能看）；增删可选填 GitHub Token 走 API。
const REPO = "emyaoyao/stock-monitor";
const API = "https://api.github.com";
const REFRESH_MS = 60 * 1000;   // 数据自动刷新间隔（60 秒）：新加股票约 2 分钟出云端信号后即自动出现

let token = localStorage.getItem("bm_token") || "";
// 多设备共享可选走云函数代理：地址 + 自设口令（不填就用上面的令牌直连 GitHub）
let proxy = localStorage.getItem("bm_proxy") || "";
let appKey = localStorage.getItem("bm_key") || "";
const $ = (s) => document.querySelector(s);

// 个股追踪：当前选中股票 / 周期 / 最近一次清单与信号（供点击切换复用）
let selectedCode = "";
let curTf = "day";
let lastWatch = [];
let lastSummaries = [];

// 同步链接支持：打开 #t=<令牌> 的链接即自动完成配置，随后把令牌从地址栏抹掉，
// 避免它留在浏览器历史或被误复制出去。
(function restoreFromHash() {
  const m = location.hash.match(/[#&]t=([^&]+)/);
  if (!m) return;
  try {
    const t = decodeURIComponent(m[1]);
    if (t) { token = t; localStorage.setItem("bm_token", token); }
  } catch { /* 忽略畸形链接 */ }
  history.replaceState(null, "", location.pathname + location.search);
})();

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("show"), 2600);
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function pctClass(p) {
  if (p == null) return "flat";
  if (p > 0) return "up";
  if (p < 0) return "down";
  return "flat";
}
function fmtPct(p) {
  if (p == null) return "";
  return (p > 0 ? "+" : "") + Number(p).toFixed(2) + "%";
}
function signalClass(label) {
  if (!label) return "";
  if (label.includes("卖出")) return "sell";
  if (label.includes("买入") || label.includes("入场")) return "buy";
  return "";
}
function b64enc(str) {
  const b = new TextEncoder().encode(str);
  let bin = "";
  b.forEach((x) => (bin += String.fromCharCode(x)));
  return btoa(bin);
}
function b64dec(b64) {
  const bin = atob(b64.replace(/\s/g, ""));
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

async function loadJSON(path) {
  try {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

async function loadAll() {
  // 有令牌时优先走 GitHub API 读清单：别的设备改了立刻能看到，
  // 不必等 Pages 上的静态文件被 Actions 重新生成。失败则回退到静态文件。
  let wl = null;
  if (token && !proxy) {
    try { wl = (await getWatchlist()).list; } catch { wl = null; }
  }
  if (wl === null) wl = await loadJSON("./outputs/watchlist.json");
  const res = await loadJSON("./outputs/monitor_result.json");
  render(wl, res);
}

function render(wl, res) {
  const watch = Array.isArray(wl) ? wl : [];
  const summaries = (res && res.summaries) || [];
  lastWatch = watch; lastSummaries = summaries;
  if (!watch.some((w) => w.code === selectedCode)) selectedCode = watch.length ? watch[0].code : "";
  const byCode = {};
  for (const s of summaries) byCode[s.code] = s;

  $("#meta").textContent = res && res.generatedAt ? "更新 " + res.generatedAt.slice(5) : "无数据";

  const banner = $("#banner");
  if (!res) {
    banner.classList.add("show");
    banner.innerHTML =
      "尚未生成信号数据。<b>激活监控</b>后即可自动刷新：给 token 加 workflow 权限，或把 deploy/monitor.yml 移到 .github/workflows/。";
  } else {
    banner.classList.remove("show");
  }

  const wlEl = $("#watchlist");
  if (!watch.length) {
    wlEl.innerHTML = '<div class="empty">清单为空，在上方添加代码</div>';
    const dn = $("#detailName"); if (dn) dn.textContent = "—";
    const dp = $("#detailPrice"); if (dp) dp.textContent = "";
    const vd = $("#verdict"); if (vd) vd.innerHTML = '<div class="muted">添加股票后，点它即可看 K 线与判断</div>';
  } else {
    wlEl.innerHTML = watch
      .map((w) => {
        const s = byCode[w.code] || {};
        const c = s.changePct;
        const n = s.buySignals ? s.buySignals.length : 0;
        const sel = w.code === selectedCode ? " selected" : "";
        return `<div class="card stock${sel}" data-code="${esc(w.code)}">
          <div><div class="name">${esc(w.name || w.code)}</div><div class="code">${esc(w.code)}</div></div>
          <div class="px">
            <div class="last ${pctClass(c)}">${s.price != null ? s.price : "—"}</div>
            <div class="chg ${pctClass(c)}">${fmtPct(c)}</div>
          </div>
          ${n ? `<span class="badge up">${n} 买点</span>` : ""}
          <button class="x" data-rm="${esc(w.code)}" title="移除">×</button>
        </div>`;
      })
      .join("");
    wlEl.querySelectorAll("[data-rm]").forEach((b) =>
      b.addEventListener("click", () => removeStock(b.getAttribute("data-rm")))
    );
    // 点股票卡片 → 打开该股 K 线追踪（点哪只看哪只，与电脑端一致）
    wlEl.querySelectorAll(".stock").forEach((card) => {
      const code = card.getAttribute("data-code");
      card.addEventListener("click", (e) => {
        if (e.target.closest("[data-rm]")) return;   // 点删除按钮不触发切换
        selectStock(code);
      });
    });
    // 保持选中并刷新该股 K 线（每 60s 自动刷新一次）
    selectStock(selectedCode);
  }

  const sigEl = $("#signals");
  // 旧版产物里 summaries 没有 name 字段，用监控清单兜一层，信号卡片才不会只剩代码
  const wlName = {};
  for (const w of watch) if (w.code && w.name) wlName[w.code] = w.name;
  const all = [];
  for (const s of summaries) {
    const nm = s.name || wlName[s.code] || "";
    for (const g of s.buySignals || []) all.push({ ...g, code: s.code, name: nm, price: s.price });
  }
  if (!all.length) {
    sigEl.innerHTML = '<div class="empty">当前无买点信号</div>';
  } else {
    sigEl.innerHTML = all
      .map((g) => {
        const cls = signalClass(g.label);
        const vc = cls === "sell" ? "down" : cls === "buy" ? "up" : "";
        return `<div class="card signal ${cls}">
          <div class="row1">
            <span class="nm">${esc(g.name || g.code)}</span>
            <span class="md">${esc(g.model || "")}</span>
            <span class="tf">${esc(g.tf || "")}</span>
            <span class="verdict ${vc}">${esc(g.label || "")}</span>
          </div>
          <div class="why">${esc(g.why || "")}</div>
        </div>`;
      })
      .join("");
  }

  $("#addHint").textContent = proxy
    ? "代理模式：添加直接在 APP 内生效，多设备共用同一清单"
    : token
      ? "共享模式：添加即写入云端清单，所有设备同步（约 2 分钟后出信号）"
      : "未配置：点击添加会跳到 GitHub Actions 网页操作";
}

// ---------- GitHub API（可选，应用内增删） ----------
function ghHeaders() {
  return {
    Authorization: "Bearer " + token,
    Accept: "application/vnd.github+json",
    "User-Agent": "bm-pwa",
    "Content-Type": "application/json",
  };
}
// 把 GitHub 的错误响应翻译成人话。403 有好几种成因（令牌没写权限、分支保护、
// 仓库不在授权范围），只抛一个状态码没法定位，所以连同响应体一起解析。
async function ghErr(r, what) {
  let msg = "";
  try {
    const j = await r.json();
    msg = j.message || "";
  } catch { /* 响应体不是 JSON，忽略 */ }
  if (r.status === 401) return new Error(`令牌无效或已过期（401）。请重新生成令牌${msg ? "：" + msg : ""}`);
  if (r.status === 403) {
    if (msg.includes("Resource not accessible by personal access token"))
      return new Error("令牌没有写权限（403）。请把令牌的 Contents 设为 Read and write，并确认仓库勾的是 stock-monitor");
    if (msg.includes("rate limit")) return new Error("触发 GitHub 限流（403），请稍后再试");
    if (msg.includes("protected") || msg.includes("branch"))
      return new Error(`分支保护拦截（403）：${msg}。请在仓库 Settings → Branches 放开 main 的写入`);
    return new Error(`${what}被拒（403）${msg ? "：" + msg : ""}`);
  }
  if (r.status === 404) return new Error(`${what}失败（404）：仓库或文件不存在，检查令牌授权的仓库是否为 ${REPO}`);
  if (r.status === 409) return new Error(`${what}冲突（409）：清单刚被别的设备改过，请刷新后重试`);
  return new Error(`${what}失败 ${r.status}${msg ? "：" + msg : ""}`);
}
async function getWatchlist() {
  const r = await fetch(`${API}/repos/${REPO}/contents/outputs/watchlist.json`, { headers: ghHeaders() });
  if (!r.ok) throw await ghErr(r, "读取清单");
  const j = await r.json();
  return { sha: j.sha, list: JSON.parse(b64dec(j.content)) };
}
async function putWatchlist(sha, list) {
  const body = {
    message: "chore(monitor): update watchlist via PWA",
    content: b64enc(JSON.stringify(list, null, 1)),
    sha,
  };
  const r = await fetch(`${API}/repos/${REPO}/contents/outputs/watchlist.json`, {
    method: "PUT",
    headers: ghHeaders(),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw await ghErr(r, "写入清单");
}
async function dispatch(payload) {
  const r = await fetch(`${API}/repos/${REPO}/actions/workflows/monitor.yml/dispatches`, {
    method: "POST",
    headers: ghHeaders(),
    body: JSON.stringify({ ref: "main", inputs: payload }),
  });
  if (!r.ok && r.status !== 204) throw await ghErr(r, "触发扫描");
}

// ---------- 令牌自检 ----------
// GET /repos/{repo} 会带回 permissions.push / pull，这是判断令牌有没有写权限最干净的
// 办法——零副作用，不用真的去写文件。配合分支保护状态，能覆盖 403 的绝大多数成因。
async function diagnose() {
  const out = [];
  const add = (ok, text) => out.push({ ok, text });
  if (!token) { add(false, "还没有填令牌"); return out; }

  add(true, "令牌格式：" + (token.startsWith("github_pat_")
    ? "fine-grained（细粒度，推荐）"
    : token.startsWith("ghp_") ? "classic（经典）"
    : "未识别前缀，请确认复制完整"));

  let r = await fetch(`${API}/user`, { headers: ghHeaders() });
  if (!r.ok) {
    add(false, `身份验证失败 ${r.status}：令牌无效或已过期，请重新生成`);
    return out;
  }
  const me = await r.json();
  add(true, `身份：${me.login}`);
  const scopes = r.headers.get("X-OAuth-Scopes");
  add(true, scopes ? `授权范围：${scopes}` : "授权范围：细粒度令牌（按仓库授权，无 scope 概念）");

  r = await fetch(`${API}/repos/${REPO}`, { headers: ghHeaders() });
  if (!r.ok) {
    add(false, `看不到仓库 ${REPO}（${r.status}）：令牌授权的仓库不对，请确认勾的是 stock-monitor`);
    return out;
  }
  const repo = await r.json();
  const perm = repo.permissions || {};
  add(perm.pull === true, `读权限（pull）：${perm.pull ? "有" : "无"}`);
  add(perm.push === true, `写权限（push）：${perm.push ? "有" : "无 ← 这就是 403 的原因"}`);
  if (!perm.push) {
    add(false, "修复：进令牌设置页把 Contents 改成 Read and write，仓库选 stock-monitor");
    return out;
  }

  r = await fetch(`${API}/repos/${REPO}/branches/main`, { headers: ghHeaders() });
  if (r.ok) {
    const br = await r.json();
    if (br.protected) {
      add(false, "main 分支开启了保护规则 —— 即使令牌有写权限，API 写文件也会被 403 拦下");
      add(false, "修复：仓库 Settings → Branches → 编辑 main 规则，取消对 push 的限制（或把令牌加入例外名单）");
    } else {
      add(true, "分支保护：未开启，可以正常写入");
    }
  }

  r = await fetch(`${API}/repos/${REPO}/contents/outputs/watchlist.json`, { headers: ghHeaders() });
  if (r.ok) {
    const j = await r.json();
    const list = JSON.parse(b64dec(j.content));
    add(true, `清单读取正常，当前 ${list.length} 条`);
  } else {
    add(false, "清单读取失败 " + r.status);
  }
  return out;
}
function openActions() {
  window.open(`https://github.com/${REPO}/actions`, "_blank", "noopener");
  toast("已打开 GitHub Actions，填代码后 Run workflow");
}
// 多设备共享模式：走 Worker 代理（服务端持有 GitHub Token，手机端只带口令）
async function proxyCall(payload) {
  const r = await fetch(proxy, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-App-Key": appKey },
    body: JSON.stringify(payload),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.msg || ("请求失败 " + r.status));
  return j;
}

// ---------- 股票名称自动识别 ----------
// 腾讯快照接口返回的是 GBK 编码（不是 UTF-8），直接当文本读会拿到乱码，
// 必须走 arrayBuffer + TextDecoder('gbk')。该接口带 CORS:*，浏览器可直连。
function txCode(code) {
  if (/^6/.test(code)) return "sh" + code;      // 沪市（含 688 科创板）
  if (/^(0|3)/.test(code)) return "sz" + code;  // 深市（含 300 创业板）
  if (/^(4|8)/.test(code)) return "bj" + code;  // 北交所
  return "sh" + code;
}
async function lookupName(code) {
  const r = await fetch(`https://qt.gtimg.cn/q=${txCode(code)}`);
  if (!r.ok) throw new Error("查询失败 " + r.status);
  const txt = new TextDecoder("gbk").decode(await r.arrayBuffer());
  // 返回形如：v_sh600519="1~贵州茅台~600519~1297.40~...";
  // 先切出引号内的整体再按 ~ 分段，第 [1] 段才是名称。
  // 注意：不能用 /="...~([^~]+)~/ 这类正则——[^"]* 贪婪匹配会回溯到末尾字段，取到涨跌幅之类的数字。
  const seg = txt.split('="')[1];
  if (!seg) return "";
  const parts = seg.split('"')[0].split("~");
  return parts.length > 1 ? parts[1].trim() : "";
}
// 输入满 6 位就自动补名称，省得手打
let _lookupSeq = 0;
async function autoFillName() {
  const code = ($("#addCode").value || "").trim();
  const nameEl = $("#addName"), hintEl = $("#lookupHint");
  if (!/^\d{6}$/.test(code)) { hintEl.hidden = true; return; }
  if ((nameEl.value || "").trim()) { hintEl.hidden = true; return; } // 用户已手填就不抢
  const seq = ++_lookupSeq;                       // 防止快速输入时旧请求覆盖新结果
  hintEl.textContent = "识别中…"; hintEl.hidden = false;
  try {
    const name = await lookupName(code);
    if (seq !== _lookupSeq) return;
    if (name) {
      nameEl.value = name;
      hintEl.textContent = "✓ 已识别：" + name;
      setTimeout(() => { hintEl.hidden = true; }, 2500);
    } else {
      hintEl.textContent = "未识别到该代码，可手动填名称";
    }
  } catch {
    if (seq === _lookupSeq) { hintEl.textContent = "名称识别失败（不影响添加）"; }
  }
}

async function addStock(code, name) {
  code = (code || "").trim();
  if (!/^\d{6}$/.test(code)) { toast("代码需为 6 位数字"); return; }
  // 名称留空时先补一次，保证写进清单的每条都有名字
  if (!(name || "").trim()) {
    try { name = await lookupName(code); } catch { name = ""; }
  }
  if (proxy) {
    try {
      const j = await proxyCall({ action: "add", code, name: (name || "").trim() });
      toast(j.msg || "已添加，云端扫描约 2 分钟后出信号");
      setTimeout(loadAll, 1500);
      setTimeout(loadAll, 120000);
    } catch (e) { toast(e.message || "添加失败"); }
    return;
  }
  // 未设置令牌时不再跳 GitHub：只提示并展开设置面板，避免误点到外链
  if (!token) {
    toast("未设置 GitHub Token。请在「多设备共享」里填入令牌（Contents 读写）后再操作");
    const ds = document.querySelector("details.settings"); if (ds) ds.open = true;
    const ti = $("#tokenInput"); if (ti && ti.scrollIntoView) ti.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  try {
    const { sha, list } = await getWatchlist();
    if (list.some((w) => w.code === code)) { toast(code + " 已在清单"); return; }
    list.push({ code, name: (name || "").trim() });
    await putWatchlist(sha, list);
    await dispatch({ mode: "run", add_code: code, add_name: (name || "").trim() });
    toast("已添加，云端扫描约 2 分钟后出信号");
    setTimeout(loadAll, 1500);    // 先刷出清单里的新票
    setTimeout(loadAll, 120000);  // 云端 Actions 跑完约 2 分钟，之后自动刷出信号
  } catch (e) {
    toast(e.message || "添加失败");
  }
}
async function removeStock(code) {
  code = (code || "").trim();
  if (proxy) {
    try {
      const j = await proxyCall({ action: "remove", code });
      toast(j.msg || "已移除，云端更新中…");
      setTimeout(loadAll, 1500);
      setTimeout(loadAll, 120000);
    } catch (e) { toast(e.message || "移除失败"); }
    return;
  }
  // 未设置令牌时不再跳 GitHub：只提示并展开设置面板，避免误点到外链
  if (!token) {
    toast("未设置 GitHub Token。请在「多设备共享」里填入令牌（Contents 读写）后再操作");
    const ds = document.querySelector("details.settings"); if (ds) ds.open = true;
    const ti = $("#tokenInput"); if (ti && ti.scrollIntoView) ti.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  try {
    const { sha, list } = await getWatchlist();
    const next = list.filter((w) => w.code !== code);
    if (next.length === list.length) { toast(code + " 不在清单"); return; }
    await putWatchlist(sha, next);
    await dispatch({ mode: "run", remove_code: code });
    toast("已移除，云端更新中…");
    setTimeout(loadAll, 1500);
    setTimeout(loadAll, 120000);
  } catch (e) {
    toast(e.message || "移除失败");
  }
}

// ---------- 事件 ----------
$("#refresh").addEventListener("click", loadAll);
$("#addBtn").addEventListener("click", () => addStock($("#addCode").value, $("#addName").value));
// 输满 6 位自动识别名称（防抖 400ms，避免边打字边发请求）
let _fillT;
$("#addCode").addEventListener("input", () => {
  clearTimeout(_fillT);
  _fillT = setTimeout(autoFillName, 400);
});
$("#addCode").addEventListener("blur", autoFillName);
$("#addCode").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter") return;
  if (!/^\d{6}$/.test(($("#addCode").value || "").trim())) { $("#addName").focus(); return; }
  if (!($("#addName").value || "").trim()) await autoFillName();  // 回车时补一次再跳焦点
  $("#addName").focus();
});
$("#addName").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#addBtn").click(); });
$("#saveToken").addEventListener("click", () => {
  token = $("#tokenInput").value.trim();
  if (token) { localStorage.setItem("bm_token", token); toast("Token 已保存"); }
  loadAll();
});
$("#clearToken").addEventListener("click", () => {
  token = ""; localStorage.removeItem("bm_token"); $("#tokenInput").value = "";
  $("#linkBox").hidden = true; $("#diagBox").hidden = true;
  toast("已清除令牌"); loadAll();
});
function renderDiag(items) {
  const box = $("#diagBox");
  box.innerHTML = items.map((i) =>
    `<div style="margin:4px 0;color:${i.ok ? "var(--ok,#3fb950)" : "var(--bad,#f85149)"}">` +
    `${i.ok ? "✓" : "✗"} ${esc(i.text)}</div>`).join("");
  box.hidden = false;
}
$("#checkToken").addEventListener("click", async () => {
  const t = ($("#tokenInput").value || "").trim();
  if (t) { token = t; localStorage.setItem("bm_token", token); }
  if (!token) { toast("请先粘贴令牌"); return; }
  renderDiag([{ ok: true, text: "正在自检…" }]);
  try {
    renderDiag(await diagnose());
  } catch (e) {
    renderDiag([{ ok: false, text: "自检失败：" + (e.message || e) }]);
  }
  loadAll();
});
// 生成同步链接：把令牌编进 URL hash，另一台设备打开即自动配置
$("#genLink").addEventListener("click", () => {
  const t = ($("#tokenInput").value || "").trim() || token;
  if (!t) { toast("请先粘贴并保存令牌"); return; }
  token = t; localStorage.setItem("bm_token", token);
  $("#linkInput").value = location.href.split("#")[0] + "#t=" + encodeURIComponent(t);
  $("#linkBox").hidden = false;
  loadAll();
});
$("#copyLink").addEventListener("click", async () => {
  const inp = $("#linkInput");
  try {
    await navigator.clipboard.writeText(inp.value);
    toast("已复制，在另一台设备打开即可");
  } catch {
    inp.removeAttribute("readonly"); inp.select();
    document.execCommand("copy"); inp.setAttribute("readonly", "");
    toast("已复制");
  }
});
$("#hideLink").addEventListener("click", () => { $("#linkBox").hidden = true; });
$("#saveProxy").addEventListener("click", () => {
  proxy = ($("#proxyInput").value || "").trim().replace(/\/+$/, "");
  appKey = ($("#keyInput").value || "").trim();
  if (proxy) localStorage.setItem("bm_proxy", proxy); else localStorage.removeItem("bm_proxy");
  if (appKey) localStorage.setItem("bm_key", appKey); else localStorage.removeItem("bm_key");
  toast(proxy ? "共享代理已保存（多设备填同样两个值）" : "已清除代理配置");
  loadAll();
});
$("#clearProxy").addEventListener("click", () => {
  proxy = ""; appKey = "";
  localStorage.removeItem("bm_proxy"); localStorage.removeItem("bm_key");
  $("#proxyInput").value = ""; $("#keyInput").value = "";
  toast("已清除共享代理"); loadAll();
});
if (token) $("#tokenInput").value = token;
if (proxy) $("#proxyInput").value = proxy;
if (appKey) $("#keyInput").value = appKey;

let deferred = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferred = e;
  const b = $("#banner");
  b.classList.add("show");
  b.innerHTML = '可<b>安装到主屏幕</b>：点浏览器菜单「添加到主屏幕」即可像 App 一样打开。';
});

if ("serviceWorker" in navigator) {
  // 注册并主动检查更新：应对旧 SW 卡住、一直喂缓存旧数据（如旧 monitor_result.json 仍含已删股票）的情况
  window.addEventListener("load", async () => {
    try {
      const reg = await navigator.serviceWorker.register("./sw.js");
      setInterval(() => { try { reg.update(); } catch (e) {} }, 60000);   // 每分钟探测一次新版本
      reg.addEventListener("updatefound", () => {
        const nw = reg.installing;
        if (!nw) return;
        nw.addEventListener("statechange", () => {
          // 已有旧 SW 在控，新版本装好就立即重载应用，用户无需手动刷新
          if (nw.state === "installed" && navigator.serviceWorker.controller) location.reload();
        });
      });
    } catch (e) { /* SW 不可用不影响基础功能 */ }
  });
  // 新版 SW 接管时自动重载，确保马上拿到新逻辑/新数据策略
  navigator.serviceWorker.addEventListener("controllerchange", () => location.reload());
}

loadAll();
setInterval(loadAll, REFRESH_MS);
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadAll(); });

// ---------- 个股追踪：K 线 + 基于 K 线的事实判断（移植自电脑端监控页） ----------
// 腾讯 K 线接口带 CORS:*，手机端跨域直连无压力
async function txKline(code, period, count) {
  const tx = txCode(code);
  const url = period === "day"
    ? `https://ifzq.gtimg.cn/appstock/app/fqkline/get?param=${tx},day,,,${count},qfq`
    : `https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=${tx},${period},,${count}`;
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error("K线请求失败 " + r.status);
  const j = await r.json();
  const d = (j.data || {})[tx] || {};
  const arr = d[period === "day" ? "qfqday" : period] || d.day || [];
  // 腾讯每段 [日期,开,收,高,低,量] —— 第 3 位是收盘价不是最高价
  return arr.map((x) => ({ t: x[0], o: +x[1], c: +x[2], h: +x[3], l: +x[4], v: +x[5] }))
    .filter((b) => isFinite(b.c) && b.c > 0);
}
function maSeries(bars, n) {
  const out = new Array(bars.length).fill(null); let s = 0;
  for (let i = 0; i < bars.length; i++) { s += bars[i].c; if (i >= n) s -= bars[i - n].c; if (i >= n - 1) out[i] = s / n; }
  return out;
}
function fmtBarTime(t) {
  if (/^\d{12}$/.test(t)) return `${t.slice(4, 6)}-${t.slice(6, 8)} ${t.slice(8, 10)}:${t.slice(10, 12)}`;
  if (/^\d{8}$/.test(t)) return `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)}`;
  return t || "";
}
function parseBarDate(t) {
  const m = /^(\d{4})(\d{2})(\d{2})/.exec(String(t || "").replace(/\D/g, ""));
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(0);
}
// 纯 canvas 蜡烛图（涨红跌绿，A股习惯），手机端自适应宽度
function drawKline(cv, bars, maN) {
  maN = maN === undefined ? 20 : maN;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 360, H = 240;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  if (!bars.length) { g.fillStyle = "#6b7a99"; g.font = "14px sans-serif"; g.fillText("暂无数据", 20, H / 2); return; }
  const PL = 8, PR = 58, PT = 12, PB = 24, cw = W - PL - PR, ch = H - PT - PB;
  let hi = -Infinity, lo = Infinity;
  bars.forEach((b) => { if (b.h > hi) hi = b.h; if (b.l < lo) lo = b.l; });
  const ma = (maN > 0 && bars.length >= maN) ? maSeries(bars, maN) : null;
  if (ma) ma.forEach((v) => { if (v != null) { if (v > hi) hi = v; if (v < lo) lo = v; } });
  const pad = (hi - lo) * 0.06 || hi * 0.01 || 1; hi += pad; lo -= pad;
  const X = (i) => PL + (bars.length < 2 ? cw / 2 : (i / (bars.length - 1)) * cw);
  const Y = (p) => PT + ch - ((p - lo) / (hi - lo)) * ch;
  g.strokeStyle = "rgba(120,160,255,.10)"; g.lineWidth = 1; g.font = "10px ui-monospace,monospace"; g.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) { const y = PT + (ch / 4) * i, v = hi - ((hi - lo) / 4) * i;
    g.beginPath(); g.moveTo(PL, y); g.lineTo(PL + cw, y); g.stroke();
    g.fillStyle = "#6b7a99"; g.fillText(v.toFixed(2), PL + cw + 4, y); }
  const bw = Math.max(1.4, Math.min(8, cw / bars.length * 0.66));
  bars.forEach((b, i) => { const x = X(i), up = b.c >= b.o, col = up ? "#ff4d4f" : "#16c784";
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1;
    g.beginPath(); g.moveTo(Math.round(x) + .5, Y(b.h)); g.lineTo(Math.round(x) + .5, Y(b.l)); g.stroke();
    const yo = Y(b.o), yc = Y(b.c), top = Math.min(yo, yc), hgt = Math.max(1, Math.abs(yc - yo));
    if (up) g.fillRect(x - bw / 2, top, bw, hgt); else g.strokeRect(x - bw / 2, top, bw, hgt); });
  if (ma) {
    g.strokeStyle = "#fbbf24"; g.lineWidth = 1.6; g.beginPath(); let started = false;
    ma.forEach((v, i) => { if (v == null) return; const x = X(i), y = Y(v); if (!started) { g.moveTo(x, y); started = true; } else g.lineTo(x, y); });
    g.stroke();
    const lv = ma[bars.length - 1];
    if (lv != null) { const ly = Math.min(Math.max(Y(lv), PT + 4), PT + ch - 4);
      g.fillStyle = "#fbbf24"; g.font = "10px ui-monospace,monospace"; g.textBaseline = "middle"; g.textAlign = "left";
      g.fillText("MA" + maN + " " + lv.toFixed(2), PL + 4, ly - 8); }
  }
  g.fillStyle = "#6b7a99"; g.textBaseline = "top";
  [0, Math.floor(bars.length / 2), bars.length - 1].forEach((i) => { const t = fmtBarTime(bars[i].t), x = X(i);
    g.textAlign = i === 0 ? "left" : (i === bars.length - 1 ? "right" : "center");
    g.fillText(t, Math.min(Math.max(x, PL + 2), PL + cw - 2), PT + ch + 6); });
  g.textAlign = "left";
}
// 基于 K 线的快速事实判断（与电脑端同算法）：趋势 / EMA20 / 末根 / 量能 / 结论
function renderVerdict(bars, code, name) {
  const el = $("#verdict"); if (!el) return;
  if (!bars || !bars.length) { el.innerHTML = '<div class="muted">暂无 K 线数据</div>'; return; }
  const N = Math.min(20, bars.length);
  const recent = bars.slice(-N);
  let up = true, down = true;
  for (let i = 1; i < recent.length; i++) { if (recent[i].h <= recent[i - 1].h) up = false; if (recent[i].l <= recent[i - 1].l) down = false; }
  const trendTxt = (up && down) ? "多头（HH+HL）" : (!up && !down) ? "空头（LH+LL）" : "震荡";
  const k = Math.min(20, bars.length);
  const win = bars.slice(-k); let ema = win[0].c; const a = 2 / (k + 1);
  win.forEach((b) => ema = a * b.c + (1 - a) * ema);
  const last = bars[bars.length - 1];
  const above = last.c >= ema;
  const rng = (last.h - last.l) || 1, bodyR = last.c - last.o;
  const upBar = last.c >= last.o;
  const lowerWick = (last.o - last.l) / rng, upperWick = (last.h - last.o) / rng;
  const bullRev = upBar && lowerWick > 0.5 && Math.abs(bodyR) / rng < 0.4;
  const vols = bars.slice(-20).map((b) => b.v || 0);
  const avgV = vols.reduce((s, v) => s + v, 0) / (vols.length || 1);
  const volUp = last.v > avgV * 1.2;
  let verdict, cls;
  if (above && upBar && up) { verdict = "关注/可买入：价格在均线上方、结构偏多、末根走强"; cls = "v-buy"; }
  else if (above) { verdict = "关注：价格在均线上方，但结构尚不清晰"; cls = "v-watch"; }
  else if (!above && down) { verdict = "观望：价格在均线下方、结构偏空"; cls = "v-wait"; }
  else { verdict = "观望：方向不明，等结构清晰"; cls = "v-wait"; }
  el.innerHTML = `<div class="verdict ${cls}">${esc(verdict)}</div>
    <div class="kv"><b>标的</b>${esc(name || "")} ${esc(code)}</div>
    <div class="kv"><b>趋势(近${N}根)</b>${esc(trendTxt)}</div>
    <div class="kv"><b>EMA20</b>收盘 ${above ? "在均线上方 ▲" : "在均线下方 ▼"}（EMA≈${ema.toFixed(2)}）</div>
    <div class="kv"><b>末根</b>${upBar ? "阳线" : "阴线"}　下影占比 ${Math.round(lowerWick * 100)}%　${bullRev ? "⚠ 长下影，疑似看涨反转" : ""}</div>
    <div class="kv"><b>量能</b>${volUp ? "放量" : "平量/缩量"}（末根 ${((last.v || 0) / 10000).toFixed(1)}万手 vs 均 ${((avgV || 0) / 10000).toFixed(1)}万手）</div>
    <div class="src">以上为基于 K 线本身的快速判断，仅供参考；完整模型结论见上方「买点信号」。若 K 线出现异常（缺口/停牌/复权错位），以你目视为准。</div>`;
}
async function selectStock(code) {
  selectedCode = code;
  document.querySelectorAll("#watchlist .stock").forEach((c) =>
    c.classList.toggle("selected", c.getAttribute("data-code") === code));
  const name = $("#detailName"), price = $("#detailPrice");
  const s = (lastSummaries || []).find((x) => x.code === code) || {};
  const w = (lastWatch || []).find((x) => x.code === code) || {};
  const nm = s.name || w.name || code;
  if (name) name.textContent = nm + "  " + code;
  if (price) { const c = s.changePct;
    price.innerHTML = s.price != null ? `<span class="${pctClass(c)}">${s.price} ${fmtPct(c)}</span>` : ""; }
  await drawDetail(nm || code);
}
async function drawDetail(nm) {
  const cv = $("#kline"), meta = $("#klineMeta");
  if (meta) meta.textContent = "K线加载中…";
  try {
    const n = curTf === "day" ? 240 : 320;
    const bars = await txKline(selectedCode, curTf, n);
    drawKline(cv, bars, 20);
    renderVerdict(bars, selectedCode, nm);
    if (meta) {
      const last = bars[bars.length - 1];
      let ago = "";
      if (last) { const mins = Math.round((Date.now() - parseBarDate(last.t).getTime()) / 60000);
        ago = mins < 0 ? "时间晚于本机" : mins < 5 ? "刚刚" : mins < 60 ? mins + " 分钟前" : mins < 1440 ? Math.floor(mins / 60) + " 小时前" : Math.floor(mins / 1440) + " 天前"; }
      meta.textContent = `共 ${bars.length} 根 · 末根 ${fmtBarTime(last ? last.t : "")} · ${ago}`;
    }
  } catch (e) { if (meta) meta.textContent = "K线加载失败：" + (e.message || e); }
}
// 周期切换（日 / 60 / 30 / 15 分）
$("#tfTabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tf]"); if (!b) return;
  document.querySelectorAll("#tfTabs button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on");
  curTf = b.getAttribute("data-tf");
  if (selectedCode) drawDetail((lastSummaries.find((x) => x.code === selectedCode) || {}).name || selectedCode);
});
