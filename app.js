// 买点监控 PWA · 前端逻辑
// 数据走同域 ./outputs/*.json（无 token 也能看）；增删可选填 GitHub Token 走 API。
const REPO = "emyaoyao/stock-monitor";
const API = "https://api.github.com";
const REFRESH_MS = 5 * 60 * 1000;

let token = localStorage.getItem("bm_token") || "";
const $ = (s) => document.querySelector(s);

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
  const wl = await loadJSON("./outputs/watchlist.json");
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
  const all = [];
  for (const s of summaries) for (const g of s.buySignals || []) all.push({ ...g, name: s.name, price: s.price });
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

  $("#addHint").textContent = token
    ? "已填 Token：添加后自动触发云端扫描"
    : "未填 Token：点击添加会跳到 GitHub Actions 网页操作";
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
async function getWatchlist() {
  const r = await fetch(`${API}/repos/${REPO}/contents/outputs/watchlist.json`, { headers: ghHeaders() });
  if (!r.ok) throw new Error("读取清单失败 " + r.status);
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
  if (!r.ok) throw new Error("写入清单失败 " + r.status);
}
async function dispatch(payload) {
  const r = await fetch(`${API}/repos/${REPO}/actions/workflows/monitor.yml/dispatches`, {
    method: "POST",
    headers: ghHeaders(),
    body: JSON.stringify({ ref: "main", inputs: payload }),
  });
  if (!r.ok && r.status !== 204) throw new Error("触发扫描失败 " + r.status);
}
function openActions() {
  window.open(`https://github.com/${REPO}/actions`, "_blank", "noopener");
  toast("已打开 GitHub Actions，填代码后 Run workflow");
}
async function addStock(code, name) {
  code = (code || "").trim();
  if (!/^\d{6}$/.test(code)) { toast("代码需为 6 位数字"); return; }
  if (!token) { openActions(); return; }
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
  if (!token) { openActions(); return; }
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
$("#addCode").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#addName").focus(); });
$("#addName").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#addBtn").click(); });
$("#saveToken").addEventListener("click", () => {
  token = $("#tokenInput").value.trim();
  if (token) { localStorage.setItem("bm_token", token); toast("Token 已保存"); }
  loadAll();
});
$("#clearToken").addEventListener("click", () => {
  token = ""; localStorage.removeItem("bm_token"); $("#tokenInput").value = "";
  toast("已清除 Token"); loadAll();
});
if (token) $("#tokenInput").value = token;

let deferred = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferred = e;
  const b = $("#banner");
  b.classList.add("show");
  b.innerHTML = '可<b>安装到主屏幕</b>：点浏览器菜单「添加到主屏幕」即可像 App 一样打开。';
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch(() => {}));
}

loadAll();
setInterval(loadAll, REFRESH_MS);
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadAll(); });
