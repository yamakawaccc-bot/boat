# -*- coding: utf-8 -*-
"""出走表（級別・当地成績・モーター・平均ST・F/L・選手登録番号）の取得

exhibition_scraper.py と同じフォルダに置く。
"""
import re

from bs4 import BeautifulSoup

from exhibition_scraper import OWPC, _get, _iso

NUM = re.compile(r"-?\d+(?:\.\d+)?")
CLASS = re.compile(r"(?<![A-Za-z0-9])(A1|A2|B1|B2)(?![A-Za-z0-9])")
FLST = re.compile(r"F\s*(\d+)\s*L\s*(\d+)\s*(\d\.\d{2})?")
TOBAN_HREF = re.compile(r"toban=(\d{4})")                          # 選手ページのリンク
TOBAN_TEXT = re.compile(r"(?<!\d)(\d{4})\s*/\s*(?:A1|A2|B1|B2)")  # 「4148 / A1」の表記


def _nums(td):
    return NUM.findall(td.get_text(" ", strip=True))


def _f(x):
    return float(x) if x is not None else None


def _toban(tb):
    """選手登録番号（4桁）を取る。リンク→表記の順に探し、なければ None。"""
    for a in tb.find_all("a", href=True):
        m = TOBAN_HREF.search(a["href"])
        if m:
            return int(m.group(1))
    m = TOBAN_TEXT.search(tb.get_text(" ", strip=True))
    return int(m.group(1)) if m else None


def parse_racelist(html, yyyymmdd, jcd, rno):
    """出走表1レース分をパースする（取れない項目は None）。"""
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for tb in soup.find_all("tbody"):
        tds = tb.find_all("td")
        course = None
        for td in tds:
            if re.search(r"is-boatColor\d", " ".join(td.get("class") or [])):
                t = td.get_text(strip=True)
                if t.isdigit():
                    course = int(t)
                break
        if course is None or course in found:
            continue
        m_cls = CLASS.search(tb.get_text(" ", strip=True))
        row = dict(date=_iso(yyyymmdd), stadium=jcd, race=rno, course=course,
                   toban=_toban(tb),
                   racer_class=m_cls.group(1) if m_cls else None,
                   f_count=None, l_count=None, avg_st=None,
                   local_win=None, local_2rate=None,
                   motor_no=None, motor_2rate=None)
        for i, td in enumerate(tds):
            m = FLST.search(td.get_text(" ", strip=True))
            if not m:
                continue
            row.update(f_count=int(m.group(1)), l_count=int(m.group(2)),
                       avg_st=_f(m.group(3)))
            stats = tds[i + 1:i + 5]       # 全国, 当地, モーター, ボート の順
            if len(stats) >= 3:
                loc, mot = _nums(stats[1]), _nums(stats[2])
                if len(loc) >= 2:
                    row["local_win"], row["local_2rate"] = float(loc[0]), float(loc[1])
                if len(mot) >= 2:
                    row["motor_no"], row["motor_2rate"] = int(float(mot[0])), float(mot[1])
            break
        found[course] = row
    return [found[c] for c in sorted(found)]


def scrape_racelist(jcd, yyyymmdd, rno, session=None):
    """1レース分の出走表データを取得する（失敗時は空リスト）。"""
    r = _get(f"{OWPC}/racelist?rno={rno}&jcd={jcd:02d}&hd={yyyymmdd}", session)
    return parse_racelist(r.text, yyyymmdd, jcd, rno) if r else []
