"""买点监控引擎：用真实 K 线跑模型库里的条件，给出逐条判定和综合建议。

判定逻辑和工作台界面保持一致：
  首要条件 全部满足（AND）
  次要条件 满足数 >= 模型设定的最少条数
  排除条件 命中任一 → 直接否决

四个周期各自独立跑一遍，用来看多周期共振。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import formula_eval as FE  # noqa: E402
import model_conditions as MC  # noqa: E402
import quote_client as Q  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
TFS = ("日线", "60分", "30分", "15分")
PH = re.compile(r"\{\{(\w+)\}\}")

VERDICT_BUY = "可买入"
VERDICT_WATCH = "关注"
VERDICT_WAIT = "观望"


def verdict_label(code: str, direction: str) -> str:
    """把内部判定翻译成人话。

    A 股做空工具受限，做空模型命中时其实是「卖点/清仓信号」，
    直接写「可买入」会让人当场看反方向。
    """
    if code == VERDICT_BUY:
        return {"多": "可买入", "空": "可卖出（做空信号）", "中性": "可入场"}.get(direction, "可买入")
    if code == VERDICT_WATCH:
        return "关注"
    return "观望"


def render_tdx(cond: dict, overrides: dict) -> tuple[str, str]:
    vals = {p["key"]: p["default"] for p in cond["params"]}
    vals.update(overrides or {})
    body = PH.sub(lambda m: str(vals.get(m.group(1), "")), cond["formula"]["tdx"])
    expr = PH.sub(lambda m: str(vals.get(m.group(1), "")), cond["expr"])
    return body, expr.upper()


def eval_condition(cid: str, bars: dict, overrides: dict) -> tuple[bool, str]:
    """跑单条条件。返回 (是否命中, 出错信息)。出错时按未命中处理但保留原因。"""
    cond = MC.by_id(cid)
    if not cond:
        return False, f"未知条件 {cid}"
    try:
        body, expr = render_tdx(cond, overrides)
        ctx = FE.run_statements(body, bars)
        if expr not in ctx:
            return False, f"未产出变量 {expr}"
        return FE.last_true(ctx[expr]), ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def eval_model(model: dict, bars: dict) -> dict:
    """在单一周期数据上跑一个模型。"""
    rows, errors = [], []
    p_hit = p_need = 0
    s_hit = 0
    x_hit = []

    for role, label in (("primary", "首要"), ("secondary", "次要"), ("exclusion", "排除")):
        for item in model.get(role) or []:
            cid = item["id"] if isinstance(item, dict) else item
            ov = (item.get("params") or {}) if isinstance(item, dict) else {}
            cond = MC.by_id(cid)
            hit, err = eval_condition(cid, bars, ov)
            if err:
                errors.append(f"{cond['name'] if cond else cid}: {err}")
            rows.append({
                "id": cid,
                "name": cond["name"] if cond else cid,
                "role": role,
                "roleLabel": label,
                "hit": hit,
                "error": err,
                "desc": cond["desc"] if cond else "",
            })
            if role == "primary":
                p_need += 1
                p_hit += 1 if hit else 0
            elif role == "secondary":
                s_hit += 1 if hit else 0
            elif hit:
                x_hit.append(cond["name"] if cond else cid)

    min_s = model.get("min_secondary") or 1
    if x_hit:
        verdict, why = VERDICT_WAIT, "命中排除条件：" + "、".join(x_hit)
    elif p_need and p_hit >= p_need and s_hit >= min_s:
        verdict, why = VERDICT_BUY, f"首要 {p_hit}/{p_need} 全中，次要 {s_hit}（需 {min_s}）"
    elif p_need and p_hit >= max(1, (p_need + 1) // 2):
        verdict, why = VERDICT_WATCH, f"首要 {p_hit}/{p_need}，次要 {s_hit}（需 {min_s}）"
    else:
        verdict, why = VERDICT_WAIT, f"首要仅 {p_hit}/{p_need}"

    return {
        "verdict": verdict,
        "verdictLabel": verdict_label(verdict, model.get("direction", "中性")),
        "direction": model.get("direction", "中性"),
        "why": why,
        "primaryHit": p_hit,
        "primaryNeed": p_need,
        "secondaryHit": s_hit,
        "secondaryNeed": min_s,
        "exclusionHit": x_hit,
        "rows": rows,
        "errors": errors,
        "bars": len(bars.get("c") or []),
    }


def evaluate_stock(code: str, models: list[dict], tfs=TFS) -> dict:
    """对一只股票跑指定模型（默认全部），每个周期各跑一遍。"""
    data = Q.fetch_all(code, tfs)
    snap = Q.snapshot([code]).get(code.zfill(6).split(".")[0], {})
    result = {
        "code": code,
        "name": snap.get("ticker") or "",
        "price": snap.get("last_price"),
        "changePct": snap.get("price_change_ratio_pct"),
        "timeframes": {},
        "models": {},
        "fetchedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    for tf in tfs:
        item = data.get(tf) or {}
        if "error" in item:
            result["timeframes"][tf] = {"error": item["error"]}
        else:
            result["timeframes"][tf] = {
                "source": item["source"],
                "bars": len(item["bars"]["c"]),
                "last": item["bars"]["t"][-1] if item["bars"]["t"] else "",
                "close": item["bars"]["c"][-1] if item["bars"]["c"] else None,
            }
        for m in models:
            bucket = result["models"].setdefault(m["id"], {
                "name": m["name"],
                "type": m.get("type", ""),
                "direction": m.get("direction", "中性"),
                "byTf": {},
            })
            if "error" in item:
                bucket["byTf"][tf] = {"verdict": "无数据", "why": item["error"], "rows": []}
            else:
                bucket["byTf"][tf] = eval_model(m, item["bars"])
    return result


def load_models(path: Path | None = None) -> list[dict]:
    p = path or (OUT / "models_v5.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    return d["models"]


def summarize(result: dict) -> dict:
    """汇总：哪些模型在哪个周期给出了「可买入」。"""
    hits = []
    for mid, m in result.get("models", {}).items():
        for tf, r in m["byTf"].items():
            if r.get("verdict") == VERDICT_BUY:
                hits.append({
                    "model": m["name"], "modelId": mid, "tf": tf,
                    "why": r["why"],
                    "direction": result["models"][mid].get("direction", "中性"),
                    "label": r.get("verdictLabel", VERDICT_BUY),
                })
    return {
        "code": result["code"],
        "price": result.get("price"),
        "changePct": result.get("changePct"),
        "buySignals": hits,
        "fetchedAt": result.get("fetchedAt"),
    }
