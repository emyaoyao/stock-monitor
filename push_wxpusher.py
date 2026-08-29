"""WxPusher 推送：把买点信号发到微信。

凭据走环境变量 WXPUSHER_APP_TOKEN / WXPUSHER_UID，不落盘、不进日志。
接口：POST https://wxpusher.zjiecode.com/api/send/message
contentType 1=HTML，2=纯文本，3=Markdown。微信公众号正文不支持 Markdown，用 1。
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.request

UA = "Mozilla/5.0 (pa-workbench/1.0)"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
SEND_URL = "https://wxpusher.zjiecode.com/api/send/message"
USER_URL = "https://wxpusher.zjiecode.com/api/fun/wxuser/v2"


class PushError(RuntimeError):
    pass


def _creds() -> tuple[str, str]:
    tok = os.environ.get("WXPUSHER_APP_TOKEN")
    uid = os.environ.get("WXPUSHER_UID")
    if not tok or not uid:
        raise PushError("环境变量 WXPUSHER_APP_TOKEN / WXPUSHER_UID 未设置")
    return tok, uid


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def check_subscription() -> dict:
    """确认 UID 是否真的关注了应用，避免推了才发现没人收。"""
    tok, uid = _creds()
    req = urllib.request.Request(f"{USER_URL}?appToken={tok}&uid={uid}",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    records = ((d.get("data") or {}).get("records") or [])
    return {
        "ok": d.get("code") == 1000 and bool(records),
        "count": len(records),
        "app": records[0].get("target") if records else None,
        "raw": d.get("msg"),
    }


def send(title: str, content_html: str, summary: str = "") -> dict:
    """发一条消息。返回接口响应。"""
    tok, uid = _creds()
    payload = {
        "appToken": tok,
        "content": content_html,
        "summary": (summary or title)[:100],
        "contentType": 1,
        "uids": [uid],
        "verifyPayType": 0,
    }
    d = _post(SEND_URL, payload)
    if d.get("code") != 1000:
        raise PushError(f"推送失败 code={d.get('code')} msg={d.get('msg')}")
    return d


def render_report(items: list[dict], title: str = "价格行为 · 买点监控") -> str:
    """把监控结果渲染成微信里能看的 HTML。红涨绿跌，符合 A 股习惯。"""
    if not items:
        return (f"<h3>{title}</h3>"
                f"<p>本次扫描没有出现「可买入」信号。</p>"
                f"<p style='color:#888;font-size:12px'>"
                f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}</p>")

    parts = [f"<h3>{title}</h3>",
             f"<p style='color:#888;font-size:12px'>"
             f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')} · "
             f"共 {len(items)} 只标的触发</p>"]
    for it in items:
        pct = it.get("changePct")
        color = "#c0392b" if (pct or 0) >= 0 else "#1e8449"
        pct_txt = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "—"
        parts.append(
            f"<div style='border-left:4px solid #d4a017;padding:6px 10px;margin:10px 0'>"
            f"<b>{it['code']}</b> "
            f"<span style='color:{color}'>{it.get('price') or '—'} ({pct_txt})</span></div>")
        for s in it.get("buySignals", []):
            parts.append(
                f"<p style='margin:4px 0'>· <b>{s['model']}</b> "
                f"<span style='color:#d4a017'>[{s['tf']}]</span><br>"
                f"<span style='color:#666;font-size:12px'>{s['why']}</span></p>")
    parts.append("<hr><p style='color:#999;font-size:11px'>"
                 "信号来自课程规则转写，需人工复核后再决策。</p>")
    return "".join(parts)
