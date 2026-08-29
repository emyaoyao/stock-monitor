# -*- coding: utf-8 -*-
"""云端监控离线冒烟测试：桩掉行情(ME.evaluate_stock)与推送(PUSH.send)，
只验证 增删 / 去重只推新信号 / 查看 的逻辑。不联网、不需要 API Key。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import monitor_cloud as M

FAKE = {
    "code": "600519", "name": "测试", "price": 1700.0, "changePct": 1.2,
    "buySignals": [
        {"model": "首要突破回踩", "modelId": "m_pullback_long", "tf": "日线",
         "why": "首要 2/2", "direction": "多", "label": "可买入"},
        {"model": "旗形", "modelId": "m_flag", "tf": "60分",
         "why": "首要 1/1", "direction": "多", "label": "可买入"},
    ],
    "fetchedAt": "x",
}


def fake_scan(codes, names, quiet=False):
    return [dict(FAKE, code=c, name=names.get(c, "")) for c in codes]


def fake_push(title, html, summary, dry_run):
    fake_push.calls.append((title, summary))


fake_push.calls = []


def setup():
    M.ME.evaluate_stock = lambda code, models, tfs: {
        "code": code, "name": "测试", "price": 1700.0, "changePct": 1.2,
        "timeframes": {}, "models": {}, "fetchedAt": "x"}
    M.scan = fake_scan
    M.push = fake_push
    fake_push.calls = []
    M.WATCHLIST.write_text("[]", encoding="utf-8")
    M.LAST.write_text("[]", encoding="utf-8")


def test_empty_run():
    setup()
    M.do_run({"mode": "run", "add": None, "name": None, "remove": None}, True)
    assert not fake_push.calls, "空清单不应推送"


def test_add_then_dedup():
    setup()
    M.do_run({"mode": "run", "add": "600519", "name": "茅台", "remove": None}, True)
    wl = M.load_watchlist()
    assert any(w["code"] == "600519" for w in wl), "应已加入 600519"
    assert fake_push.calls, "加入后应立即回执推送"
    # 去重：第二次纯扫描不应再推
    fake_push.calls.clear()
    M.do_run({"mode": "run", "add": None, "name": None, "remove": None}, True)
    assert not fake_push.calls, "去重：已推送过的信号不应重复推"


def test_view():
    setup()
    M.WATCHLIST.write_text('[{"code":"600519","name":"茅台"}]', encoding="utf-8")
    M.do_view({"mode": "view"}, True)
    assert any("监控清单" in t for t, _ in fake_push.calls), "view 应推送清单"


def test_remove():
    setup()
    M.WATCHLIST.write_text('[{"code":"600519","name":"茅台"}]', encoding="utf-8")
    M.do_run({"mode": "run", "add": None, "name": None, "remove": "600519"}, True)
    wl = M.load_watchlist()
    assert not any(w["code"] == "600519" for w in wl), "应已移除 600519"


def test_resolve_env():
    # repository_dispatch 注入
    import os
    os.environ["GITHUB_EVENT_NAME"] = "repository_dispatch"
    os.environ["DISPATCH_CLIENT"] = '{"mode":"view","add_code":"300750"}'
    os.environ["DISPATCH_INPUTS"] = ""
    c = M.resolve_command(__import__("argparse").Namespace(mode=None, add=None, name=None, remove=None))
    assert c["mode"] == "view" and c["add"] == "300750", c
    # workflow_dispatch 注入
    os.environ["GITHUB_EVENT_NAME"] = "workflow_dispatch"
    os.environ["DISPATCH_INPUTS"] = '{"mode":"run","remove_code":"600519"}'
    os.environ["DISPATCH_CLIENT"] = ""
    c = M.resolve_command(__import__("argparse").Namespace(mode=None, add=None, name=None, remove=None))
    assert c["mode"] == "run" and c["remove"] == "600519", c
    # schedule 固定 run
    os.environ["GITHUB_EVENT_NAME"] = "schedule"
    c = M.resolve_command(__import__("argparse").Namespace(mode=None, add=None, name=None, remove=None))
    assert c["mode"] == "run" and not c["add"], c


if __name__ == "__main__":
    test_empty_run()
    test_add_then_dedup()
    test_view()
    test_remove()
    test_resolve_env()
    print("SMOKE OK —— 增删 / 去重只推新信号 / 查看 / 事件解析 全部通过")
