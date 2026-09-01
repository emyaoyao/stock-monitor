"""统一行情客户端：日线走同花顺，分钟线走智兔，腾讯做最后兜底。

单位口径（踩过一次坑）：
  同花顺 volume 单位是「股」，智兔 v 单位是「手」。不统一的话
  `V>MA(V,20)*1.5` 这类放量条件在两个源上结论完全相反。这里统一成「股」。

降级链（2026-09-01 加的第三级）：
  日线   同花顺（有 API_KEY）→ 智兔日线 → 腾讯前复权日线
  分钟线 智兔（唯一有授权的）  → 腾讯分钟线
  加腾讯是因为分钟线只有智兔一个源时，智兔一挂 60/30/15 分就整片「无数据」，
  而日线照常显示，看起来像页面坏了。腾讯免费公开，能兜住这个单点故障。

字段统一输出：{'t':[时间串], 'o':[], 'h':[], 'l':[], 'c':[], 'v':[]}
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from functools import lru_cache

UA = "Mozilla/5.0 (pa-workbench/1.0)"


def _ssl_ctx() -> ssl.SSLContext:
    """默认严格校验证书。

    原先这里全局关掉了校验（check_hostname=False + CERT_NONE），
    而请求里带着 API_KEY / ZHITU_TOKEN——一旦链路上有中间人，凭据和行情
    都会被同时拿走。实测三个数据源在严格模式下都能连通，所以收紧为默认严格。
    仅在个别环境证书链确实缺失时，用 PA_INSECURE_TLS=1 显式放开，
    把风险变成一件需要主动勾选的事。
    """
    ctx = ssl.create_default_context()
    if os.environ.get("PA_INSECURE_TLS", "").strip() in ("1", "true", "yes"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx

HITHINK_BASE = "https://fuyao.aicubes.cn"
ZHITU_BASE = "https://api.zhituapi.com"


class QuoteError(RuntimeError):
    pass


def _get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        return r.read().decode("utf-8", "replace")


def _key(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise QuoteError(f"环境变量 {name} 未设置")
    return v


# ------------------------------------------------------------------ 代码转换

@lru_cache(maxsize=512)
def _search_item(code: str) -> dict | None:
    """在同花顺检索接口里定位这只票，返回整条记录（含 thscode / 名称）。

    缓存是必需的：内部会发一次 HTTP 请求，而一只票在扫描流程里
    （hithink_daily + snapshot + 名称解析）至少被调三次，N 只票就是 3N 次
    多余往返。代码→交易所/名称的映射不会变，缓存没有时效问题。
    """
    try:
        url = f"{HITHINK_BASE}/api/meta/tickers/search?q={urllib.parse.quote(code)}&limit=5"
        d = json.loads(_get(url, {"X-api-key": _key("API_KEY")}))
        for it in ((d.get("data") or {}).get("item") or []):
            if str(it.get("ticker", "")).zfill(6) == code.zfill(6):
                return it
    except Exception:
        pass
    return None


@lru_cache(maxsize=512)
def to_thscode(code: str) -> str:
    """6 位代码 → 带交易所后缀。先用同花顺检索消歧，失败再按号段推断。"""
    code = code.strip()
    if "." in code:
        return code.upper()
    it = _search_item(code)
    if it and it.get("thscode"):
        return it["thscode"]
    c = code.zfill(6)
    if c[0] == "6" or c.startswith(("68", "9")):
        return f"{c}.SH"
    if c.startswith(("4", "8")):
        return f"{c}.BJ"
    return f"{c}.SZ"


@lru_cache(maxsize=512)
def stock_name(code: str) -> str:
    """6 位代码 → 股票中文名。查不到返回空串（让调用方自己决定兜底）。

    注意快照接口 snapshot() 只返回 ticker（就是代码本身），没有名称字段，
    名称必须走检索接口单独取——这是之前把 name 写成代码的原因。
    """
    code = code.strip()
    it = _search_item(plain_code(code))
    if not it:
        return ""
    for k in ("shortName", "name", "secName", "tickerName", "cnName"):
        v = it.get(k)
        if v:
            return str(v)
    return ""


def plain_code(code: str) -> str:
    """智兔用不带后缀的 6 位代码。"""
    return code.strip().split(".")[0].zfill(6)


# ------------------------------------------------------------------ 数据源

def hithink_daily(code: str, days: int = 400) -> list[dict] | None:
    """同花顺日线（前复权）。历史 K 线目前仅支持 1d。"""
    try:
        ths = to_thscode(code)
        end = int(time.time() * 1000)
        start = end - int(days * 1.6) * 86400 * 1000
        url = (f"{HITHINK_BASE}/api/a-share/prices/historical?thscode={ths}"
               f"&interval=1d&start={start}&end={end}&adjust=forward")
        d = json.loads(_get(url, {"X-api-key": _key("API_KEY")}))
        if d.get("code") != 0:
            return None
        items = (d.get("data") or {}).get("item") or []
        if not items:
            return None
        out = []
        for it in items:
            ms = it.get("date_ms")
            ts = time.strftime("%Y-%m-%d", time.localtime(ms / 1000)) if ms else ""
            out.append({
                "t": ts, "o": it.get("open_price"), "h": it.get("high_price"),
                "l": it.get("low_price"), "c": it.get("close_price"),
                "v": (it.get("volume") or 0),  # 股
            })
        return _clean(out)
    except Exception:
        return None


def zhitu_history(code: str, period: str, days: int = 120) -> list[dict] | None:
    """智兔历史 K 线。period: d / 60 / 30 / 15 / 5。

    分钟级没有除权数据，复权参数必须传 n；传 f 会返回「数据不存在」。
    """
    try:
        tok = _key("ZHITU_TOKEN")
        adj = "f" if period == "d" else "n"
        st = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
        et = date.today().strftime("%Y%m%d")
        url = (f"{ZHITU_BASE}/hs/history/{plain_code(code)}/{period}/{adj}"
               f"?token={urllib.parse.quote(tok)}&st={st}&et={et}")
        txt = _get(url).strip()
        if txt.startswith("{"):
            return None
        arr = json.loads(txt)
        if not isinstance(arr, list) or not arr:
            return None
        out = []
        for it in arr:
            out.append({
                "t": it.get("t"), "o": it.get("o"), "h": it.get("h"),
                "l": it.get("l"), "c": it.get("c"),
                "v": (it.get("v") or 0) * 100,  # 手 → 股
            })
        return _clean(out)
    except Exception:
        return None


def _txcode(code: str) -> str:
    """6 位代码 → 腾讯代码（sh/sz/bj 前缀）。腾讯的段格式与同花顺不同，单独一套。"""
    c = plain_code(code)
    if c.startswith(("60", "68", "9", "5", "11")):
        return "sh" + c
    if c.startswith(("4", "8")):
        return "bj" + c
    return "sz" + c


def _tx_time(t: str) -> str:
    """腾讯时间 → 与智兔一致的 'YYYY-MM-DD HH:MM:00'。日线只保留日期。"""
    s = str(t or "")
    d = "".join(ch for ch in s if ch.isdigit())
    if len(d) >= 12:
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]} {d[8:10]}:{d[10:12]}:00"
    if len(d) == 8:
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return s


TX_MIN_PERIOD = {"60": "m60", "30": "m30", "15": "m15", "5": "m5"}


def tencent_history(code: str, period: str, count: int = 640) -> list[dict] | None:
    """腾讯 K 线兜底（免费、无需 token）。period: d / 60 / 30 / 15 / 5。

    为什么要有它：分钟线原先只有智兔一个源，智兔一挂（token 过期 / 额度用尽 /
    接口调整），真实扫描里的 60分·30分·15分 就全部显示「无数据」，而日线因为
    有同花顺兜底照常工作——看起来像是页面坏了。腾讯这个是免费公开源，
    作为最后一级兜底，至少保证多周期扫描不会整片为空。

    段格式与智兔不同：[t, o, c, h, l, v]，第 3 位是**收盘价**不是最高价，
    v 单位是**手**（同花顺是股），这里统一成股。
    """
    try:
        tx = _txcode(code)
        n = max(60, min(int(count or 640), 640))  # 实测 >640 会被接口悄悄降回 320 根
        if period == "d":
            url = (f"https://ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?param={tx},day,,,{n},qfq")
            key = "qfqday"
        else:
            url = (f"https://ifzq.gtimg.cn/appstock/app/kline/mkline"
                   f"?param={tx},{TX_MIN_PERIOD.get(str(period), period)},,{n}")
            key = str(TX_MIN_PERIOD.get(str(period), period))
        d = json.loads(_get(url))
        arr = ((d.get("data") or {}).get(tx) or {}).get(key) or []
        if not arr:
            return None
        out = []
        for it in arr:
            if len(it) < 6:
                continue
            out.append({
                "t": _tx_time(it[0]), "o": it[1], "c": it[2], "h": it[3], "l": it[4],
                "v": float(it[5] or 0) * 100,  # 手 → 股
            })
        return _clean(out)
    except Exception:
        return None


def _clean(rows: list[dict]) -> list[dict]:
    """丢掉残缺行并按时间排序。数据源偶发返回 null，不处理会让后续计算崩掉。"""
    out = []
    for r in rows:
        if None in (r.get("o"), r.get("h"), r.get("l"), r.get("c")):
            continue
        if not r.get("t"):
            continue
        out.append({**r, "v": float(r.get("v") or 0)})
    out.sort(key=lambda x: x["t"])
    return out


def to_bars(rows: list[dict]) -> dict:
    return {
        "t": [r["t"] for r in rows],
        "o": [float(r["o"]) for r in rows],
        "h": [float(r["h"]) for r in rows],
        "l": [float(r["l"]) for r in rows],
        "c": [float(r["c"]) for r in rows],
        "v": [float(r["v"]) for r in rows],
    }


# ------------------------------------------------------------------ 对外接口

PERIODS = {
    "日线": "d",
    "60分": "60",
    "30分": "30",
    "15分": "15",
    "5分": "5",
}


def fetch(code: str, tf: str, days: int = 400) -> tuple[dict, str]:
    """取单个周期的 K 线，返回 (bars, 数据源名)。日线优先同花顺，失败转智兔。"""
    period = PERIODS.get(tf)
    if period is None:
        raise QuoteError(f"不支持的周期 {tf}")

    if period == "d":
        rows = hithink_daily(code, days)
        if rows:
            return to_bars(rows), "同花顺"
        rows = zhitu_history(code, "d", days)
        if rows:
            return to_bars(rows), "智兔"
        rows = tencent_history(code, "d", max(250, min(days, 640)))
        if rows:
            return to_bars(rows), "腾讯"
    else:
        # 分钟线：智兔为主，腾讯兜底（窗口按周期缩小以免拉太多）
        rows = zhitu_history(code, period, max(30, min(days, 120)))
        if rows:
            return to_bars(rows), "智兔"
        rows = tencent_history(code, period, 640)
        if rows:
            return to_bars(rows), "腾讯"
    raise QuoteError(f"{code} {tf} 无数据（同花顺/智兔/腾讯 均已尝试）")


def fetch_all(code: str, tfs=("日线", "60分", "30分", "15分")) -> dict:
    out = {}
    for tf in tfs:
        try:
            bars, src = fetch(code, tf)
            out[tf] = {"bars": bars, "source": src}
        except QuoteError as e:
            out[tf] = {"error": str(e)}
    return out


def snapshot(codes: list[str]) -> dict:
    """同花顺实时快照，用于看当前价和涨跌幅。"""
    try:
        thscodes = ",".join(to_thscode(c) for c in codes)
        url = f"{HITHINK_BASE}/api/a-share/prices/snapshot?thscodes={thscodes}"
        d = json.loads(_get(url, {"X-api-key": _key("API_KEY")}))
        if d.get("code") != 0:
            return {}
        return {it["ticker"]: it for it in ((d.get("data") or {}).get("item") or [])}
    except Exception:
        return {}
