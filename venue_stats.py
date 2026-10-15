# -*- coding: utf-8 -*-
"""会場ごとのクセ（直近3か月のコース別1着率・決まり手）の取得

exhibition_scraper.py と同じフォルダに置く。
取得元: 公式サイト「ボートレース場データ」
"""
import re

from bs4 import BeautifulSoup

from exhibition_scraper import _get

URL = "https://www.boatrace.jp/owpc/pc/data/stadium?jcd={:02d}"
KM_ALL = ["逃げ", "捲り", "差し", "捲り差し", "抜き", "恵まれ"]
KM_RENAME = {"捲り": "まくり", "捲り差し": "まくり差し"}
DASHES = {"-", "－", "―", "ー", "—", ""}


def _pf(s):
    s = s.strip().replace("%", "").replace("％", "")
    if s in DASHES:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def parse_venue_stats(html):
    """{1: {"w1":..,"w2":..,"w3":..,"km":{"逃げ":..}}, ..., "period": ".."} を返す。
    取れなければ None。"""
    soup = BeautifulSoup(html, "html.parser")
    table = None
    for t in soup.find_all("table"):
        if "決まり手" in t.get_text():
            table = t
            break
    if table is None:
        return None

    names = list(KM_ALL)                      # 列の並び（見出しから読み取る）
    out = {}
    for tr in table.find_all("tr"):
        texts = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        found = [x for x in texts if x in KM_ALL]
        if len(found) == 6:
            names = found
            continue
        if len(texts) >= 13 and texts[0] in "123456" and len(texts[0]) == 1:
            vals = [_pf(x) for x in texts[1:13]]
            if any(v is None for v in vals):
                continue
            out[int(texts[0])] = dict(
                w1=vals[0], w2=vals[1], w3=vals[2],
                km={KM_RENAME.get(n, n): v for n, v in zip(names, vals[6:12])})
    if len(out) < 6:
        return None
    m = re.search(r"集計期間[：:]\s*([\d/]+)\s*[～~〜]\s*([\d/]+)", soup.get_text())
    if m:
        out["period"] = f"{m.group(1)}〜{m.group(2)}"
    return out


def fetch_venue_stats(jcd, session=None):
    """会場コードから取得（失敗時は None）。"""
    r = _get(URL.format(int(jcd)), session)
    return parse_venue_stats(r.text) if r else None
