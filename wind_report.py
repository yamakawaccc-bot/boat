#!/usr/bin/env python3
"""
wind_report.py
history_data/races に保存したレース結果から、「会場 × 風」で1号艇の1着率がどう変わるかを集計して表示するだけのスクリプト。
確認専用。点数や画面（app.py）には一切つながない。ファイルも保存しない（Actionsのログに出すだけ）。

見るもの:
  A) 全会場まとめて、風速帯ごとの1号艇1着率（基準づくり）
  B) 会場ごと × 風速帯（0-1m / 2-3m / 4-5m / 6m以上）
  C) 会場ごと × 風向き（8方位＋無風）
     ※風向きは「会場ごとの方角のまま」見る。会場の向きの表は使わない（各会場の向きは固定なので、
       その会場なりの傾向がそのまま出る）

表示のルール:
  ・数字は1号艇の1着率（%）。レース数が MIN_N 未満の枠は「-」（Aだけレース数も表示）
  ・▲▼は、その会場の平均より「偶然とは考えにくいほど」高い／低い枠（z値が±Z_MARK以上、かつレース数十分）
    ※枠の数が多いので、偶然の▲▼も数個は混ざる。1つだけ光っている枠は信用しすぎない。
      複数の隣り合う枠（例：風速が上がるほど下がる）で同じ向きの傾向があるものを重視する。

使い方:  python wind_report.py
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

# ---- 設定 -----------------------------------------------------------------
RACES_DIR = Path(__file__).with_name("history_data") / "races"
MIN_N = 30        # これ未満のレース数の枠は「-」にする
Z_MARK = 2.5      # |z|がこれ以上で▲▼をつける

VENUES = {
    1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖",
    7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江",
    13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山",
    19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村",
}

# 風速帯（m）
SPEED_BANDS = [("0-1m", 0, 1), ("2-3m", 2, 3), ("4-5m", 4, 5), ("6m+", 6, 99)]

# 風向き番号（1=北, 2=北北東, ... 16=北北西, 17=無風）を8方位にまとめる
#   北=(北北西・北) 北東=(北北東・北東) 東=(東北東・東) 南東=(東南東・南東)
#   南=(南南東・南) 南西=(南南西・南西) 西=(西南西・西) 北西=(西北西・北西)
DIR_GROUPS = [
    ("北", (16, 1)), ("北東", (2, 3)), ("東", (4, 5)), ("南東", (6, 7)),
    ("南", (8, 9)), ("南西", (10, 11)), ("西", (12, 13)), ("北西", (14, 15)),
    ("無風", (17,)),
]
# --------------------------------------------------------------------------


def band_of(ws: int) -> str | None:
    for name, lo, hi in SPEED_BANDS:
        if lo <= ws <= hi:
            return name
    return None


def dir_of(wd: int) -> str | None:
    for name, nums in DIR_GROUPS:
        if wd in nums:
            return name
    return None


def load_races() -> list[dict]:
    races: list[dict] = []
    for f in sorted(RACES_DIR.glob("*.json")):
        races.extend(json.loads(f.read_text(encoding="utf-8")).get("races", []))
    return races


class Tally:
    """勝ち数とレース数を数える"""
    def __init__(self) -> None:
        self.n = 0
        self.w = 0

    def add(self, win: bool) -> None:
        self.n += 1
        self.w += 1 if win else 0

    def rate(self) -> float:
        return self.w / self.n * 100 if self.n else 0.0


def cell(t: Tally, base: float) -> str:
    """スマホの画面に収まる短い表示。'58▲' のように、率＋印を幅4で返す。"""
    if t.n < MIN_N:
        return "  - "
    p0 = base / 100
    mark = " "
    if 0 < p0 < 1:
        z = (t.w / t.n - p0) / math.sqrt(p0 * (1 - p0) / t.n)
        mark = "▲" if z >= Z_MARK else ("▼" if z <= -Z_MARK else " ")
    return f"{t.rate():3.0f}{mark}"


def vname(st: int) -> str:
    """会場名を全角4文字ぶんにそろえる"""
    return VENUES.get(st, str(st)).ljust(4, "　")


def main() -> None:
    races = load_races()
    # 使えるレースだけ: 会場・風・着順があるもの
    use = []
    for r in races:
        ws, wd, fin, st = r.get("ws"), r.get("wd"), r.get("fin"), r.get("st")
        if None in (ws, wd, st) or not fin:
            continue
        use.append((int(st), int(ws), int(wd), fin.split("-")[0] == "1"))
    print(f"集計に使ったレース: {len(use)} / 全{len(races)}レース（風や着順が欠けたものは除外）")

    # A) 全会場まとめ
    allv = Tally()
    by_band_all = defaultdict(Tally)
    for st, ws, wd, win in use:
        allv.add(win)
        b = band_of(ws)
        if b:
            by_band_all[b].add(win)
    print("\n=== A) 全会場まとめ：1号艇の1着率 ===")
    print(f"全体 {allv.rate():.1f}%（{allv.n}レース）")
    for name, _, _ in SPEED_BANDS:
        t = by_band_all[name]
        print(f"風速{name} {t.rate():.1f}%（{t.n}）")

    # 会場ごとに集計
    v_all = defaultdict(Tally)
    v_band = defaultdict(lambda: defaultdict(Tally))
    v_dir = defaultdict(lambda: defaultdict(Tally))
    for st, ws, wd, win in use:
        v_all[st].add(win)
        b, d = band_of(ws), dir_of(wd)
        if b:
            v_band[st][b].add(win)
        if d:
            v_dir[st][d].add(win)

    print("\n=== B) 会場 × 風速帯（1号艇の1着率%）===")
    print("全体=その会場の平均 ／ ▲▼=平均より明らかに高い・低い")
    print("　　　　全体| 0-1m 2-3m 4-5m 6m+")
    for st in sorted(v_all):
        base = v_all[st].rate()
        cells = "".join(cell(v_band[st][name], base) for name, _, _ in SPEED_BANDS)
        print(f"{vname(st)}{base:3.0f} |{cells}")

    print("\n=== C) 会場 × 風向き（1号艇の1着率%）===")
    print("風向き（会場ごとの方角のまま）: N=北 E=東 S=南 W=西、無=無風")
    print("N=北北西・北 / NE=北北東・北東 / E=東北東・東 / SE=東南東・南東")
    print("S=南南東・南 / SW=南南西・南西 / W=西南西・西 / NW=西北西・北西")
    labels = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    print("　　　　　 " + " ".join(f"{lab:>2} " for lab in labels) + " 無")
    names = [n for n, _ in DIR_GROUPS]
    for st in sorted(v_all):
        base = v_all[st].rate()
        cells = "".join(cell(v_dir[st][name], base) for name in names)
        print(f"{vname(st)}{cells}")


if __name__ == "__main__":
    main()
