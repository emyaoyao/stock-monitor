"""价格行为模型库的原子条件卡。

每张条件卡 = 一个可被程序判定的事实 + 三套公式片段（通达信 / 同花顺 / Pine）。

约束（血的教训）：
  1. 变量名必须带参数后缀（如 EMAV20 而不是 EMAV）。多条条件组合成公式时，
     参数不同的同名变量会互相覆盖，导致结果莫名其妙。
  2. 通达信选股公式必须以 `XG:` 结尾，中间变量用 `:=`。
  3. 通达信没有内置 ATR，需要自己用真实波幅算；`TR` 这组字母容易被占用，用 `TRV`。
  4. 同花顺选股公式基本兼容通达信语法，个别函数名有差异，模板里分开维护。

占位符用 {{N}}，生成公式时按参数值替换。
"""

from __future__ import annotations

# 分组：工作台里按这个分组展示条件，便于勾选
GROUPS = [
    ("trend", "趋势与结构", "先定背景：市场是趋势还是区间，方向朝哪"),
    ("channel", "通道", "窄通道 / 宽通道 / 微通道的识别与位置"),
    ("range", "震荡区间", "区间识别、区间内的高抛低吸位置"),
    ("breakout", "突破", "突破、跟随、以及 80% 会失败的假突破"),
    ("pullback", "回调", "回调深度、形态、首次回调与两腿回调"),
    ("signalbar", "信号K线", "入场触发：信号K线与入场K线的判定"),
    ("pattern", "形态结构", "双底双顶、头肩、旗形、楔形、三角形"),
    ("climax", "高潮", "抛售/买入高潮与随之而来的反转"),
    ("volume", "量能", "成交量对突破与高潮的验证"),
    ("risk", "风险与盈亏比", "止损距离、盈亏比、波动率过滤"),
    ("open", "开盘与早盘", "开盘缺口、早盘首根K线"),
]

# 通用片段：真实波幅（通达信无内置 ATR）
# 占位符必须写成 {{N}}，和其余模板保持一致，否则渲染时会漏替换。
_ATR_TDX = (
    "TRV{{N}}:=MAX(MAX(H-L,ABS(H-REF(C,1))),ABS(L-REF(C,1)));\n"
    "ATRV{{N}}:=MA(TRV{{N}},{{N}});"
)
_ATR_PINE = "atr{{N}} = ta.atr({{N}})"


def P(key, label, default, min_v, max_v, step=1):
    return {"key": key, "label": label, "default": default,
            "min": min_v, "max": max_v, "step": step}


CONDITIONS: list[dict] = []


def C(cid, name, group, direction, desc, expr, tdx, pine, params=(), units=(), ths=None):
    CONDITIONS.append({
        "id": cid,
        "name": name,
        "group": group,
        "direction": direction,       # 多 / 空 / 中性
        "desc": desc,
        "expr": expr,                 # 组合公式时引用的变量名
        "formula": {"tdx": tdx, "ths": ths or tdx, "pine": pine},
        "params": list(params),
        "units": list(units),
    })


# ============================================================ 趋势与结构
C("trend_up_structure", "上涨趋势结构（HH+HL）", "trend", "多",
  "近 N 根K线的低点高于前 N 根K线的低点，且高点也抬高——这是课程对上涨趋势的定义。"
  "趋势是一切的前提，逆势做多的胜率会显著下降。",
  "UPT{{N}}",
  "UPT{{N}}:=LLV(L,{{N}})>REF(LLV(L,{{N}}),{{N}}) AND HHV(H,{{N}})>=REF(HHV(H,{{N}}),{{N}});",
  "upt{{N}} = ta.lowest(low, {{N}}) > ta.lowest(low, {{N}})[{{N}}] and ta.highest(high, {{N}}) >= ta.highest(high, {{N}})[{{N}}]",
  [P("N", "回看K线数", 10, 3, 60)], ["13", "14"])

C("trend_down_structure", "下降趋势结构（LH+LL）", "trend", "空",
  "近 N 根K线的高点低于前 N 根K线的高点，且低点也下移——下降趋势的定义。",
  "DNT{{N}}",
  "DNT{{N}}:=HHV(H,{{N}})<REF(HHV(H,{{N}}),{{N}}) AND LLV(L,{{N}})<=REF(LLV(L,{{N}}),{{N}});",
  "dnt{{N}} = ta.highest(high, {{N}}) < ta.highest(high, {{N}})[{{N}}] and ta.lowest(low, {{N}}) <= ta.lowest(low, {{N}})[{{N}}]",
  [P("N", "回看K线数", 10, 3, 60)], ["13", "14"])

C("price_above_ema", "收盘价在 EMA 上方", "trend", "多",
  "课程里说的均线默认就是 EMA20。多头希望回调时价格维持在均线上方，"
  "首次回调到均线不破是标准的顺势做多点。",
  "PABV{{N}}",
  "EMAV{{N}}:=EMA(C,{{N}});\nPABV{{N}}:=C>EMAV{{N}};",
  "emav{{N}} = ta.ema(close, {{N}})\npabv{{N}} = close > emav{{N}}",
  [P("N", "EMA周期", 20, 5, 120)], ["11", "14"])

C("price_below_ema", "收盘价在 EMA 下方", "trend", "空",
  "空头希望反弹不超过均线，反弹到均线附近受阻是顺势做空点。",
  "PBEL{{N}}",
  "EMAV{{N}}:=EMA(C,{{N}});\nPBEL{{N}}:=C<EMAV{{N}};",
  "emav{{N}} = ta.ema(close, {{N}})\npbel{{N}} = close < emav{{N}}",
  [P("N", "EMA周期", 20, 5, 120)], ["11", "14"])

C("ema_slope_up", "EMA 向上", "trend", "多",
  "均线本身在上升,说明趋势有惯性。突破行情需要均线配合,均线走平时突破更容易失败。",
  "EMUP{{N}}",
  "EMAV{{N}}:=EMA(C,{{N}});\nEMUP{{N}}:=EMAV{{N}}>REF(EMAV{{N}},{{M}});",
  "emav{{N}} = ta.ema(close, {{N}})\nemup{{N}} = emav{{N}} > emav{{N}}[{{M}}]",
  [P("N", "EMA周期", 20, 5, 120), P("M", "对比前推K线", 5, 1, 30)], ["14"])

C("ema_slope_down", "EMA 向下", "trend", "空",
  "均线下降,空头趋势有惯性,反弹到均线附近是做空机会。",
  "EMDN{{N}}",
  "EMAV{{N}}:=EMA(C,{{N}});\nEMDN{{N}}:=EMAV{{N}}<REF(EMAV{{N}},{{M}});",
  "emav{{N}} = ta.ema(close, {{N}})\nemdn{{N}} = emav{{N}} < emav{{N}}[{{M}}]",
  [P("N", "EMA周期", 20, 5, 120), P("M", "对比前推K线", 5, 1, 30)], ["14"])

C("ema_stack_bull", "均线多头排列", "trend", "多",
  "短期均线在长期均线上方,趋势结构完整,回调做多的背景更可靠。",
  "ESTK{{A}}_{{B}}",
  "EMA{{A}}:=EMA(C,{{A}});\nEMA{{B}}:=EMA(C,{{B}});\nESTK{{A}}_{{B}}:=EMA{{A}}>EMA{{B}};",
  "ema{{A}} = ta.ema(close, {{A}})\nema{{B}} = ta.ema(close, {{B}})\nestk{{A}}_{{B}} = ema{{A}} > ema{{B}}",
  [P("A", "短周期", 20, 5, 60), P("B", "长周期", 60, 20, 250)], ["14"],
  ths="EMA{{A}}:=EMA(CLOSE,{{A}});\nEMA{{B}}:=EMA(CLOSE,{{B}});\nESTK{{A}}_{{B}}:=EMA{{A}}>EMA{{B}};")

C("strong_bull_swing", "单边上涨（连续趋势K线）", "trend", "多",
  "连续多根K线收盘价不断抬高、少有回调,说明多头完全掌控。单边行情中回调极浅,"
  "等待深度回调会踏空。",
  "SBS{{N}}",
  "SBS{{N}}:=COUNT(C>REF(C,1),{{N}})>={{K}} AND C>HHV(REF(C,1),{{N}});",
  "sbs{{N}} = math.sum(close > close[1] ? 1 : 0, {{N}}) >= {{K}} and close > ta.highest(close[1], {{N}})",
  [P("N", "回看K线数", 5, 3, 30), P("K", "至少上涨K线数", 4, 2, 30)], ["13"])

C("strong_bear_swing", "单边下跌（连续趋势K线）", "trend", "空",
  "连续多根K线收盘不断走低,空头掌控。此时抢反弹是逆势交易。",
  "SBR{{N}}",
  "SBR{{N}}:=COUNT(C<REF(C,1),{{N}})>={{K}} AND C<LLV(REF(C,1),{{N}});",
  "sbr{{N}} = math.sum(close < close[1] ? 1 : 0, {{N}}) >= {{K}} and close < ta.lowest(close[1], {{N}})",
  [P("N", "回看K线数", 5, 3, 30), P("K", "至少下跌K线数", 4, 2, 30)], ["13"])

# ============================================================ 通道
C("tight_channel_up", "窄上涨通道", "channel", "多",
  "回调极浅、K线重叠度高,每根K线的低点都不低于前一根低点太多。窄通道是强趋势的表现,"
  "在通道下沿买入、用较小止损。",
  "TCU{{N}}",
  "TCU{{N}}:=COUNT(L>=REF(L,1),{{N}})>={{K}} AND C>EMA(C,{{E}});",
  "tcu{{N}} = math.sum(low >= low[1] ? 1 : 0, {{N}}) >= {{K}} and close > ta.ema(close, {{E}})",
  [P("N", "回看K线数", 5, 3, 30), P("K", "至少不掉低的K线数", 4, 2, 30), P("E", "EMA周期", 20, 5, 120)],
  ["17", "43"])

C("tight_channel_down", "窄下降通道", "channel", "空",
  "反弹极浅的下降通道,每根K线的高点都不高于前一根高点太多。",
  "TCD{{N}}",
  "TCD{{N}}:=COUNT(H<=REF(H,1),{{N}})>={{K}} AND C<EMA(C,{{E}});",
  "tcd{{N}} = math.sum(high <= high[1] ? 1 : 0, {{N}}) >= {{K}} and close < ta.ema(close, {{E}})",
  [P("N", "回看K线数", 5, 3, 30), P("K", "至少不抬高的K线数", 4, 2, 30), P("E", "EMA周期", 20, 5, 120)],
  ["17", "44"])

C("micro_channel_up", "微通道上涨（连续收高）", "channel", "多",
  "连续 N 根K线收盘价一根比一根高,是窄通道的极端形式。微通道一旦被跌破,"
  "往往出现至少两段下跌。",
  "MCU{{N}}",
  "MCU{{N}}:=EVERY(C>REF(C,1),{{N}});",
  "mcu{{N}} = ta.barssince(close <= close[1]) > {{N}}",
  [P("N", "连续K线数", 4, 2, 20)], ["17", "43"])

C("wide_channel_up", "宽上涨通道（可做波段）", "channel", "多",
  "通道足够宽时,多头在通道下沿买、上沿卖,波段空间才够。宽度用近 N 根K线的"
  "平均真实波幅衡量。",
  "WCU{{N}}",
  _ATR_TDX + "\nWCU{{N}}:=ATRV{{N}}>MA(C,{{N}})*{{R}}/100 AND C>EMA(C,{{E}});",
  _ATR_PINE + "\nwcu{{N}} = atr{{N}} > ta.sma(close, {{N}}) * {{R}} / 100 and close > ta.ema(close, {{E}})",
  [P("N", "ATR周期", 20, 5, 60), P("R", "ATR占价格百分比下限", 2, 1, 10), P("E", "EMA周期", 20, 5, 120)],
  ["16", "45"])

# ============================================================ 震荡区间
C("in_trading_range", "处于震荡区间", "range", "中性",
  "近 N 根K线的高点没有明显抬高、低点没有明显下移——市场在横盘。"
  "区间里要改用高抛低吸,趋势策略会连续被打止损。",
  "ITR{{N}}",
  "RH{{N}}:=HHV(H,{{N}});\nRL{{N}}:=LLV(L,{{N}});\n"
  "ITR{{N}}:=RH{{N}}<REF(HHV(H,{{N}}),{{N}})*1.0{{R}} AND RL{{N}}>REF(LLV(L,{{N}}),{{N}})*0.{{S}};",
  "rh{{N}} = ta.highest(high, {{N}})\nrl{{N}} = ta.lowest(low, {{N}})\n"
  "itr{{N}} = rh{{N}} < ta.highest(high, {{N}})[{{N}}] and rl{{N}} > ta.lowest(low, {{N}})[{{N}}]",
  [P("N", "区间回看K线数", 20, 5, 120), P("R", "高点容差(%)", 3, 1, 20), P("S", "低点容差(%)", 97, 80, 99)],
  ["18", "47"])

C("range_bottom_third", "处于区间底部三分之一", "range", "多",
  "课程强调:区间做多不要在下半区就买,要等价格进入底部 1/3,因为市场往往会"
  "跌到区间底部。这是高抛低吸(BLSHS)的买点。",
  "RBT{{N}}",
  "RH{{N}}:=HHV(H,{{N}});\nRL{{N}}:=LLV(L,{{N}});\nRBT{{N}}:=C<=RL{{N}}+(RH{{N}}-RL{{N}})/3;",
  "rh{{N}} = ta.highest(high, {{N}})\nrl{{N}} = ta.lowest(low, {{N}})\nrbt{{N}} = close <= rl{{N}} + (rh{{N}} - rl{{N}}) / 3",
  [P("N", "区间回看K线数", 20, 5, 120)], ["47"])

C("range_top_third", "处于区间顶部三分之一", "range", "空",
  "区间做空同理,要等价格进入顶部 1/3 再卖,而不是中间就入场。",
  "RTT{{N}}",
  "RH{{N}}:=HHV(H,{{N}});\nRL{{N}}:=LLV(L,{{N}});\nRTT{{N}}:=C>=RH{{N}}-(RH{{N}}-RL{{N}})/3;",
  "rh{{N}} = ta.highest(high, {{N}})\nrl{{N}} = ta.lowest(low, {{N}})\nrtt{{N}} = close >= rh{{N}} - (rh{{N}} - rl{{N}}) / 3",
  [P("N", "区间回看K线数", 20, 5, 120)], ["47"])

C("tight_range", "窄幅震荡区间（TTR）", "range", "中性",
  "区间太窄时,扣除点差和手续费后赚不到钱,剥头皮的最低目标都够不着。"
  "通常作为排除条件使用。",
  "TTR{{N}}",
  _ATR_TDX + "\nTTR{{N}}:=ATRV{{N}}<MA(C,{{N}})*{{R}}/100;",
  _ATR_PINE + "\nttr{{N}} = atr{{N}} < ta.sma(close, {{N}}) * {{R}} / 100",
  [P("N", "ATR周期", 20, 5, 60), P("R", "ATR占价格百分比上限", 1, 1, 10)], ["18", "47"])

# ============================================================ 突破
C("breakout_prev_high", "突破前 N 根K线高点", "breakout", "多",
  "突破是一根或数根趋势K线,冲过某个支撑或阻力。先过前一根K线高点,"
  "再过前期高点,最后过趋势线和均线。",
  "BPH{{N}}",
  "BPH{{N}}:=H>REF(HHV(H,{{N}}),1) AND C>REF(HHV(H,{{N}}),1);",
  "bph{{N}} = high > ta.highest(high, {{N}})[1] and close > ta.highest(high, {{N}})[1]",
  [P("N", "突破回看K线数", 20, 3, 120)], ["15", "41"])

C("breakdown_prev_low", "跌破前 N 根K线低点", "breakout", "空",
  "空头突破的对称版本:跌破前期低点并收在其下方。",
  "BPL{{N}}",
  "BPL{{N}}:=L<REF(LLV(L,{{N}}),1) AND C<REF(LLV(L,{{N}}),1);",
  "bpl{{N}} = low < ta.lowest(low, {{N}})[1] and close < ta.lowest(low, {{N}})[1]",
  [P("N", "跌破回看K线数", 20, 3, 120)], ["15", "41"])

C("breakout_strong_close", "突破且收盘强势", "breakout", "多",
  "突破K线必须收在高位——收盘接近最高、实体饱满才说明多头真金白银推上去。"
  "收盘软弱(长上影)的突破大概率失败。",
  "BSC{{R}}",
  "BODY:=ABS(C-O);\nBSC{{R}}:=C>O AND (H-L)>0 AND (C-L)/(H-L)>{{R}}/100;",
  "bsc{{R}} = close > open and (high - low) > 0 and (close - low) / (high - low) > {{R}} / 100",
  [P("R", "收盘位于K线区间百分比下限", 70, 50, 95)], ["08", "15"])

C("breakdown_strong_close", "跌破且收盘弱势", "breakout", "空",
  "空头突破K线要收在低位,收盘接近最低。",
  "BDC{{R}}",
  "BDC{{R}}:=C<O AND (H-L)>0 AND (H-C)/(H-L)>{{R}}/100;",
  "bdc{{R}} = close < open and (high - low) > 0 and (high - close) / (high - low) > {{R}} / 100",
  [P("R", "收盘位于K线区间百分比下限", 70, 50, 95)], ["08", "15"])

C("big_bull_bar", "大阳线（实体显著）", "breakout", "多",
  "实体大于近 N 根K线平均实体的 K/10 倍（默认 1.5 倍）。大阳线本身就是一次突破,"
  "是最强的做多信号K线。",
  "BBB{{N}}_{{K}}",
  "ABODY{{N}}:=MA(ABS(C-O),{{N}});\nBBB{{N}}_{{K}}:=C>O AND ABS(C-O)>ABODY{{N}}*{{K}}/10;",
  "abody{{N}} = ta.sma(math.abs(close - open), {{N}})\nbbb{{N}}_{{K}} = close > open and math.abs(close - open) > abody{{N}} * {{K}} / 10",
  [P("N", "平均实体回看", 20, 5, 60), P("K", "实体倍数×10", 15, 10, 40)],
  ["08", "15"])

C("big_bear_bar", "大阴线（实体显著）", "breakout", "空",
  "实体显著大于平均的大阴线,是最强的做空信号K线,同时也可能是抛售高潮。",
  "BBR{{N}}_{{K}}",
  "ABODY{{N}}:=MA(ABS(C-O),{{N}});\nBBR{{N}}_{{K}}:=C<O AND ABS(C-O)>ABODY{{N}}*{{K}}/10;",
  "abody{{N}} = ta.sma(math.abs(close - open), {{N}})\nbbr{{N}}_{{K}} = close < open and math.abs(close - open) > abody{{N}} * {{K}} / 10",
  [P("N", "平均实体回看", 20, 5, 60), P("K", "实体倍数×10", 15, 10, 40)],
  ["08", "29"])

C("failed_breakout_up", "向上假突破（多头陷阱）", "breakout", "空",
  "80% 的突破会失败。价格冲过前高却收在区间内或前高下方,是多头陷阱——"
  "突破失败后通常至少有两段下跌。这是课程里性价比最高的反做形态之一。",
  "FBU{{N}}",
  "PH{{N}}:=REF(HHV(H,{{N}}),1);\nFBU{{N}}:=H>PH{{N}} AND C<PH{{N}};",
  "ph{{N}} = ta.highest(high, {{N}})[1]\nfbu{{N}} = high > ph{{N}} and close < ph{{N}}",
  [P("N", "突破回看K线数", 20, 3, 120)], ["15", "41"])

C("failed_breakout_down", "向下假突破（空头陷阱）", "breakout", "多",
  "价格跌破前低却收在其上方,是空头陷阱。空头被套后回补会推动反弹。",
  "FBD{{N}}",
  "PL{{N}}:=REF(LLV(L,{{N}}),1);\nFBD{{N}}:=L<PL{{N}} AND C>PL{{N}};",
  "pl{{N}} = ta.lowest(low, {{N}})[1]\nfbd{{N}} = low < pl{{N}} and close > pl{{N}}",
  [P("N", "跌破回看K线数", 20, 3, 120)], ["15", "41"])

C("gap_up", "向上跳空缺口", "breakout", "多",
  "缺口是最强的突破形式之一。测量缺口出现在趋势运行 10-20 根K线后,"
  "往往意味着后面还有等距的测量移动。",
  "GUP",
  "GUP:=L>REF(H,1);",
  "gup = low > high[1]",
  [], ["11"])

C("gap_down", "向下跳空缺口", "breakout", "空",
  "向下的跳空缺口,空头强势的表现。",
  "GDN",
  "GDN:=H<REF(L,1);",
  "gdn = high < low[1]",
  [], ["11"])

C("gap_unfilled_up", "向上缺口未回补", "breakout", "多",
  "缺口没有被回补说明多头完全掌控,缺口成为后续回调的支撑。"
  "回补了则突破力度存疑。",
  "GUF{{N}}",
  "GUF{{N}}:=COUNT(L>REF(H,1),{{N}})>=1 AND LLV(L,{{N}})>REF(H,{{N}});",
  "guf{{N}} = ta.lowest(low, {{N}}) > high[{{N}}]",
  [P("N", "回补观察K线数", 10, 2, 60)], ["11"])

C("ma_gap_bar_up", "均线缺口K线（MAG·多）", "breakout", "多",
  "开盘价远高于 EMA 的K线,称均线缺口K线。说明市场急于离开均线,"
  "是强势突破的标志,常出现在趋势启动初期。",
  "MGB{{N}}_{{R}}",
  "EMAV{{N}}:=EMA(C,{{N}});\nMGB{{N}}_{{R}}:=O>EMAV{{N}}*(100+{{R}})/100;",
  "emav{{N}} = ta.ema(close, {{N}})\nmgb{{N}}_{{R}} = open > emav{{N}} * (100 + {{R}}) / 100",
  [P("N", "EMA周期", 20, 5, 120), P("R", "开盘高于均线的百分比", 1, 1, 10)], ["11", "15"])

# ============================================================ 回调
C("pullback_to_ema", "回调至 EMA 附近", "pullback", "多",
  "上涨趋势中最常见的做多点:价格回到均线附近但不破。课程里称为"
  "「首次回调至均线买入」。",
  "PBE{{N}}_{{T}}",
  "EMAV{{N}}:=EMA(C,{{N}});\nPBE{{N}}_{{T}}:=L<=EMAV{{N}}*(100+{{T}})/100 AND L>=EMAV{{N}}*(100-{{T}})/100;",
  "emav{{N}} = ta.ema(close, {{N}})\npbe{{N}}_{{T}} = low <= emav{{N}} * (100 + {{T}}) / 100 and low >= emav{{N}} * (100 - {{T}}) / 100",
  [P("N", "EMA周期", 20, 5, 120), P("T", "容差百分比", 1, 1, 10)], ["09", "19"])

C("rally_to_ema", "反弹至 EMA 附近", "pullback", "空",
  "下降趋势中价格反弹到均线附近受阻,是顺势做空点。",
  "RTE{{N}}_{{T}}",
  "EMAV{{N}}:=EMA(C,{{N}});\nRTE{{N}}_{{T}}:=H>=EMAV{{N}}*(100-{{T}})/100 AND H<=EMAV{{N}}*(100+{{T}})/100;",
  "emav{{N}} = ta.ema(close, {{N}})\nrte{{N}}_{{T}} = high >= emav{{N}} * (100 - {{T}}) / 100 and high <= emav{{N}} * (100 + {{T}}) / 100",
  [P("N", "EMA周期", 20, 5, 120), P("T", "容差百分比", 1, 1, 10)], ["09", "19"])

C("pullback_50", "回调至 50% 回撤位", "pullback", "多",
  "一波上涨后回调 50% 是最常见的支撑位,多头在此挂限价单。"
  "回调超过 50% 后趋势延续的概率开始下降。",
  "PB50{{N}}",
  "SWH{{N}}:=HHV(H,{{N}});\nSWL{{N}}:=LLV(L,{{N}});\n"
  "PB50{{N}}:=SWH{{N}}>SWL{{N}} AND L<=(SWH{{N}}+SWL{{N}})/2 AND L>=(SWH{{N}}+SWL{{N}})/2*0.{{T}};",
  "swh{{N}} = ta.highest(high, {{N}})\nswl{{N}} = ta.lowest(low, {{N}})\n"
  "pb50{{N}} = swh{{N}} > swl{{N}} and low <= (swh{{N}} + swl{{N}}) / 2 and low >= (swh{{N}} + swl{{N}}) / 2 * 0.{{T}}",
  [P("N", "波段回看K线数", 20, 5, 120), P("T", "下沿容差(%)", 97, 80, 99)], ["09", "19"])

C("shallow_pullback", "浅回调（趋势强劲）", "pullback", "多",
  "回调幅度不到前一波的 50%,说明多头急切,趋势强劲。"
  "强趋势中浅回调就是买点,等深回调会错过。",
  "SHP{{N}}",
  "SWH{{N}}:=HHV(H,{{N}});\nSWL{{N}}:=LLV(L,{{N}});\n"
  "SHP{{N}}:=SWH{{N}}>SWL{{N}} AND LLV(L,{{M}})>SWL{{N}}+(SWH{{N}}-SWL{{N}})*{{R}}/100;",
  "swh{{N}} = ta.highest(high, {{N}})\nswl{{N}} = ta.lowest(low, {{N}})\n"
  "shp{{N}} = swh{{N}} > swl{{N}} and ta.lowest(low, {{M}}) > swl{{N}} + (swh{{N}} - swl{{N}}) * {{R}} / 100",
  [P("N", "波段回看K线数", 20, 5, 120), P("M", "近期回调观察K线数", 5, 2, 30), P("R", "回撤下限(%)", 50, 10, 90)],
  ["09"])

C("deep_pullback", "深回调（趋势存疑）", "pullback", "中性",
  "回调跌破前一波的 50% 甚至回到起点,趋势延续概率降到接近 50%,"
  "市场更可能转入震荡区间。通常作为排除或减仓条件。",
  "DPP{{N}}",
  "SWH{{N}}:=HHV(H,{{N}});\nSWL{{N}}:=LLV(L,{{N}});\n"
  "DPP{{N}}:=SWH{{N}}>SWL{{N}} AND LLV(L,{{M}})<SWL{{N}}+(SWH{{N}}-SWL{{N}})*{{R}}/100;",
  "swh{{N}} = ta.highest(high, {{N}})\nswl{{N}} = ta.lowest(low, {{N}})\n"
  "dpp{{N}} = swh{{N}} > swl{{N}} and ta.lowest(low, {{M}}) < swl{{N}} + (swh{{N}} - swl{{N}}) * {{R}} / 100",
  [P("N", "波段回看K线数", 20, 5, 120), P("M", "近期回调观察K线数", 5, 2, 30), P("R", "回撤下限(%)", 50, 10, 90)],
  ["09", "18"])

C("two_legged_pullback", "两腿回调（TBTL）", "pullback", "多",
  "TBTL = Ten Bars Two Legs:持续 10 根K线以上、走出两段的下跌回调。"
  "第二段走完后反转的概率明显提高,是课程里的经典回调买入结构。",
  "TLP{{N}}",
  "TLP{{N}}:=BARSLAST(L=LLV(L,{{N}}))>={{M}} AND COUNT(L<REF(L,1),{{N}})>={{K}};",
  "tlp{{N}} = ta.barssince(low == ta.lowest(low, {{N}})) >= {{M}} and math.sum(low < low[1] ? 1 : 0, {{N}}) >= {{K}}",
  [P("N", "回看K线数", 20, 5, 60), P("M", "距最近低点的K线数", 5, 1, 30), P("K", "下跌K线数下限", 6, 2, 40)],
  ["09", "31"])

C("first_pullback_after_breakout", "突破后首次回调", "pullback", "多",
  "强劲突破之后的第一次回调最可能只是趋势中的暂停,是顺势入场的最佳窗口。"
  "第二次、第三次回调的成功率依次下降。",
  "FPB{{N}}",
  "FPB{{N}}:=BARSLAST(H>REF(HHV(H,{{N}}),1))>={{A}} AND BARSLAST(H>REF(HHV(H,{{N}}),1))<={{B}};",
  "fpb_bars{{N}} = ta.barssince(high > ta.highest(high, {{N}})[1])\nfpb{{N}} = fpb_bars{{N}} >= {{A}} and fpb_bars{{N}} <= {{B}}",
  [P("N", "突破回看K线数", 20, 3, 120), P("A", "突破后最少K线数", 1, 1, 30), P("B", "突破后最多K线数", 10, 2, 60)],
  ["09", "40"])

# ============================================================ 信号K线
C("bull_signal_bar", "看涨信号K线", "signalbar", "多",
  "信号K线是提示入场的那一根,入场K线是真正进场的那根,两者常常不是同一根。"
  "好的看涨信号K线:阳线、收盘接近最高、实体饱满。",
  "BSIG{{N}}_{{K}}",
  "ABODY{{N}}:=MA(ABS(C-O),{{N}});\n"
  "BSIG{{N}}_{{K}}:=C>O AND (C-L)>(H-L)*0.{{R}} AND ABS(C-O)>ABODY{{N}}*{{K}}/10;",
  "abody{{N}} = ta.sma(math.abs(close - open), {{N}})\n"
  "bsig{{N}}_{{K}} = close > open and (close - low) > (high - low) * 0.{{R}} and math.abs(close - open) > abody{{N}} * {{K}} / 10",
  [P("N", "平均实体回看", 20, 5, 60), P("K", "实体倍数×10", 12, 5, 40), P("R", "收盘位置下限(%)", 60, 50, 95)],
  ["08"])

C("bear_signal_bar", "看跌信号K线", "signalbar", "空",
  "好的看跌信号K线:阴线、收盘接近最低、实体饱满。",
  "SSIG{{N}}_{{K}}",
  "ABODY{{N}}:=MA(ABS(C-O),{{N}});\n"
  "SSIG{{N}}_{{K}}:=C<O AND (H-C)>(H-L)*0.{{R}} AND ABS(C-O)>ABODY{{N}}*{{K}}/10;",
  "abody{{N}} = ta.sma(math.abs(close - open), {{N}})\n"
  "ssig{{N}}_{{K}} = close < open and (high - close) > (high - low) * 0.{{R}} and math.abs(close - open) > abody{{N}} * {{K}} / 10",
  [P("N", "平均实体回看", 20, 5, 60), P("K", "实体倍数×10", 12, 5, 40), P("R", "收盘位置下限(%)", 60, 50, 95)],
  ["08"])

C("bull_reversal_bar", "看涨反转K线（长下影）", "signalbar", "多",
  "下影线长、收盘接近最高——下方有买盘把价格推回。"
  "在有利背景下,最好的信号K线就是这种反转K线。",
  "BREV{{R}}",
  "BREV{{R}}:=H>L AND (MIN(C,O)-L)/(H-L)>{{R}}/100 AND (C-L)/(H-L)>{{S}}/100;",
  "brev{{R}} = high > low and (math.min(close, open) - low) / (high - low) > {{R}} / 100 and (close - low) / (high - low) > {{S}} / 100",
  [P("R", "下影占K线区间下限(%)", 30, 10, 80), P("S", "收盘位置下限(%)", 60, 50, 95)], ["08"])

C("bear_reversal_bar", "看跌反转K线（长上影）", "signalbar", "空",
  "上影线长、收盘接近最低——上方有卖盘压回。",
  "SREV{{R}}",
  "SREV{{R}}:=H>L AND (H-MAX(C,O))/(H-L)>{{R}}/100 AND (H-C)/(H-L)>{{S}}/100;",
  "srev{{R}} = high > low and (high - math.max(close, open)) / (high - low) > {{R}} / 100 and (high - close) / (high - low) > {{S}} / 100",
  [P("R", "上影占K线区间下限(%)", 30, 10, 80), P("S", "收盘位置下限(%)", 60, 50, 95)], ["08"])

C("doji", "十字星（单根K线的区间）", "signalbar", "中性",
  "实体极小的K线,本质是单根K线的震荡区间,代表多空僵持、方向不明。"
  "连续十字星往往构成稍大的震荡区间。",
  "DOJI{{R}}",
  "DOJI{{R}}:=H>L AND ABS(C-O)/(H-L)<{{R}}/100;",
  "doji{{R}} = high > low and math.abs(close - open) / (high - low) < {{R}} / 100",
  [P("R", "实体占K线区间上限(%)", 20, 5, 50)], ["08"])

C("inside_bar", "孕线（inside bar）", "signalbar", "中性",
  "高低点都被前一根K线包住,说明市场在休息、波动收缩。"
  "孕线常是突破前的蓄势,方向由后续突破决定。",
  "INSB",
  "INSB:=H<REF(H,1) AND L>REF(L,1);",
  "insb = high < high[1] and low > low[1]",
  [], ["08"])

C("outside_bar", "外包K线（outside bar）", "signalbar", "中性",
  "高低点都包住了前一根K线,波动放大。出现在趋势末端常是高潮或反转信号。",
  "OUTB",
  "OUTB:=H>REF(H,1) AND L<REF(L,1);",
  "outb = high > high[1] and low < low[1]",
  [], ["08"])

C("consecutive_bull_bars", "连续阳线", "signalbar", "多",
  "连续 N 根阳线,动量确认。课程里常以「连续三根阳线收在高位」作为强势突破的判据。",
  "CBB{{N}}",
  "CBB{{N}}:=EVERY(C>O,{{N}});",
  "cbb{{N}} = ta.barssince(not (close > open)) > {{N}}",
  [P("N", "连续K线数", 3, 2, 15)], ["08", "13"])

C("consecutive_bear_bars", "连续阴线", "signalbar", "空",
  "连续 N 根阴线收在低位,空头动量的确认。",
  "CBR{{N}}",
  "CBR{{N}}:=EVERY(C<O,{{N}});",
  "cbr{{N}} = ta.barssince(not (close < open)) > {{N}}",
  [P("N", "连续K线数", 3, 2, 15)], ["08", "13"])

C("close_near_high", "收盘接近最高", "signalbar", "多",
  "收盘价位于K线区间的上 R%,说明买盘在收盘前仍掌控。",
  "CNH{{R}}",
  "CNH{{R}}:=H>L AND (C-L)/(H-L)>={{R}}/100;",
  "cnh{{R}} = high > low and (close - low) / (high - low) >= {{R}} / 100",
  [P("R", "收盘位置下限(%)", 70, 50, 100)], ["08"])

C("close_near_low", "收盘接近最低", "signalbar", "空",
  "收盘价位于K线区间的下 R%,卖盘掌控。",
  "CNL{{R}}",
  "CNL{{R}}:=H>L AND (H-C)/(H-L)>={{R}}/100;",
  "cnl{{R}} = high > low and (high - close) / (high - low) >= {{R}} / 100",
  [P("R", "收盘位置下限(%)", 70, 50, 100)], ["08"])

# ============================================================ 形态结构
C("double_bottom", "双底", "pattern", "多",
  "两个低点大致在同一水平。第二底常略微跌破第一底形成空头陷阱,"
  "失败后反转向上。双底是课程里最常见的反转入场形态之一。",
  "DBOT{{N}}",
  "DBOT{{N}}:=ABS(LLV(L,{{N}})-REF(LLV(L,{{N}}),{{N}}))/LLV(L,{{N}})<{{T}}/100 AND L<=LLV(L,{{N}})*1.0{{S}};",
  "db_l1{{N}} = ta.lowest(low, {{N}})\ndb_l2{{N}} = ta.lowest(low, {{N}})[{{N}}]\ndbot{{N}} = math.abs(db_l1{{N}} - db_l2{{N}}) / db_l1{{N}} < {{T}} / 100 and low <= db_l1{{N}} * 1.0{{S}}",
  [P("N", "半段回看K线数", 20, 5, 60), P("T", "两底差异容差(%)", 2, 1, 10), P("S", "触及底部的容差(%)", 3, 1, 10)],
  ["25"])

C("double_top", "双顶", "pattern", "空",
  "两个高点大致在同一水平,第二顶常略微突破形成多头陷阱后失败。",
  "DTOP{{N}}",
  "DTOP{{N}}:=ABS(HHV(H,{{N}})-REF(HHV(H,{{N}}),{{N}}))/HHV(H,{{N}})<{{T}}/100 AND H>=HHV(H,{{N}})*0.{{S}};",
  "dt_h1{{N}} = ta.highest(high, {{N}})\ndt_h2{{N}} = ta.highest(high, {{N}})[{{N}}]\ndtop{{N}} = math.abs(dt_h1{{N}} - dt_h2{{N}}) / dt_h1{{N}} < {{T}} / 100 and high >= dt_h1{{N}} * 0.{{S}}",
  [P("N", "半段回看K线数", 20, 5, 60), P("T", "两顶差异容差(%)", 2, 1, 10), P("S", "触及顶部的容差(%)", 97, 90, 99)],
  ["25"])

C("head_shoulders_bottom", "头肩底", "pattern", "多",
  "左肩—头—右肩,颈线被突破时确认。课程提醒:形态刚出现时概率并不高,"
  "要等颈线突破和跟随K线确认。",
  "HSB{{N}}",
  "HSB{{N}}:=LLV(L,{{N}})<REF(LLV(L,{{N}}),{{N}}) AND LLV(L,{{N}})<REF(LLV(L,{{N}}),{{N}}*2) AND C>EMA(C,{{E}});",
  "hsb{{N}} = ta.lowest(low, {{N}}) < ta.lowest(low, {{N}})[{{N}}] and ta.lowest(low, {{N}}) < ta.lowest(low, {{N}})[{{N}} * 2] and close > ta.ema(close, {{E}})",
  [P("N", "每段回看K线数", 20, 5, 60), P("E", "EMA周期", 20, 5, 120)], ["27"])

C("bull_flag", "牛旗（紧凑回调）", "pattern", "多",
  "强势突破后,价格以小幅、向下倾斜的窄通道整理,像一面旗子。"
  "牛旗是趋势延续形态,突破旗形上沿是顺势做多点。",
  "BFLG{{N}}",
  "BFLG{{N}}:=EVERY(H<=REF(H,1),{{M}}) AND COUNT(C<REF(C,1),{{M}})>={{K}} AND C>EMA(C,{{E}});",
  "bflg{{N}} = ta.barssince(high > high[1]) > {{M}} and math.sum(close < close[1] ? 1 : 0, {{M}}) >= {{K}} and close > ta.ema(close, {{E}})",
  [P("M", "旗形K线数", 5, 2, 20), P("K", "其中下跌K线数", 3, 1, 20), P("E", "EMA周期", 20, 5, 120)],
  ["16", "23"])

C("bear_flag", "熊旗（紧凑反弹）", "pattern", "空",
  "下跌后的小幅向上整理,跌破旗形下沿是顺势做空点。",
  "SFLG{{N}}",
  "SFLG{{N}}:=EVERY(L>=REF(L,1),{{M}}) AND COUNT(C>REF(C,1),{{M}})>={{K}} AND C<EMA(C,{{E}});",
  "sflg{{N}} = ta.barssince(low < low[1]) > {{M}} and math.sum(close > close[1] ? 1 : 0, {{M}}) >= {{K}} and close < ta.ema(close, {{E}})",
  [P("M", "旗形K线数", 5, 2, 20), P("K", "其中上涨K线数", 3, 1, 20), P("E", "EMA周期", 20, 5, 120)],
  ["16", "23"])

C("wedge_bottom", "楔形底", "pattern", "多",
  "下跌末端的收敛楔形,常表现为三推结构。楔形是趋势末端的形态,"
  "突破楔形上沿往往启动反向运动。",
  "WEDB{{N}}",
  "WEDB{{N}}:=LLV(L,{{N}})<REF(LLV(L,{{N}}),{{N}}) AND HHV(H,{{N}})<REF(HHV(H,{{N}}),{{N}}) AND (HHV(H,{{N}})-LLV(L,{{N}}))<(REF(HHV(H,{{N}}),{{N}})-REF(LLV(L,{{N}}),{{N}}));",
  "wedb{{N}} = ta.lowest(low, {{N}}) < ta.lowest(low, {{N}})[{{N}}] and ta.highest(high, {{N}}) < ta.highest(high, {{N}})[{{N}}] and (ta.highest(high, {{N}}) - ta.lowest(low, {{N}})) < (ta.highest(high, {{N}})[{{N}}] - ta.lowest(low, {{N}})[{{N}}])",
  [P("N", "半段回看K线数", 20, 5, 60)], ["24"])

C("wedge_top", "楔形顶", "pattern", "空",
  "上涨末端的收敛楔形,三推后常出现反转。",
  "WEDT{{N}}",
  "WEDT{{N}}:=HHV(H,{{N}})>REF(HHV(H,{{N}}),{{N}}) AND LLV(L,{{N}})>REF(LLV(L,{{N}}),{{N}}) AND (HHV(H,{{N}})-LLV(L,{{N}}))<(REF(HHV(H,{{N}}),{{N}})-REF(LLV(L,{{N}}),{{N}}));",
  "wedt{{N}} = ta.highest(high, {{N}}) > ta.highest(high, {{N}})[{{N}}] and ta.lowest(low, {{N}}) > ta.lowest(low, {{N}})[{{N}}] and (ta.highest(high, {{N}}) - ta.lowest(low, {{N}})) < (ta.highest(high, {{N}})[{{N}}] - ta.lowest(low, {{N}})[{{N}}])",
  [P("N", "半段回看K线数", 20, 5, 60)], ["24"])

C("triangle_converge", "三角形收敛", "pattern", "中性",
  "高点下移、低点上移的收敛结构,可看作含三腿以上的回调。"
  "三角形方向不明,是突破前的蓄势,等待方向选择。",
  "TRIA{{N}}",
  "TRIA{{N}}:=HHV(H,{{N}})<REF(HHV(H,{{N}}),{{N}}) AND LLV(L,{{N}})>REF(LLV(L,{{N}}),{{N}});",
  "tria{{N}} = ta.highest(high, {{N}}) < ta.highest(high, {{N}})[{{N}}] and ta.lowest(low, {{N}}) > ta.lowest(low, {{N}})[{{N}}]",
  [P("N", "半段回看K线数", 20, 5, 60)], ["26"])

C("terminal_flag", "末端旗形", "pattern", "空",
  "趋势末端出现的旗形,形似延续实为反转。课程把末端旗形归类为反转形态——"
  "看似要继续上涨,实际是最后的出货。",
  "TFLG{{N}}",
  "TFLG{{N}}:=COUNT(H>REF(H,1),{{N}})>={{K}} AND HHV(H,{{N}})>REF(HHV(H,{{N}}),{{N}}) AND (HHV(H,{{N}})-LLV(L,{{N}}))<REF(HHV(H,{{N}})-LLV(L,{{N}}),{{N}});",
  "tflg{{N}} = math.sum(high > high[1] ? 1 : 0, {{N}}) >= {{K}} and ta.highest(high, {{N}}) > ta.highest(high, {{N}})[{{N}}]",
  [P("N", "回看K线数", 10, 5, 40), P("K", "其中上涨K线数", 6, 2, 40)], ["23"])

C("measured_move_up_target", "等距测量目标（多）", "pattern", "多",
  "MM:从起涨点到第一段高点的距离,向上翻一倍就是测量目标。"
  "课程里最常用的目标位算法,也是盈亏比的计算基础。",
  "MMU{{N}}",
  "MMU{{N}}:=C>LLV(L,{{N}})+(HHV(H,{{N}})-LLV(L,{{N}})) AND HHV(H,{{N}})>LLV(L,{{N}});",
  "mmu{{N}} = close > ta.lowest(low, {{N}}) + (ta.highest(high, {{N}}) - ta.lowest(low, {{N}})) and ta.highest(high, {{N}}) > ta.lowest(low, {{N}})",
  [P("N", "测量段回看K线数", 20, 5, 120)], ["20"])

# ============================================================ 高潮
C("selling_climax", "抛售高潮", "climax", "多",
  "连续多根大阴线、收盘都在低位,伴随放量——空头最后一次集中宣泄。"
  "抛售高潮后通常至少有两段反弹,是反转交易的触发条件。",
  "SCL{{N}}",
  "ABODY{{N}}:=MA(ABS(C-O),{{N}});\n"
  "SCL{{N}}:=COUNT(C<O AND (H-C)/(H-L)>0.{{R}},{{M}})>={{K}} AND V>MA(V,{{N}});",
  "abody{{N}} = ta.sma(math.abs(close - open), {{N}})\n"
  "scl{{N}} = math.sum((close < open and (high - close) / (high - low) > 0.{{R}}) ? 1 : 0, {{M}}) >= {{K}} and volume > ta.sma(volume, {{N}})",
  [P("N", "量能均值回看", 20, 5, 60), P("M", "高潮观察K线数", 3, 2, 15), P("K", "其中大阴线数", 3, 2, 15), P("R", "收盘位置下限(%)", 70, 50, 95)],
  ["29", "42"])

C("buying_climax", "买入高潮", "climax", "空",
  "连续多根大阳线、放量,多头最后的疯狂。之后通常至少有两段下跌。",
  "BCL{{N}}",
  "BCL{{N}}:=COUNT(C>O AND (C-L)/(H-L)>0.{{R}},{{M}})>={{K}} AND V>MA(V,{{N}});",
  "bcl{{N}} = math.sum((close > open and (close - low) / (high - low) > 0.{{R}}) ? 1 : 0, {{M}}) >= {{K}} and volume > ta.sma(volume, {{N}})",
  [P("N", "量能均值回看", 20, 5, 60), P("M", "高潮观察K线数", 3, 2, 15), P("K", "其中大阳线数", 3, 2, 15), P("R", "收盘位置下限(%)", 70, 50, 95)],
  ["29", "42"])

C("climax_reversal_bar_bull", "高潮后看涨反转K线", "climax", "多",
  "抛售高潮之后出现收在高位的阳线或多头反转K线——这是从「可能反转」"
  "到「确认反转」的关键一根。",
  "CRB{{R}}",
  "CRB{{R}}:=C>O AND (C-L)/(H-L)>{{R}}/100 AND C>REF(C,1);",
  "crb{{R}} = close > open and (close - low) / (high - low) > {{R}} / 100 and close > close[1]",
  [P("R", "收盘位置下限(%)", 70, 50, 95)], ["29", "42"])

C("climax_reversal_bar_bear", "高潮后看跌反转K线", "climax", "空",
  "买入高潮之后出现收在低位的大阴线,确认反转向下。",
  "CRS{{R}}",
  "CRS{{R}}:=C<O AND (H-C)/(H-L)>{{R}}/100 AND C<REF(C,1);",
  "crs{{R}} = close < open and (high - close) / (high - low) > {{R}} / 100 and close < close[1]",
  [P("R", "收盘位置下限(%)", 70, 50, 95)], ["29", "42"])

# ============================================================ 量能
C("volume_surge", "放量", "volume", "中性",
  "成交量超过近 N 日均量的 K/10 倍（默认 1.5 倍）。突破需要成交量配合,缩量突破更容易失败。",
  "VSUR{{N}}_{{K}}",
  "VSUR{{N}}_{{K}}:=V>MA(V,{{N}})*{{K}}/10;",
  "vsur{{N}}_{{K}} = volume > ta.sma(volume, {{N}}) * {{K}} / 10",
  [P("N", "均量回看", 20, 5, 60), P("K", "放量倍数×10", 15, 10, 50)], ["29"])

C("volume_dry", "缩量", "volume", "中性",
  "成交量低于均量的 K/10（默认 0.8 倍）,市场观望。缩量回调比放量回调更像健康的趋势休整。",
  "VDRY{{N}}_{{K}}",
  "VDRY{{N}}_{{K}}:=V<MA(V,{{N}})*{{K}}/10;",
  "vdry{{N}}_{{K}} = volume < ta.sma(volume, {{N}}) * {{K}} / 10",
  [P("N", "均量回看", 20, 5, 60), P("K", "缩量比例×10", 8, 1, 10)], ["29"])

# ============================================================ 风险与盈亏比
C("rr_above_2", "盈亏比 ≥ 2 倍", "risk", "中性",
  "课程的最低要求:潜在盈利至少是风险的 2 倍,否则数学期望为负。"
  "目标位用等距测量移动或前高估算。",
  "RR{{N}}",
  _ATR_TDX + "\nRR{{N}}:=(HHV(H,{{N}})-C)/(ATRV{{N}}+0.0001)>={{K}};",
  _ATR_PINE + "\nrr{{N}} = (ta.highest(high, {{N}}) - close) / (atr{{N}} + 0.0001) >= {{K}}",
  [P("N", "目标位回看K线数", 20, 5, 120), P("K", "盈亏比下限", 2, 1, 10)], ["30", "34"])

C("stop_distance_ok", "止损距离合理", "risk", "中性",
  "止损放在信号K线低点下方。若这个距离超过 2 倍 ATR,说明止损太远、"
  "盈亏比被吃掉,应当缩小仓位或放弃。",
  "SDOK{{N}}",
  _ATR_TDX + "\nSDOK{{N}}:=(C-LLV(L,{{M}}))/(ATRV{{N}}+0.0001)<={{K}};",
  _ATR_PINE + "\nsdok{{N}} = (close - ta.lowest(low, {{M}})) / (atr{{N}} + 0.0001) <= {{K}}",
  [P("N", "ATR周期", 20, 5, 60), P("M", "止损参考低点回看", 3, 1, 20), P("K", "止损距离ATR倍数上限", 2, 1, 5)],
  ["33", "34"])

C("low_volatility", "低波动率（避免乱跳）", "risk", "中性",
  "ATR 占价格比例过高时,K线跳动剧烈、止损容易被扫。作为过滤条件使用。",
  "LVOL{{N}}",
  _ATR_TDX + "\nLVOL{{N}}:=ATRV{{N}}<MA(C,{{N}})*{{R}}/100;",
  _ATR_PINE + "\nlvol{{N}} = atr{{N}} < ta.sma(close, {{N}}) * {{R}} / 100",
  [P("N", "ATR周期", 20, 5, 60), P("R", "ATR占价格百分比上限", 5, 1, 20)], ["34"])

# ============================================================ 开盘与早盘
C("open_gap_up", "高开", "open", "多",
  "开盘价高于前一日最高价。早盘的开盘缺口常常不会被回补,"
  "是当天方向的重要线索。",
  "OGU",
  "OGU:=O>REF(H,1);",
  "ogu = open > high[1]",
  [], ["48"])

C("open_gap_down", "低开", "open", "空",
  "开盘价低于前一日最低价,空头开局占优。",
  "OGD",
  "OGD:=O<REF(L,1);",
  "ogd = open < low[1]",
  [], ["48"])

C("open_strong_bar", "开盘首根K线强势", "open", "中性",
  "开盘第一根K线实体饱满、收在高位。早盘的方向常常决定当天的交易基调。",
  "OSB{{R}}",
  "OSB{{R}}:=H>L AND (C-L)/(H-L)>{{R}}/100 AND ABS(C-O)/(H-L)>{{S}}/100;",
  "osb{{R}} = high > low and (close - low) / (high - low) > {{R}} / 100 and math.abs(close - open) / (high - low) > {{S}} / 100",
  [P("R", "收盘位置下限(%)", 65, 50, 95), P("S", "实体占K线区间下限(%)", 40, 10, 90)], ["48"])

C("open_in_range", "开盘价位于昨日区间内", "open", "中性",
  "开盘既没有高于昨高也没有低于昨低,属于常规开盘,早盘方向需再观察。",
  "OIR",
  "OIR:=O<=REF(H,1) AND O>=REF(L,1);",
  "oir = open <= high[1] and open >= low[1]",
  [], ["48"])


def by_id(cid: str) -> dict | None:
    for c in CONDITIONS:
        if c["id"] == cid:
            return c
    return None
