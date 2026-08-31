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
  } else {
    wlEl.innerHTML = watch
      .map((w) => {
        const s = byCode[w.code] || {};
        const c = s.changePct;
        const n = s.buySignals ? s.buySignals.length : 0;
        return `<div class="card stock">
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
