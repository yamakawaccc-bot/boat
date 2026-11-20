#!/usr/bin/env python3
"""
history_fetch.py
Boatrace Open API（結果データ）から、過去のレース結果を「日ごとのファイル」にためておくスクリプト。
集めるだけ。分析や点数への反映はしない。既存のファイルとは別（technique_tags.py などには触らない）。

データ元: https://boatraceopenapi.github.io/api/v1/YYYY/YYYYMMDD.json （2026-01-01以降）

1レースごとに保存する項目（短いキーで保存してファイルを小さくしている）:
  st     会場番号            r      レース番号          grade  開催グレード番号
  ws     風速(m)             wd     風向き番号          wds    風向き（文字）  ← 番号と文字の対応確認用
  wave   波高(cm)            wx     天気番号            tech   決まり手
  fin    着順（"1-3-2" 艇番の順。1〜3着）
  crs    進入コース（艇番1〜6の順に、その艇が入ったコース。取れないときは null）
  rank   級別（艇番1〜6の順に "A1" など）
  tri    三連単の払戻 [組み合わせ, 払戻金額(100円あたり)]
  ref    返還があったか（true/false）

保存先: history_data/races/YYYYMMDD.json （取得済みの日は再取得しない）

使い方:
  python history_fetch.py --days 7      # 直近7日（まず試す用）
  python history_fetch.py --days 365    # 2026-01-01まで遡って取得（取得済みの日は飛ばす）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---- 設定 -----------------------------------------------------------------
API_URL = "https://boatraceopenapi.github.io/api/v1/{year}/{ymd}.json"
API_START = date(2026, 1, 1)          # APIの対応開始日
JST = timezone(timedelta(hours=9))
REQUEST_INTERVAL = 1.0                 # リクエスト間隔（秒）。API側に負荷をかけない

DATA_DIR = Path(__file__).with_name("history_data")
RACES_DIR = DATA_DIR / "races"
# --------------------------------------------------------------------------


def today_jst() -> date:
    return datetime.now(JST).date()


def fetch_day(d: date, retries: int = 3):
    """1日分のJSONを取得。404ならNone。失敗が続けばRuntimeError。"""
    url = API_URL.format(year=d.year, ymd=d.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "history-fetch/1.0"})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_err = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{d} の取得に失敗: {last_err}")


def _by_entry(racers: dict | None) -> dict[int, dict]:
    """番号キーの辞書 → {艇番: 中身}"""
    out: dict[int, dict] = {}
    for r in (racers or {}).values():
        n = (r or {}).get("entry_number")
        if isinstance(n, int):
            out[n] = r
    return out


def extract_races(day_json: dict) -> list[dict]:
    """1日分のJSONから、結果のあるレースを短い形に直して返す（中止などは飛ばす）。"""
    races: list[dict] = []
    stadiums = (day_json.get("programs") or {}).get("stadiums") or {}
    for st in stadiums.values():
        for race in ((st or {}).get("races") or {}).values():
            race = race or {}
            result = race.get("result")
            if not result:
                continue
            res_racers = _by_entry(result.get("racers"))
            prog_racers = _by_entry(race.get("racers"))

            # 着順（1〜3着の艇番）
            placed = sorted(
                (r["place_number"], n) for n, r in res_racers.items()
                if isinstance(r.get("place_number"), int) and r["place_number"] <= 3
            )
            fin = "-".join(str(n) for _, n in placed)

            tri = None
            tri_list = (result.get("payouts") or {}).get("trifecta") or []
            if tri_list:
                tri = [tri_list[0].get("combination"), tri_list[0].get("amount")]

            races.append({
                "st": race.get("stadium_number"),
                "r": race.get("race_number"),
                "grade": race.get("grade_number"),
                "ws": result.get("wind_speed"),
                "wd": result.get("wind_direction_number"),
                "wds": result.get("wind_direction_number_source"),
                "wave": result.get("wave_height"),
                "wx": result.get("weather_number"),
                "tech": result.get("technique_number_source"),
                "fin": fin,
                "crs": [(res_racers.get(i) or {}).get("course_number") for i in range(1, 7)],
                "rank": [(prog_racers.get(i) or {}).get("rank_number_source") for i in range(1, 7)],
                "tri": tri,
                "ref": bool(result.get("refunds")),
            })
    return races


def update_cache(start: date, end: date) -> None:
    """start〜endの各日について、未取得の日だけ取得して保存する。"""
    RACES_DIR.mkdir(parents=True, exist_ok=True)
    fetched = 0
    d = start
    while d <= end:
        path = RACES_DIR / f"{d:%Y%m%d}.json"
        if not path.exists():
            if fetched:
                time.sleep(REQUEST_INTERVAL)
            fetched += 1
            try:
                data = fetch_day(d)
            except RuntimeError as e:
                print(f"  {d}: {e}（スキップ。次回また試します）", file=sys.stderr)
                d += timedelta(days=1)
                continue
            if data is None:
                print(f"  {d}: データなし（404）")
            else:
                races = extract_races(data)
                path.write_text(
                    json.dumps({"date": d.isoformat(), "races": races},
                               ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                print(f"  {d}: {len(races)}レースを保存")
        d += timedelta(days=1)


def summarize() -> None:
    """保存済みデータの確認用まとめ（件数・期間・風向きの番号と文字の対応）。"""
    files = sorted(RACES_DIR.glob("*.json"))
    if not files:
        print("保存済みのデータがありません")
        return
    total = 0
    no_wind = 0
    wd_map: dict = defaultdict(Counter)
    for f in files:
        for r in json.loads(f.read_text(encoding="utf-8")).get("races", []):
            total += 1
            if r.get("ws") is None or r.get("wd") is None:
                no_wind += 1
            wd_map[r.get("wd")][r.get("wds")] += 1
    print(f"\n=== まとめ ===")
    print(f"期間: {files[0].stem} 〜 {files[-1].stem}（{len(files)}日分）")
    print(f"レース数: {total} ／ 風のデータなし: {no_wind}")
    print("風向き番号と文字の対応（番号: 文字×件数）")
    for k in sorted(wd_map, key=lambda x: (x is None, x)):
        parts = "、".join(f"{s}×{c}" for s, c in wd_map[k].most_common(3))
        print(f"  {k}: {parts}")


def main() -> None:
    ap = argparse.ArgumentParser(description="過去のレース結果を日ごとにためる")
    ap.add_argument("--days", type=int, default=7, help="遡る日数（2026-01-01より前には遡らない）")
    args = ap.parse_args()

    end = today_jst() - timedelta(days=1)  # 当日は途中なので含めない
    start = max(API_START, end - timedelta(days=args.days - 1))
    print(f"取得期間: {start} 〜 {end}")
    update_cache(start, end)
    summarize()


if __name__ == "__main__":
    main()
