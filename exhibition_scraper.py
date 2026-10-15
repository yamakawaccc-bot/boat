#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exhibition_scraper.py — 競艇「展示タイム」取得スクレイパー

取得元:
  [公式] BOAT RACE オフィシャルサイト 直前情報
      https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno={R}&jcd={jcd}&hd={YYYYMMDD}
      → 展示タイム / チルト / 体重 / プロペラ / 部品交換 / スタート展示ST / 天候
  [補助・非公式] Boatrace Open API previews
      https://boatraceopenapi.github.io/previews/v2/{YYYY}/{YYYYMMDD}.json
      → racer_exhibition_time 等（公式ページのクロスチェック・一括取得用）

出力は前回の予想パイプライン（date/stadium/race/course キー）にそのまま結合できる DataFrame / CSV。

注意:
  - リクエストは1件ずつ sleep を挟む（サーバ負荷配慮）。サイトポリシーを遵守すること。
  - Boatrace Open API は非公式・正確性保証なし。重要値は公式ページで裏取ること。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")}
OWPC = "https://www.boatrace.jp/owpc/pc/race"
OPENAPI = "https://boatraceopenapi.github.io"

# 会場名マッピングは「本日のレース」index から動的に解決する。
# index取得失敗時のフォールバック用（実データから確認できたペアのみ掲載）。
VENUE_NAMES = ["桐生", "戸田", "江戸川", "平和島", "多摩川", "浜名湖", "蒲郡", "常滑",
               "びわこ", "尼崎", "住之江", "児島", "丸亀", "琴平", "鳴門", "宮島",
               "徳山", "下関", "若松", "芦屋", "福岡", "唐津", "大村", "三角"]
VENUE_MAP_FALLBACK = {1: "桐生", 2: "戸田", 4: "平和島", 6: "浜名湖", 11: "びわこ", 12: "住之江",
                      13: "尼崎", 14: "鳴門", 15: "丸亀", 20: "若松", 21: "芦屋",
                      22: "福岡", 24: "大村"}


# ---------------------------------------------------------------- 基盤
def _get(url: str, session: requests.Session | None = None,
         retries: int = 2, timeout: int = 30) -> requests.Response | None:
    """200ならResponse、404ならNone、それ以外はリトライ後にNone。"""
    s = session or requests.Session()
    for i in range(retries + 1):
        try:
            r = s.get(url, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1.0 + i)
    return None


def _num(s: str | None) -> float | None:
    s = (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


# ---------------------------------------------------------------- 会場一覧
def list_live_venues(yyyymmdd: str, session=None) -> list[tuple[int, str]]:
    """「本日のレース」index から開催中の (jcd, 会場名) を抽出する。"""
    r = _get(f"{OWPC}/index?hoted={yyyymmdd}", session)
    if r is None:
        return [(k, v) for k, v in sorted(VENUE_MAP_FALLBACK.items())]
    html, pairs = r.text, {}
    for m in re.finditer(rf"jcd=(\d{{2}})(?:&amp;|&)hd={yyyymmdd}", html):
        window = html[max(0, m.start() - 1500):m.start()]
        found = [n for n in VENUE_NAMES if n in window]
        if found:
            pairs.setdefault(int(m.group(1)), found[-1])
    return sorted(pairs.items())


# ---------------------------------------------------------------- 公式 直前情報
def parse_beforeinfo(html: str, yyyymmdd: str, jcd: int, rno: int) -> list[dict]:
    """直前情報ページ1レース分をパースする（未公開・中止は空リスト）。"""
    soup = BeautifulSoup(html, "html.parser")

    # --- 天候（気温/風速/水温/波高）---
    wx: dict = {}
    for u in soup.select("div.weather1_bodyUnit"):
        t = u.select_one("span.weather1_bodyUnitLabelTitle")
        d = u.select_one("span.weather1_bodyUnitLabelData")
        if not (t and d):
            continue
        label, val = t.get_text(strip=True), d.get_text(strip=True)
        if "気温" in label:
            wx["air_temp"] = _num(val.replace("℃", ""))
        elif "風速" in label:
            wx["wind"] = _num(val.replace("m", ""))
        elif "水温" in label:
            wx["water_temp"] = _num(val.replace("℃", ""))
        elif "波高" in label:
            wx["wave"] = _num(val.replace("cm", ""))

    # --- 展示タイム本体の表（ヘッダに「展示」「枠」を含む）---
    main = None
    for t in soup.find_all("table"):
        heads = " ".join(th.get_text(strip=True) for th in t.find_all("th"))
        if "展示" in heads and "枠" in heads:
            main = t
            break
    if main is None:
        return []

    # --- スタート展示（コース別ST、F=フライング展示）---
    se: dict[int, tuple[bool, float]] = {}
    for t in soup.find_all("table"):
        heads = " ".join(th.get_text(strip=True) for th in t.find_all("th"))
        if "スタート展示" in heads:
            for tr in t.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) == 1:
                    m = re.match(r"^\s*(\d)\s*(F?)\s*\.?\s*(\d{1,2})\s*$",
                                 tds[0].get_text())
                    if m:
                        se[int(m.group(1))] = (m.group(2) == "F",
                                               round(int(m.group(3)) / 100, 2))

    # --- 艇ブロック（1艇=4行: 本体/進入/ST/着順）---
    out: list[dict] = []
    cur: dict | None = None
    for tr in main.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        texts = [c.get_text(" ", strip=True) for c in cells]
        first = cells[0] if cells else None
        is_boat = bool(
            first and first.name == "td"
            and re.search(r"is-boatColor\d", " ".join(first.get("class") or []))
        ) or bool(
            first and first.name == "td"
            and re.fullmatch(r"[1-6]", texts[0]) and len(cells) >= 8
        )
        if is_boat and len(texts) >= 8:
            if cur:
                out.append(cur)
            cur = dict(
                course=int(texts[0]),
                racer_name=re.sub(r"[\u3000\s]+", " ", texts[2]).strip(),
                weight_kg=_num(texts[3].replace("kg", "")),
                exhibition_time=_num(texts[4]),   # ★展示タイム
                tilt=_num(texts[5]),              # チルト
                propeller=texts[6] or None,       # プロペラ
                parts_exchange=texts[7] or None,  # 部品交換
                prev_race_type=(texts[8] or None) if len(texts) > 8 else None,
                prev_course_in=None, prev_result=None, prev_st=None,
                adjust_weight=None,
            )
            continue
        if cur is not None:
            if "進入" in texts:
                i = texts.index("進入")
                if i + 1 < len(texts):
                    cur["prev_course_in"] = _num(texts[i + 1])
            if "着順" in texts:
                i = texts.index("着順")
                if i + 1 < len(texts) and texts[i + 1]:
                    cur["prev_result"] = texts[i + 1]
            if "ST" in texts:
                i = texts.index("ST")
                before = [x for x in texts[:i]
                          if re.fullmatch(r"-?\d+(\.\d+)?", x)]
                if before:                     # rowspan=2 の数値セルは調整重量
                    cur["adjust_weight"] = _num(before[-1])
                if i + 1 < len(texts):         # 'ST'ラベルの後ろは前走ST
                    cur["prev_st"] = _num(texts[i + 1])
    if cur:
        out.append(cur)

    for r in out:
        f, st = se.get(r["course"], (None, None))
        r["start_exhibition_f"] = f
        r["start_exhibition_st"] = st
        r.update(wx)
        r.update(date=_iso(yyyymmdd), stadium=jcd, race=rno,
                 fetched_at=dt.datetime.now().isoformat(timespec="seconds"))
    return out


def scrape_beforeinfo(jcd: int, yyyymmdd: str, rnos=range(1, 13), sleep: float = 0.8,
                      session: requests.Session | None = None,
                      verbose: bool = True) -> list[dict]:
    """1会場×指定レース(既定1-12R)の直前情報を取得する。"""
    s = session or requests.Session()
    rows: list[dict] = []
    for rno in rnos:
        if rows:
            time.sleep(sleep)  # 負荷配慮
        url = f"{OWPC}/beforeinfo?rno={rno}&jcd={jcd:02d}&hd={yyyymmdd}"
        r = _get(url, s)
        if r is None:
            if verbose:
                print(f"  [skip] {jcd:02d} R{rno}: 取得失敗 or 未公開")
            continue
        got = parse_beforeinfo(r.text, yyyymmdd, jcd, rno)
        if verbose:
            mark = f"{len(got)}艇" if got else "データなし(未公開/中止)"
            print(f"  [ok]   {jcd:02d} R{rno}: {mark}")
        rows += got
    return rows


def scrape_day(yyyymmdd: str, jcds: list[int] | None = None, rnos=range(1, 13),
               sleep: float = 0.8) -> pd.DataFrame:
    """指定日（未指定会場なら index から開催会場を自動解決）の全データを取得。"""
    session = requests.Session()
    venues = list_live_venues(yyyymmdd, session) if jcds is None else []
    if jcds is None:
        print(f"開催会場: {venues}")
        jcds = [j for j, _ in venues]
    names = dict(venues) or VENUE_MAP_FALLBACK
    rows: list[dict] = []
    for j in jcds:
        print(f"== jcd={j:02d} ({names.get(j, '?')}) ==")
        for r in scrape_beforeinfo(j, yyyymmdd, rnos, sleep, session):
            r["stadium_name"] = names.get(j, "")
            rows.append(r)
    df = pd.DataFrame(rows)
    cols = ["date", "stadium", "stadium_name", "race", "course", "racer_name",
            "exhibition_time", "tilt", "weight_kg", "adjust_weight",
            "propeller", "parts_exchange",
            "start_exhibition_st", "start_exhibition_f",
            "prev_race_type", "prev_course_in", "prev_st", "prev_result",
            "air_temp", "wind", "water_temp", "wave", "fetched_at"]
    return df[[c for c in cols if c in df.columns]]


# ---------------------------------------------------------------- 補助: OpenAPI
def fetch_openapi_previews(date_iso: str) -> pd.DataFrame:
    """Boatrace Open API previews（非公式）から展示タイム等を取得。"""
    y, ymd = date_iso[:4], date_iso.replace("-", "")
    r = _get(f"{OPENAPI}/previews/v2/{y}/{ymd}.json")
    if r is None:
        return pd.DataFrame()
    rows = []
    for race in r.json()["previews"]:
        for b in race["boats"]:
            rows.append(dict(
                date=race["race_date"], stadium=race["race_stadium_number"],
                race=race["race_number"], course=b["racer_boat_number"],
                exhibition_time_api=b["racer_exhibition_time"] or None,
                tilt_api=b["racer_tilt_adjustment"] or None,
                st_api=b["racer_start_timing"] or None,
                weight_api=b["racer_weight"] or None,
                wind_api=race["race_wind"], wave_api=race["race_wave"],
            ))
    return pd.DataFrame(rows)


def crosscheck_with_api(df_official: pd.DataFrame, date_iso: str) -> pd.DataFrame | None:
    """公式ページの展示タイムと OpenAPI の値を突き合わせて検証する。"""
    api = fetch_openapi_previews(date_iso)
    if api.empty:
        print("OpenAPI: データなし")
        return None
    m = df_official.merge(api, on=["date", "stadium", "race", "course"], how="inner")
    both = m[m["exhibition_time"].notna() & m["exhibition_time_api"].notna()]
    if both.empty:
        print("OpenAPI: 比較可能な行なし（未公開）")
        return m
    diff = (both["exhibition_time"] - both["exhibition_time_api"]).abs()
    print(f"[クロスチェック] 比較{len(both)}行 | 完全一致 {int((diff == 0).sum())}行"
          f" ({(diff == 0).mean():.1%}) | 最大差 {diff.max():.2f}秒")
    bad = both[diff > 0]
    if len(bad):
        print(bad[["date", "stadium", "race", "course", "exhibition_time",
                   "exhibition_time_api"]].to_string(index=False))
    return m


# ---------------------------------------------------------------- パイプライン結合
def attach_exhibition(df_programs: pd.DataFrame, df_exhibition: pd.DataFrame,
                      ) -> pd.DataFrame:
    """前回の出走表DataFrameに展示系特徴量を left join する。"""
    cols = ["date", "stadium", "race", "course", "exhibition_time", "tilt",
            "adjust_weight", "prev_st", "start_exhibition_st",
            "start_exhibition_f", "propeller", "parts_exchange"]
    cols = [c for c in cols if c in df_exhibition.columns]
    return df_programs.merge(df_exhibition[cols],
                             on=["date", "stadium", "race", "course"], how="left")


# ---------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser(description="競艇 展示タイムスクレイパー")
    ap.add_argument("date", help="YYYYMMDD")
    ap.add_argument("--jcd", help="会場コード (例: 01,06)。未指定/--live で全開催会場")
    ap.add_argument("--live", action="store_true", help="開催中の全会場を自動取得")
    ap.add_argument("--races", help="レース番号 (例: 1,2,3。既定 1-12)")
    ap.add_argument("--sleep", type=float, default=0.8)
    ap.add_argument("--out", default="")
    ap.add_argument("--crosscheck", action="store_true", help="OpenAPIと突き合わせ検証")
    args = ap.parse_args()

    yyyymmdd = args.date.replace("-", "")
    rnos = [int(x) for x in args.races.split(",")] if args.races else range(1, 13)
    jcds = [int(x) for x in args.jcd.split(",")] if args.jcd and not args.live else None

    df = scrape_day(yyyymmdd, jcds, rnos, args.sleep)
    print(df.head(14).to_string(index=False))

    if args.crosscheck:
        crosscheck_with_api(df, _iso(yyyymmdd))

    out = args.out or f"exhibition_{yyyymmdd}.csv"
    df.to_csv(out, index=False)
    print(f"saved: {out}  ({len(df)} rows)")


if __name__ == "__main__":
    main()
