#!/usr/bin/env python3
"""
ステップ1: 選手別 × コース別の成績を集計する

データ元: Boatrace Open API (results v3) ※GitHub Pages上のJSON。boatrace.jpや日和には触りません。
  https://boatraceopenapi.github.io/results/v3/YYYY/YYYYMMDD.json  (2025-05-01以降)

使い方:
  python build_stats.py --days 180        # 直近180日を集計 → data/racer_stats.csv
  python build_stats.py --racer 4491      # 登録番号4491の選手のコース別率を表示

必要なもの: pip install requests pandas

決まり手の番号(technique_number)は 1逃げ 2差し 3まくり 4まくり差し 5抜き 6恵まれ
として扱っています。実行時の「動作チェック」で1コース1着の大半が逃げになっていればOK。
"""
import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://boatraceopenapi.github.io/results/v3/{year}/{ymd}.json"
FIRST_DAY = date(2025, 5, 1)  # APIの対応開始日
CACHE_DIR = Path("data/daily")
OUT_PATH = Path("data/racer_stats.csv")
HEADERS = {"User-Agent": "personal-boatrace-stats/0.1"}
SLEEP_SEC = 0.5  # 1日分ごとの待ち時間(相手に優しく)

TECH_COL = {
    1: "w_nige",
    2: "w_sashi",
    3: "w_makuri",
    4: "w_makurizashi",
    5: "w_nuki",
    6: "w_megumare",
}
COUNT_COLS = ["starts", "wins", *TECH_COL.values(), "race_nige"]
DAILY_COLS = ["racer_number", "course", *COUNT_COLS]


def aggregate_day(data: dict) -> pd.DataFrame:
    """1日分のJSONを (選手, 進入コース) ごとの回数に集計する。

    starts    : そのコースで出走した回数
    wins      : そのコースで1着になった回数
    w_xxx     : 1着のうち、決まり手がxxxだった回数
    race_nige : そのコースで出走したレースのうち、決まり手が「逃げ」だった回数
                (2コースで出た時の「逃がした回数」の元になる)
    """
    acc: dict = {}
    for race in data.get("results", []):
        tech = race.get("technique_number")
        if tech is None:  # 不成立・中止などは数えない
            continue
        for boat in race.get("boats", []):
            racer = boat.get("racer_number")
            course = boat.get("racer_course_number")
            if racer is None or course is None:  # 欠場など
                continue
            row = acc.setdefault((racer, course), dict.fromkeys(COUNT_COLS, 0))
            row["starts"] += 1
            if tech == 1:
                row["race_nige"] += 1
            if boat.get("racer_place_number") == 1:
                row["wins"] += 1
                col = TECH_COL.get(tech)
                if col:
                    row[col] += 1
    rows = [{"racer_number": r, "course": c, **v} for (r, c), v in acc.items()]
    return pd.DataFrame(rows, columns=DAILY_COLS)


def fetch_day(d: date, retries: int = 3):
    """1日分のJSONを取得。データなし(404)なら None。"""
    url = BASE_URL.format(year=d.year, ymd=d.strftime("%Y%m%d"))
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            wait = 2 ** (attempt + 1)
            print(f"  {d} 取得失敗({e}) → {wait}秒待って再試行", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"{d} の取得に失敗しました。時間をおいて再実行してください。")


def ensure_cached(d: date, today: date) -> bool:
    """その日の集計がキャッシュに無ければ取得して保存。新規にアクセスしたら True。"""
    path = CACHE_DIR / f"{d:%Y%m%d}.csv"
    if path.exists():
        return False
    data = fetch_day(d)
    if data is None:
        # 古い日付の404は「データなし」として覚える。直近は更新待ちかもしれないので覚えない
        if d < today - timedelta(days=3):
            pd.DataFrame(columns=DAILY_COLS).to_csv(path, index=False)
        return True
    aggregate_day(data).to_csv(path, index=False)
    return True


def load_window(days: int) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    end = today - timedelta(days=1)  # 当日分は未確定なので昨日まで
    start = max(end - timedelta(days=days - 1), FIRST_DAY)

    frames = []
    n_days = (end - start).days + 1
    for i in range(n_days):
        d = start + timedelta(days=i)
        accessed = ensure_cached(d, today)
        path = CACHE_DIR / f"{d:%Y%m%d}.csv"
        if path.exists():
            df = pd.read_csv(path)
            if not df.empty:
                frames.append(df)
        if accessed:
            time.sleep(SLEEP_SEC)
        if (i + 1) % 20 == 0 or i + 1 == n_days:
            print(f"  {i + 1}/{n_days}日 処理済み")
    if not frames:
        raise RuntimeError("集計できるデータがありませんでした。")
    return pd.concat(frames, ignore_index=True)


def build_stats(df: pd.DataFrame) -> pd.DataFrame:
    """日別の集計を合算して、率(%)を出す。"""
    g = df.groupby(["racer_number", "course"], as_index=False)[COUNT_COLS].sum()
    s = g["starts"]

    def pct(col):
        return (g[col] / s * 100).round(1)

    g["win_rate"] = pct("wins")  # 1着率
    g["nige_rate"] = pct("w_nige")  # 逃げ率 (1コース用)
    g["nigashi_rate"] = pct("race_nige")  # 逃し率 (2コース用: 1コースに逃げられた率)
    g["sashi_rate"] = pct("w_sashi")  # 差し率 (2〜6コース用)
    g["makuri_rate"] = pct("w_makuri")  # 捲り率
    g["makurizashi_rate"] = pct("w_makurizashi")  # 捲り差し率
    return g.sort_values(["racer_number", "course"]).reset_index(drop=True)


def sanity_check(stats: pd.DataFrame) -> None:
    c1 = stats[stats["course"] == 1]
    starts, wins, nige = c1["starts"].sum(), c1["wins"].sum(), c1["w_nige"].sum()
    print("\n【動作チェック】全体の1コース")
    print(f"  出走 {starts:,} / 1着率 {wins / starts * 100:.1f}% / 逃げ率 {nige / starts * 100:.1f}%")
    print(f"  1コース1着のうち決まり手が逃げ: {nige / wins * 100:.1f}%  (9割前後ならOK)")
    print(f"  選手数: {stats['racer_number'].nunique():,}人")


def show_racer(stats: pd.DataFrame, racer: int) -> None:
    r = stats[stats["racer_number"] == racer]
    if r.empty:
        print(f"登録番号 {racer} のデータが見つかりません")
        return
    cols = ["course", "starts", "win_rate", "nige_rate", "nigashi_rate",
            "sashi_rate", "makuri_rate", "makurizashi_rate"]
    print(f"\n登録番号 {racer} のコース別成績")
    print(r[cols].to_string(index=False))


def main() -> None:
    p = argparse.ArgumentParser(description="選手別コース成績の集計")
    p.add_argument("--days", type=int, default=180, help="集計する日数(昨日から遡る)")
    p.add_argument("--racer", type=int, help="登録番号を指定すると、その選手の率を表示")
    args = p.parse_args()

    print(f"直近{args.days}日分を集計します(初回は日数分のダウンロードが走ります)")
    stats = build_stats(load_window(args.days))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    stats.to_csv(OUT_PATH, index=False)
    print(f"\n保存しました → {OUT_PATH}  ({len(stats):,}行)")

    sanity_check(stats)
    if args.racer:
        show_racer(stats, args.racer)


if __name__ == "__main__":
    main()
