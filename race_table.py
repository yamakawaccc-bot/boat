#!/usr/bin/env python3
"""
ステップ2: 今日の出走表 × 選手別成績(data/racer_stats.csv) を合体して、
レースごとに「1号艇の逃げ率」「2号艇の逃し率」「2〜6号艇の差し・捲り率」を並べる。

出走表: Boatrace Open API (programs)  ※GitHub Pages上のJSON、1日1ファイル
  https://boatraceopenapi.github.io/programs/v2/today.json

使い方:
  python race_table.py                  # 今日の全レースの表を作る → data/today_races.csv
  python race_table.py --min-starts 15  # 出走数が少ない選手の率は使わない(既定10)

注意: 進入コースはレース前には分からないので、号艇＝コース(枠なり)として計算します。
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
import requests

TODAY_URL = "https://boatraceopenapi.github.io/programs/v2/today.json"
STATS_PATH = Path("data/racer_stats.csv")
OUT_PATH = Path("data/today_races.csv")
HEADERS = {"User-Agent": "personal-boatrace-stats/0.1"}

STADIUMS = {
    1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖",
    7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江",
    13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山",
    19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村",
}


def pick(d: dict, *names, default=None):
    """候補のキー名のうち、最初に見つかった値を返す(APIのキー名の違いに備える)。"""
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default


def fetch_programs(url: str = TODAY_URL) -> list:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    for key in ("programs", "results", "races"):
        if isinstance(data.get(key), list):
            return data[key]
    for v in data.values():  # それ以外でも最初のリストを使う
        if isinstance(v, list):
            return v
    raise RuntimeError(f"出走表の形が想定と違います。キー一覧: {list(data.keys())}")


def load_stats(min_starts: int) -> dict:
    """(登録番号, コース) -> 率 の辞書。出走数が少ないものは除外。"""
    df = pd.read_csv(STATS_PATH)
    df = df[df["starts"] >= min_starts].copy()
    df["attack_rate"] = (df["sashi_rate"] + df["makuri_rate"] + df["makurizashi_rate"]).round(1)
    return {(int(r.racer_number), int(r.course)): r for r in df.itertuples(index=False)}


def build_table(programs: list, stats: dict) -> pd.DataFrame:
    rows = []
    for race in programs:
        stadium = pick(race, "race_stadium_number", "stadium_number")
        number = pick(race, "race_number", "number")
        boats = race.get("boats") or []
        if stadium is None or number is None or not boats:
            raise RuntimeError(f"出走表の形が想定と違います。1レース分のキー一覧: {list(race.keys())}")

        by_boat = {}
        for b in boats:
            n = pick(b, "racer_boat_number", "boat_number")
            if n is None:
                raise RuntimeError(f"艇のキー一覧: {list(b.keys())}")
            by_boat[int(n)] = b

        def racer_of(n):
            b = by_boat.get(n)
            return (int(pick(b, "racer_number")) if b and pick(b, "racer_number") is not None else None,
                    pick(b, "racer_name", default="") if b else "")

        closed = pd.to_datetime(pick(race, "race_closed_at", "closed_at"), errors="coerce")
        row = {
            "会場": STADIUMS.get(int(stadium), str(stadium)),
            "R": int(number),
            "締切": closed.strftime("%H:%M") if pd.notna(closed) else "",
        }

        # 1号艇の逃げ率 / 2号艇の逃し率
        r1, name1 = racer_of(1)
        s1 = stats.get((r1, 1))
        row.update({"1号艇": name1, "1逃げ率": s1.nige_rate if s1 is not None else None,
                    "1出走": int(s1.starts) if s1 is not None else None})
        r2, name2 = racer_of(2)
        s2 = stats.get((r2, 2))
        row.update({"2号艇": name2, "2逃し率": s2.nigashi_rate if s2 is not None else None,
                    "2出走": int(s2.starts) if s2 is not None else None})

        # 2〜6号艇の差し・捲り率(差し+捲り+捲り差し)のうち一番高い艇
        best_rate, best_boat = None, None
        for n in range(2, 7):
            rn, _ = racer_of(n)
            s = stats.get((rn, n))
            if s is not None and (best_rate is None or s.attack_rate > best_rate):
                best_rate, best_boat = s.attack_rate, n
        row.update({"攻め最大率": best_rate, "攻め艇": best_boat})
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["会場", "R"]).reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser(description="今日の出走表と選手別成績を合体")
    p.add_argument("--min-starts", type=int, default=10, help="この出走数に満たない率は使わない")
    args = p.parse_args()

    if not STATS_PATH.exists():
        sys.exit(f"{STATS_PATH} がありません。先に build_stats.py を実行してください。")

    programs = fetch_programs()
    table = build_table(programs, load_stats(args.min_starts))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT_PATH, index=False)

    ok = table["1逃げ率"].notna() & table["2逃し率"].notna()
    print(f"今日のレース数: {len(table)} / 1号艇・2号艇の率がそろったレース: {int(ok.sum())}")
    print(f"保存しました → {OUT_PATH}\n")
    print("【先頭15レース】")
    print(table.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
