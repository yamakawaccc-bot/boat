#!/usr/bin/env python3
"""
wind_stats.py
history_data/races の過去結果から、「会場 × 風速帯」ごとの1号艇の1着率を計算して、
小さなファイル history_data/wind_stats.json に保存する。

・保存するだけ。画面（app.py）や点数・判定にはつながない。表示専用の参考情報の元データ。
・wind_report.py（確認用の集計）と同じ会場名・風速帯の定義を使う（wind_report.py と同じフォルダに置く）。

保存する内容（会場ごと・風速帯ごと）:
  rate  実際の1号艇1着率（%）
  n     そのレース数
  est   補正した推定値（%）。レース数が少ない枠のブレをならしたもの。
        「その会場の平均」に「全国の同じ風速帯での平均との差」を足したものを目安に、
        実際の数字をレース数に応じて混ぜている（レースが多いほど実際の数字に近づく）。
  ※表示するときは、n が少ない枠は est を使い、「参考」と分かるようにする想定。

使い方:
  python wind_stats.py                 # history_data/wind_stats.json を作る
アプリ側から使う:
  from wind_stats import load_wind_stats, get_wind_info
  stats = load_wind_stats()
  info = get_wind_info(stats, 1, 6)    # 桐生・風速6m → {"band":"6m+", "rate":..., "est":..., "n":..., ...}
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wind_report import SPEED_BANDS, VENUES, Tally, band_of, load_races

# ---- 設定 -----------------------------------------------------------------
DATA_DIR = Path(__file__).with_name("history_data")
OUT_PATH = DATA_DIR / "wind_stats.json"
JST = timezone(timedelta(hours=9))

SHRINK_K = 60        # 大きいほど、レース数が少ない枠をその会場の平均寄りにならす
RELIABLE_N = 100     # この数以上のレースがある枠は「実数をそのまま信頼してよい」目安
# --------------------------------------------------------------------------


def _pct(x: float) -> float:
    return round(x, 1)


def build() -> dict:
    races = load_races()
    all_t = Tally()
    all_band = defaultdict(Tally)
    v_t = defaultdict(Tally)
    v_band = defaultdict(lambda: defaultdict(Tally))
    dates = []

    for f in sorted((DATA_DIR / "races").glob("*.json")):
        dates.append(f.stem)

    used = 0
    for r in races:
        ws, st, fin = r.get("ws"), r.get("st"), r.get("fin")
        if ws is None or st is None or not fin:
            continue
        b = band_of(int(ws))
        if b is None:
            continue
        win = fin.split("-")[0] == "1"
        used += 1
        all_t.add(win)
        all_band[b].add(win)
        v_t[int(st)].add(win)
        v_band[int(st)][b].add(win)

    all_rate = all_t.rate()
    out = {
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "period": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        "races_used": used,
        "settings": {"shrink_k": SHRINK_K, "reliable_n": RELIABLE_N},
        "bands": [name for name, _, _ in SPEED_BANDS],
        "all": {
            "rate": _pct(all_rate),
            "n": all_t.n,
            "bands": {b: {"rate": _pct(all_band[b].rate()), "n": all_band[b].n}
                      for b, _, _ in SPEED_BANDS},
        },
        "venues": {},
    }

    for st in sorted(v_t):
        base = v_t[st].rate()
        bands = {}
        for name, _, _ in SPEED_BANDS:
            t = v_band[st][name]
            # 目安 = その会場の平均 + 全国の「この風速帯 − 全体」の差
            prior = base + (all_band[name].rate() - all_rate)
            prior = min(max(prior, 1.0), 99.0)
            est = (t.w + SHRINK_K * prior / 100) / (t.n + SHRINK_K) * 100
            bands[name] = {"rate": _pct(t.rate()), "n": t.n, "est": _pct(est)}
        out["venues"][str(st)] = {
            "name": VENUES.get(st, str(st)),
            "rate": _pct(base),
            "n": v_t[st].n,
            "bands": bands,
        }
    return out


def save(stats: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")


# ---- アプリ側から使う関数 -------------------------------------------------
def load_wind_stats(path: Path | None = None) -> dict:
    return json.loads(Path(path or OUT_PATH).read_text(encoding="utf-8"))


def get_wind_info(stats: dict, stadium_number, wind_speed) -> dict | None:
    """会場番号と風速（m）から、その風速帯の情報を返す。分からなければ None。
    戻り値: band(風速帯) / rate(実数) / est(補正値) / n(レース数) / reliable(nが十分か) /
            venue_rate(その会場の平均) / all_band_rate(全国の同じ風速帯の平均)"""
    try:
        ws = int(wind_speed)
        band = band_of(ws)
        v = stats["venues"][str(int(stadium_number))]
    except (TypeError, ValueError, KeyError):
        return None
    if band is None or band not in v["bands"]:
        return None
    b = v["bands"][band]
    return {
        "band": band,
        "rate": b["rate"],
        "est": b["est"],
        "n": b["n"],
        "reliable": b["n"] >= stats.get("settings", {}).get("reliable_n", RELIABLE_N),
        "venue_name": v["name"],
        "venue_rate": v["rate"],
        "all_band_rate": stats["all"]["bands"][band]["rate"],
    }
# --------------------------------------------------------------------------


def main() -> None:
    stats = build()
    save(stats)
    print(f"保存しました: {OUT_PATH.name}（{stats['period']['start']}〜{stats['period']['end']}、"
          f"{stats['races_used']}レース）")
    print("\n会場 × 風速帯：補正後の推定値%")
    print("　　　　全体| 0-1m 2-3m 4-5m 6m+")
    for st, v in stats["venues"].items():
        cells = "".join(f"{v['bands'][b]['est']:4.0f} " for b in stats["bands"])
        name = v["name"].ljust(4, "　")
        print(f"{name}{v['rate']:3.0f} |{cells}")
    print("\n6m以上のレース数（少ない会場ほど実際の数字はぶれやすい）")
    line = []
    for st, v in stats["venues"].items():
        line.append(f"{v['name']}{v['bands']['6m+']['n']}")
    print(" ".join(line))


if __name__ == "__main__":
    main()
