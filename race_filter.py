#!/usr/bin/env python3
"""
ステップ3: 今日のレースを条件で絞り込む(日和の「ガチガチレース検索」「穴レース検索」の再現)

  ガチガチ: 1号艇の逃げ率 ≥ ◯%  かつ  2号艇の逃し率 ≥ ◯%
  穴      : 1号艇の逃げ率 ≤ ◯%  かつ  2〜6号艇の差し・捲り率(最大) ≥ ◯%

使い方:
  python race_filter.py                              # 既定(70/50 と 40/30)で両方検索
  python race_filter.py --nige-min 65 --nigashi-min 45
  python race_filter.py --upcoming                   # 締切前のレースだけ

race_table.py と同じフォルダに置いてください(データの取得・合体はそちらを使います)。
"""
import argparse
from datetime import datetime, timedelta, timezone

import pandas as pd

import race_table as rt

JST = timezone(timedelta(hours=9))


def search_gachigachi(table: pd.DataFrame, nige_min: float = 70, nigashi_min: float = 50) -> pd.DataFrame:
    """1号艇逃げ率 ≥ nige_min かつ 2号艇逃し率 ≥ nigashi_min。率がない(NaN)レースは除外。"""
    hit = (table["1逃げ率"] >= nige_min) & (table["2逃し率"] >= nigashi_min)
    return table[hit]


def search_ana(table: pd.DataFrame, nige_max: float = 40, attack_min: float = 30) -> pd.DataFrame:
    """1号艇逃げ率 ≤ nige_max かつ 2〜6号艇の差し・捲り率(最大) ≥ attack_min。"""
    hit = (table["1逃げ率"] <= nige_max) & (table["攻め最大率"] >= attack_min)
    return table[hit]


def only_upcoming(table: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """締切時刻がまだ来ていないレースだけ残す(日本時間)。"""
    hhmm = (now or datetime.now(JST)).strftime("%H:%M")
    return table[table["締切"] >= hhmm]


def show(title: str, df: pd.DataFrame, cols: list) -> None:
    print(f"\n■ {title}: {len(df)}件")
    if df.empty:
        print("  該当なし")
    else:
        print(df.sort_values("締切")[cols].to_string(index=False))


def main() -> None:
    p = argparse.ArgumentParser(description="今日のレースを条件で絞り込む")
    p.add_argument("--nige-min", type=float, default=70, help="ガチガチ: 1号艇逃げ率の下限(%)")
    p.add_argument("--nigashi-min", type=float, default=50, help="ガチガチ: 2号艇逃し率の下限(%)")
    p.add_argument("--ana-nige-max", type=float, default=40, help="穴: 1号艇逃げ率の上限(%)")
    p.add_argument("--ana-attack-min", type=float, default=30, help="穴: 2〜6号艇の差し・捲り率の下限(%)")
    p.add_argument("--min-starts", type=int, default=10, help="この出走数に満たない率は使わない")
    p.add_argument("--upcoming", action="store_true", help="締切前のレースだけ")
    args = p.parse_args()

    table = rt.build_table(rt.fetch_programs(), rt.load_stats(args.min_starts))
    if args.upcoming:
        table = only_upcoming(table)
    print(f"対象レース: {len(table)}件")

    gachi = search_gachigachi(table, args.nige_min, args.nigashi_min)
    show(f"ガチガチ(1号艇逃げ率{args.nige_min:g}%以上 × 2号艇逃し率{args.nigashi_min:g}%以上)", gachi,
         ["会場", "R", "締切", "1号艇", "1逃げ率", "2号艇", "2逃し率"])

    ana = search_ana(table, args.ana_nige_max, args.ana_attack_min)
    show(f"穴(1号艇逃げ率{args.ana_nige_max:g}%以下 × 2〜6号艇の差し・捲り率{args.ana_attack_min:g}%以上)", ana,
         ["会場", "R", "締切", "1号艇", "1逃げ率", "攻め艇", "攻め最大率"])


if __name__ == "__main__":
    main()
