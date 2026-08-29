"""通达信公式子集求值器（纯 Python，零依赖）。

为什么要自己写：工作台里展示的选股公式是通达信语法，如果监控引擎另写一套 Python 判断，
两边迟早会漂移——界面显示 A 条件，实际跑的是 B 逻辑。这里直接执行**同一串表达式**，
做到「看到什么就跑什么」。

支持的语法（覆盖 model_conditions.py 里用到的全部）：
  行情变量  O H L C V（大小写都行）
  函数      EMA MA HHV LLV REF ABS MAX MIN SUM COUNT EVERY BARSLAST CROSS BETWEEN IF
  运算      + - * /  > < >= <= =  AND OR NOT
  语句      NAME:=表达式;  以分号分隔，按序求值，后面的语句可以引用前面的变量

所有中间值都是「序列」（list），下标 0 是 earliest bar。取信号时看最后一根。
"""

from __future__ import annotations

import re

# ------------------------------------------------------------------ 词法

TOKEN_RE = re.compile(r"""
    \s+
  | (?P<num>\d+\.\d+|\.\d+|\d+)
  | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<op>>=|<=|<>|[+\-*/()<>=,;])
""", re.VERBOSE)

KEYWORDS = {"AND", "OR", "NOT"}


def tokenize(src: str):
    pos, out = 0, []
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise SyntaxError(f"无法识别的字符 at {pos}: {src[pos:pos + 12]!r}")
        pos = m.end()
        # lastgroup 为 None 表示匹配到的是模式里第一条 `\s+`（空白）。
        # 必须跳过：否则空白会变成 ('op', None)，解析到空格就停下，
        # 像 `C>O AND X` 会被静默截断成 `C>O` —— 不报错但结果是错的。
        if m.lastgroup is None:
            continue
        if m.lastgroup == "num":
            out.append(("num", float(m.group("num"))))
        elif m.lastgroup == "name":
            nm = m.group("name")
            out.append(("kw", nm) if nm.upper() in KEYWORDS else ("name", nm))
        else:
            out.append(("op", m.group("op")))
    out.append(("end", ""))
    return out


# ------------------------------------------------------------------ 语法树

class Node:
    __slots__ = ("kind", "val", "kids")

    def __init__(self, kind, val=None, kids=None):
        self.kind, self.val, self.kids = kind, val, kids or []


FUNCS = {
    "EMA", "MA", "HHV", "LLV", "REF", "ABS", "MAX", "MIN",
    "SUM", "COUNT", "EVERY", "BARSLAST", "CROSS", "BETWEEN", "IF",
}


class Parser:
    """递归下降。优先级从低到高：OR < AND < NOT < 比较 < 加减 < 乘除 < 一元 < 原子。"""

    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def peek(self):
        return self.toks[self.i]

    def eat(self, kind=None, val=None):
        t = self.toks[self.i]
        if kind and t[0] != kind:
            raise SyntaxError(f"期望 {kind}，实际 {t}")
        if val is not None and t[1] != val:
            raise SyntaxError(f"期望 {val!r}，实际 {t[1]!r}")
        self.i += 1
        return t

    def parse(self):
        n = self.or_expr()
        return n

    def or_expr(self):
        left = self.and_expr()
        while self.peek()[0] == "kw" and self.peek()[1] == "OR":
            self.eat(); left = Node("or", None, [left, self.and_expr()])
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.peek()[0] == "kw" and self.peek()[1] == "AND":
            self.eat(); left = Node("and", None, [left, self.not_expr()])
        return left

    def not_expr(self):
        if self.peek()[0] == "kw" and self.peek()[1] == "NOT":
            self.eat(); return Node("not", None, [self.not_expr()])
        return self.cmp_expr()

    def cmp_expr(self):
        left = self.add_expr()
        while self.peek()[0] == "op" and self.peek()[1] in (">", "<", ">=", "<=", "="):
            op = self.eat()[1]
            left = Node("cmp", op, [left, self.add_expr()])
        return left

    def add_expr(self):
        left = self.mul_expr()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.eat()[1]
            left = Node("arith", op, [left, self.mul_expr()])
        return left

    def mul_expr(self):
        left = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            op = self.eat()[1]
            left = Node("arith", op, [left, self.unary()])
        return left

    def unary(self):
        if self.peek()[0] == "op" and self.peek()[1] in ("-", "+"):
            op = self.eat()[1]
            return Node("unary", op, [self.unary()])
        return self.atom()

    def atom(self):
        t = self.peek()
        if t[0] == "num":
            self.eat(); return Node("num", t[1])
        if t[0] == "op" and t[1] == "(":
            self.eat("op", "(")
            n = self.or_expr()
            self.eat("op", ")")
            return n
        if t[0] == "name":
            nm = self.eat()[1].upper()
            if self.peek()[0] == "op" and self.peek()[1] == "(":
                self.eat("op", "(")
                args = [self.or_expr()]
                while self.peek()[0] == "op" and self.peek()[1] == ",":
                    self.eat("op", ","); args.append(self.or_expr())
                self.eat("op", ")")
                return Node("call", nm, args)
            return Node("var", nm)
        raise SyntaxError(f"意外的 token {t}")


# ------------------------------------------------------------------ 序列工具

def _f(x):
    """把标量或序列统一成 float 序列。"""
    if isinstance(x, list):
        return [1.0 if v is True else (0.0 if v is False else float(v)) for v in x]
    return [1.0 if x is True else (0.0 if x is False else float(x))]


def _b(x):
    """把标量或序列统一成 bool 序列。"""
    if isinstance(x, list):
        return [bool(v) for v in x]
    return [bool(x)]


def _zip2(a, b, fn):
    a, b = _f(a), _f(b)
    if len(a) == 1 and len(b) > 1:
        a = a * len(b)
    if len(b) == 1 and len(a) > 1:
        b = b * len(a)
    n = min(len(a), len(b))
    return [fn(a[i], b[i]) for i in range(n)]


def _safe(d):
    return d if d else 1e-12


def _period(x) -> int:
    """周期参数可能是标量，也可能是 `{{N}}*2` 这类常量表达式。

    常量表达式求值后是长度 1 的序列，必须取出来转 int，
    否则 `REF(X, 20*2)` 会因为 int([40.0]) 直接抛 TypeError。
    """
    if isinstance(x, list):
        if not x:
            raise ValueError("周期参数为空")
        x = x[-1]
    try:
        n = int(round(float(x)))
    except (TypeError, ValueError) as e:
        raise ValueError(f"周期参数无法转成整数：{x!r}") from e
    if n < 1:
        raise ValueError(f"周期参数必须 >= 1，实际 {n}")
    return n


def ema(x, n):
    """通达信 EMA：Y=(2*X+(N-1)*Y')/(N+1)，首值以 X[0] 作种子。"""
    x, n = _f(x), _period(n)
    if not x:
        return x
    k = 2.0 / (n + 1)
    out, prev = [], x[0]
    for v in x:
        prev = k * v + (1 - k) * prev
        out.append(prev)
    return out


def ma(x, n):
    x, n = _f(x), _period(n)
    out, s = [], 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        out.append(s / min(i + 1, n))
    return out


def hhv(x, n):
    x, n = _f(x), _period(n)
    return [max(x[max(0, i - n + 1):i + 1]) for i in range(len(x))]


def llv(x, n):
    x, n = _f(x), _period(n)
    return [min(x[max(0, i - n + 1):i + 1]) for i in range(len(x))]


def ref(x, n):
    x, n = _f(x), _period(n)
    if n == 0:
        return list(x)
    return [x[i - n] if i - n >= 0 else x[0] for i in range(len(x))]


def ssum(x, n):
    x, n = _f(x), _period(n)
    return [sum(x[max(0, i - n + 1):i + 1]) for i in range(len(x))]


def count(cond, n):
    c, n = _b(cond), _period(n)
    return [float(sum(1 for v in c[max(0, i - n + 1):i + 1] if v)) for i in range(len(c))]


def every(cond, n):
    c, n = _b(cond), _period(n)
    return [all(c[max(0, i - n + 1):i + 1]) for i in range(len(c))]


def barslast(cond):
    c = _b(cond)
    out, last = [], None
    for i, v in enumerate(c):
        if v:
            last = i
        out.append(float(i - last) if last is not None else float(len(c)))
    return out


def cross(a, b):
    """金叉：上一根 a<=b 且本根 a>b。"""
    a, b = _f(a), _f(b)
    n = min(len(a), len(b))
    out = [False] * n
    for i in range(1, n):
        out[i] = a[i - 1] <= b[i - 1] and a[i] > b[i]
    return out


def _call(name, args, ctx):
    if name == "EMA":
        return ema(args[0], args[1])
    if name == "MA":
        return ma(args[0], args[1])
    if name == "SMA":
        return ema(args[0], args[1])
    if name == "HHV":
        return hhv(args[0], args[1])
    if name == "LLV":
        return llv(args[0], args[1])
    if name == "REF":
        return ref(args[0], args[1])
    if name == "ABS":
        return [abs(v) for v in _f(args[0])]
    if name == "MAX":
        return _zip2(args[0], args[1], max)
    if name == "MIN":
        return _zip2(args[0], args[1], min)
    if name == "SUM":
        return ssum(args[0], args[1])
    if name == "COUNT":
        return count(args[0], args[1])
    if name == "EVERY":
        return every(args[0], args[1])
    if name == "BARSLAST":
        return barslast(args[0])
    if name == "CROSS":
        return cross(args[0], args[1])
    if name == "BETWEEN":
        x, lo, hi = args[0], args[1], args[2]
        return _zip2(_zip2(x, lo, lambda a, b: a >= b), _zip2(x, hi, lambda a, b: a <= b),
                     lambda a, b: 1.0 if (a and b) else 0.0)
    if name == "IF":
        c, a, b = _b(args[0]), _f(args[1]), _f(args[2])
        n = min(len(c), len(a), len(b))
        return [a[i] if c[i] else b[i] for i in range(n)]
    raise ValueError(f"不支持的函数 {name}")


# ------------------------------------------------------------------ 求值

def evaluate(node, ctx):
    k = node.kind
    if k == "num":
        return node.val
    if k == "var":
        nm = node.val
        if nm in ctx:
            return ctx[nm]
        # 公式里行情变量是大写 O/H/L/C/V，行情字典用的是小写键
        if nm in ("O", "H", "L", "C", "V") and nm.lower() in ctx:
            return ctx[nm.lower()]
        raise ValueError(f"未定义的变量 {nm}")
    if k == "call":
        return _call(node.val, [evaluate(a, ctx) for a in node.kids], ctx)
    if k == "arith":
        a = evaluate(node.kids[0], ctx)
        b = evaluate(node.kids[1], ctx)
        op = node.val
        fn = {"+": lambda x, y: x + y, "-": lambda x, y: x - y,
              "*": lambda x, y: x * y, "/": lambda x, y: x / _safe(y)}[op]
        return _zip2(a, b, fn)
    if k == "cmp":
        a = evaluate(node.kids[0], ctx)
        b = evaluate(node.kids[1], ctx)
        op = node.val
        fn = {">": lambda x, y: x > y, "<": lambda x, y: x < y,
              ">=": lambda x, y: x >= y, "<=": lambda x, y: x <= y,
              "=": lambda x, y: x == y}[op]
        return _zip2(a, b, fn)
    if k == "and":
        return _zip2(_b(evaluate(node.kids[0], ctx)), _b(evaluate(node.kids[1], ctx)),
                     lambda x, y: 1.0 if (x and y) else 0.0)
    if k == "or":
        return _zip2(_b(evaluate(node.kids[0], ctx)), _b(evaluate(node.kids[1], ctx)),
                     lambda x, y: 1.0 if (x or y) else 0.0)
    if k == "not":
        return [0.0 if v else 1.0 for v in _b(evaluate(node.kids[0], ctx))]
    if k == "unary":
        v = _f(evaluate(node.kids[0], ctx))
        return [-x for x in v] if node.val == "-" else v
    raise ValueError(f"未知节点 {k}")


def parse_expr(src: str) -> Node:
    """解析完整表达式，并强制消费到结尾。

    少了这个检查，语法只被吃掉一半时不会报错，只会静默返回前半段结果——
    这类错误在回测里极难发现，所以在这里直接拦死。
    """
    toks = tokenize(src)
    p = Parser(toks)
    node = p.parse()
    if p.peek()[0] != "end":
        raise SyntaxError(f"表达式在 {p.i} 处提前结束，剩余：{[t for t in toks[p.i:]]}")
    return node


def run_statements(body: str, bars: dict) -> dict:
    """执行一段通达信语句（`A:=...;B:=...;`），返回所有变量的值。

    bars 形如 {'O':[...], 'H':[...], 'L':[...], 'C':[...], 'V':[...]}
    """
    ctx = {k: list(v) for k, v in bars.items()}
    for stmt in body.split(";"):
        stmt = stmt.strip()
        if not stmt or ":=" not in stmt:
            continue
        name, expr = stmt.split(":=", 1)
        name = name.strip().upper()
        # 过滤掉 `{...}` 注释块
        expr = re.sub(r"\{[^}]*\}", "", expr).strip()
        if not expr:
            continue
        ctx[name] = evaluate(parse_expr(expr), ctx)
    return ctx


def last_true(value) -> bool:
    """取序列最后一根作为信号；标量直接当布尔。"""
    if isinstance(value, list):
        return bool(value[-1]) if value else False
    return bool(value)
