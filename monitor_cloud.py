# -*- coding: utf-8 -*-
"""买点监控 · 云端入口（GitHub Actions 上跑，脱离本机）。

三种触发方式，全部由本文件统一处理：
  1) schedule        —— 定时扫描（盘前 09:20 + 交易时段每 30 分），只推「新出现」的买点信号
  2) workflow_dispatch —— 在 GitHub 手机端/网页点「Run workflow」并填代码，手动增删/查看
  3) repository_dispatch —— 由 Cloudflare Worker 桥接转发 WxPusher 微信上行消息触发（最丝滑）

指令来源优先级：命令行参数 > GitHub Actions 注入的环境变量（DISPATCH_INPUTS / DISPATCH_CLIENT）。

持久化（提交回仓库，因此「不开电脑」也记得住清单和去重状态）：
  outputs/watchlist.json   监控清单
  outputs/last_signals.json 上一次已推送的 (代码|模型|周期) 键集合，用于去重

仅依赖标准库 + 同目录的 monitor_engine / push_wxpusher 等模块。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import monitor_engine as ME   # noqa: E402
import push_wxpusher as PUSH  # noqa: E402

MODELS = SCRIPT_DIR / "models_v5.json"
OUT = SCRIPT_DIR / "outputs"
WATCHLIST = OUT / "watchlist.json"
LAST = OUT / "last_signals.json"
RESULT = OUT / "monitor_result.json"


# ------------------------------------------------------------------ 持久化

def load_watchlist() -> list[dict]:
    if WATCHLIST.exists():
        try:
            return json.loads(WATCHLIST.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_watchlist(items: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    WATCHLIST.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def load_last_signals() -> dict:
    if LAST.exists():
        try:
            data = json.loads(LAST.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {"keys": data}
            return data if isinstance(data, dict) else {"keys": []}
        except Exception:
            pass
    return {"keys": []}


def save_last_signals(keys: set[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # 只存键集合，不存时间戳：内容仅在信号状态真正变化时才变，避免每次运行都产生 commit 噪音
    LAST.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=1),
                   encoding="utf-8")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ 指令解析

def _parse_payload(raw: str | None) -> dict:
    """GitHub Actions 用 toJSON(github.event.inputs) 注入，非对应事件下可能是
    '' / 'null' / 非法串，全部兜底成空字典，避免 JSONDecodeError。"""
    if not raw or raw.strip() in ("", "null"):
        return {}
    try:
        return json.loads(raw) or {}
    except Exception:
        return {}

def resolve_command(args: argparse.Namespace) -> dict:
    """从 GitHub Actions 事件或命令行拿到本次要做什么。"""
    ev = os.environ.get("GITHUB_EVENT_NAME", "")
    if ev == "schedule":
        return {"mode": "run", "add": None, "name": None, "remove": None}
    if ev in ("workflow_dispatch", "repository_dispatch"):
        key = "DISPATCH_INPUTS" if ev == "workflow_dispatch" else "DISPATCH_CLIENT"
        payload = _parse_payload(os.environ.get(key))
        # 命令行参数优先（本地调试用），否则取事件负载
        return {
            "mode": args.mode or payload.get("mode") or "run",
            "add": args.add or payload.get("add_code"),
            "name": args.name or payload.get("add_name"),
            "remove": args.remove or payload.get("remove_code"),
        }
    # 本地直接跑
    return {"mode": args.mode or "run", "add": args.add,
            "name": args.name, "remove": args.remove}


# ------------------------------------------------------------------ 扫描核心

def scan(codes: list[str], names: dict[str, str], quiet: bool = False) -> list[dict]:
    """对清单里每只票跑全部模型，返回 summaries。单只失败不影响其他。"""
    models = ME.load_models(MODELS)
    results, summaries = [], []
    for code in codes:
        print(f"[dbg] code={code!r} names_keys={list(names.keys())} names_get={names.get(code)!r}", flush=True)
        try:
            r = ME.evaluate_stock(code, models, ME.TFS)
            r["name"] = names.get(code, r.get("name", ""))
            results.append(r)
            summ = ME.summarize(r)
            print(f"[dbg] summ_name_before={summ.get('name')!r} will_set={names.get(code, summ.get('name') or '')!r}", flush=True)
            # summarize 内部会另取行情源名称（常为 None），用 watchlist 名称兜底，保证落盘/APP 显示正确
            summ["name"] = names.get(code, summ.get("name") or "")
            summaries.append(summ)
            if not quiet:
                print(f"[scan] {code} {r.get('name','')} 价 {r.get('price')}")
        except Exception as e:
            print(f"[scan] {code} 失败：{type(e).__name__} {e}")
    # 落盘一份结果，供本地工作台读取（云端不提交，避免频繁 commit）
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps({
        "generatedAt": _now(), "tfs": list(ME.TFS),
        "modelCount": len(models), "results": results, "summaries": summaries,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return summaries


def signal_key(code: str, sig: dict) -> str:
    return f"{code}|{sig['modelId']}|{sig['tf']}"


def build_items(summaries: list[dict], names: dict[str, str],
                only_keys: set[str] | None = None) -> list[dict]:
    """把 summaries 整理成推送用的 items。only_keys 给定时只保留这些键对应的信号。"""
    items: list[dict] = []
    for s in summaries:
        sigs = s.get("buySignals") or []
        if only_keys is not None:
            sigs = [g for g in sigs if signal_key(s["code"], g) in only_keys]
        if not sigs:
            continue
        items.append({
            "code": s["code"],
            "name": names.get(s["code"], ""),
            "price": s.get("price"),
            "changePct": s.get("changePct"),
            "buySignals": sigs,
        })
    return items


def push(title: str, html: str, summary: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] 将要推送《{title}》：{summary}\n{html}")
        return
    try:
        r = PUSH.send(title, html, summary)
        print(f"[push] {r.get('msg')}（{summary}）")
    except Exception as e:
        print(f"[push] 失败：{type(e).__name__} {e}")


# ------------------------------------------------------------------ 模式

def do_run(cmd: dict, dry_run: bool) -> None:
    wl = load_watchlist()
    names = {w["code"]: w.get("name", "") for w in wl}

    # 先处理增删（来自 dispatch / 微信）
    changed = False
    if cmd["add"]:
        code = cmd["add"].strip()
        if any(w["code"] == code for w in wl):
            print(f"[run] {code} 已在清单")
        else:
            wl.append({"code": code, "name": (cmd["name"] or "").strip()})
            save_watchlist(wl)
            names[code] = (cmd["name"] or "").strip()
            changed = True
            print(f"[run] 已加入 {code} {cmd['name'] or ''}")
    if cmd["remove"]:
        code = cmd["remove"].strip()
        wl = [w for w in wl if w["code"] != code]
        save_watchlist(wl)
        changed = True
        print(f"[run] 已移除 {code}")

    codes = [w["code"] for w in wl]
    if not codes:
        print("[run] 监控清单为空，跳过扫描")
        if changed and not dry_run:
            # 增删后清单变空也要让用户知道
            push("价格行为 · 买点监控",
                 "<p>监控清单已更新，目前为空。发「加 600519」或在工作流里填代码即可添加。</p>",
                 "清单为空", dry_run)
        return

    summaries = scan(codes, names, quiet=True)

    if cmd["add"] or cmd["remove"]:
        # 手动增删：给个回执（含当前清单 + 新信号）
        items = build_items(summaries, names)
        wl_txt = "<br>".join(f"· {w['code']} {w.get('name','')}" for w in wl) or "（空）"
        header = (f"<p>操作完成。当前监控 <b>{len(wl)}</b> 只：</p><p style='color:#666'>{wl_txt}</p>")
        body = PUSH.render_report(items) if items else "<p>当前无买点信号。</p>"
        push("价格行为 · 监控清单已更新", header + body,
             f"监控 {len(wl)} 只" + (f"／新信号 {len(items)}" if items else ""), dry_run)
        # 仍更新去重状态
        cur = {signal_key(s["code"], g) for s in summaries for g in s.get("buySignals", [])}
        save_last_signals(cur)
        return

    # 纯定时扫描：只推「新出现」的买点
    prev = set(load_last_signals().get("keys", []))
    cur = {signal_key(s["code"], g) for s in summaries for g in s.get("buySignals", [])}
    new_keys = cur - prev
    if new_keys:
        items = build_items(summaries, names, only_keys=new_keys)
        html = PUSH.render_report(items)
        cnt = sum(len(i["buySignals"]) for i in items)
        push("价格行为 · 买点监控（新信号）", html,
             f"{len(items)} 只标的 {cnt} 条新买点", dry_run)
    else:
        print("[run] 无新买点信号，静默（按你的偏好只推新信号）")
    save_last_signals(cur)


def do_view(cmd: dict, dry_run: bool) -> None:
    wl = load_watchlist()
    names = {w["code"]: w.get("name", "") for w in wl}
    codes = [w["code"] for w in wl]
    if not codes:
        push("价格行为 · 监控清单", "<p>监控清单为空。发「加 600519」或在工作流里填代码添加。</p>",
             "清单为空", dry_run)
        return
    summaries = scan(codes, names, quiet=True)
    items = build_items(summaries, names)  # 当前所有买点（查看时不过滤）
    wl_txt = "<br>".join(f"· {w['code']} {w.get('name','')}" for w in wl)
    header = (f"<h3>价格行为 · 监控清单（{_now()}）</h3>"
              f"<p style='color:#666'>共 {len(wl)} 只：</p><p style='color:#666'>{wl_txt}</p>"
              f"<hr>")
    body = PUSH.render_report(items) if items else "<p>当前无买点信号。</p>"
    push("价格行为 · 监控清单", header + body,
         f"监控 {len(wl)} 只" + (f"／买点 {len(items)}" if items else ""), dry_run)


def do_help(dry_run: bool) -> None:
    html = (
        "<h3>买点监控 · 指令</h3>"
        "<p>在微信里给本应用发消息即可（需配好回调桥接）：</p>"
        "<p>· <b>加 600519</b> 或 <b>加 600519 茅台</b> —— 加入监控<br>"
        "· <b>删 600519</b> —— 移除监控<br>"
        "· <b>列表</b> / <b>查看</b> —— 看当前清单与买点<br>"
        "· <b>帮助</b> —— 本说明</p>"
        "<p style='color:#999;font-size:11px'>也可在 GitHub 手机端 Actions → 买点监控 → Run workflow 手动操作。</p>"
    )
    push("价格行为 · 帮助", html, "指令说明", dry_run)


# ------------------------------------------------------------------ 主入口

def main() -> int:
    ap = argparse.ArgumentParser(description="价格行为买点监控 · 云端入口")
    ap.add_argument("--mode", help="run / view / help")
    ap.add_argument("--add", help="加入监控代码，如 600519")
    ap.add_argument("--name", help="配合 --add 的名称")
    ap.add_argument("--remove", help="移除监控代码")
    ap.add_argument("--dry-run", action="store_true", help="不真正推送，只打印")
    args = ap.parse_args()

    cmd = resolve_command(args)
    mode = (cmd["mode"] or "run").lower()
    print(f"[main] event={os.environ.get('GITHUB_EVENT_NAME','local')} "
          f"mode={mode} add={cmd['add']} remove={cmd['remove']} dry={args.dry_run}")

    if mode == "view":
        do_view(cmd, args.dry_run)
    elif mode == "help":
        do_help(args.dry_run)
    else:
        do_run(cmd, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
