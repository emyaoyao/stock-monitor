from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE = "https://www.sse.com.cn/disclosure/dealinstruc/closed/"
PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent.parent if PACKAGE_DIR.parent.name == "work" else PACKAGE_DIR.parent
CACHE = ROOT / "outputs" / "market_calendar.json"
NEXT_RETRY: dict[int, float] = {}


def _ranges(rows: list[list[str]], year: int) -> list[tuple[date, date]]:
    ranges = []
    for cells in rows:
        if len(cells) < 2 or "休市" not in cells[1]:
            continue
        text = cells[1].split("休市", 1)[0]
        matches = re.findall(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", text)
        if not matches:
            continue
        first, last = matches[0], matches[-1]
        start = date(int(first[0] or year), int(first[1]), int(first[2]))
        end = date(int(last[0] or year), int(last[1]), int(last[2]))
        if end < start and not first[0] and not last[0] and start.month == 12 and end.month == 1:
            start = date(year - 1, start.month, start.day)
        ranges.append((start, end))
    if not 5 <= len(ranges) <= 10 or any(start > end or (end - start).days > 15 for start, end in ranges):
        raise ValueError("交易所年度休市表不完整")
    return ranges


def parse_calendar(page: str, year: int) -> list[tuple[date, date]]:
    heading = re.search(rf"{year}\s*年\s*休市安排", page)
    if not heading:
        raise ValueError(f"交易所页面没有 {year} 年休市安排")
    table_start = page.find("<table", heading.end())
    table_end = page.find("</table>", table_start)
    if table_start < 0 or table_end < 0 or table_start - heading.end() > 3000:
        raise ValueError("交易所休市表格式不符")
    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page[table_start:table_end], re.I | re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", cell)).strip()
                 for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.I | re.S)]
        rows.append(cells)
    return _ranges(rows, year)


def _read_cache(year: int) -> list[tuple[date, date]] | None:
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        if data.get("year") != year or data.get("source") != SOURCE:
            return None
        ranges = [(date.fromisoformat(start), date.fromisoformat(end))
                  for start, end in data["ranges"]]
        if not 5 <= len(ranges) <= 10 or any(start > end for start, end in ranges):
            return None
        return ranges
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _fetch_calendar(year: int) -> list[tuple[date, date]]:
    request = Request(SOURCE, headers={"User-Agent": "price-action-monitor/1.0"})
    with urlopen(request, timeout=12) as response:
        page = response.read().decode("utf-8")
    return parse_calendar(page, year)


def calendar_for(year: int) -> list[tuple[date, date]] | None:
    cached = _read_cache(year)
    if cached is not None:
        return cached
    if time.monotonic() < NEXT_RETRY.get(year, 0):
        return None
    try:
        ranges = _fetch_calendar(year)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE.with_name(f".{CACHE.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps({
            "year": year,
            "source": SOURCE,
            "ranges": [[start.isoformat(), end.isoformat()] for start, end in ranges],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(CACHE)
        print(f"[calendar] 已获取 {year} 年交易所休市安排")
        return ranges
    except Exception as exc:
        NEXT_RETRY[year] = time.monotonic() + 3600
        print(f"[calendar] {year} 年休市安排获取失败，暂停推送：{type(exc).__name__}: {exc}")
        return None


def is_trading_day(day: date) -> bool:
    ranges = calendar_for(day.year)
    return (day.weekday() < 5 and ranges is not None
            and not any(start <= day <= end for start, end in ranges))
