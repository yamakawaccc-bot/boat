"""wind_shift.py
会場×風速から、trifecta_picker.pick() に渡す「風補正（wind_shift）」を計算する。

【考え方】
history_data/wind_stats.json には、会場ごと・風速帯ごとの「1号艇の1着率」が入っている。
  rate : その会場の1号艇1着率（全体）
  bands: 風速帯ごとの 1着率(rate)・レース数(n)・推定値(est)
est は、レース数が少ない風速帯を会場全体と全国の傾向に寄せて安定させた値。

風補正 =（その風速帯の est − その会場の全体 rate）× POINTS_PER_PCT
  → その会場で「この風だと1号艇が普段より何%ポイント勝ちやすい／負けやすいか」を、
    点数に直して1号艇に足し引きする。
  → プラスなら1号艇に有利、マイナスなら不利。±WIND_SHIFT_CAP で頭打ち。

【まだ入れていないもの】
・風向き（向かい風・追い風など）は未対応。風速だけで補正している。
・会場そのもののクセ（イン強め・弱め）は補正に入れていない（風の効果だけを見る）。

【使い方】
    from trifecta_picker import pick
    from wind_shift import calc_wind_shift

    w = calc_wind_shift("蒲郡", 5)          # 会場名（または会場番号）と風速[m]
    rw = pick(boats, wind_shift=w["shift"])  # 風考慮版（参考・記録しない）
    st.caption(w["note"])                    # 「蒲郡・風4-5m：1号艇の1着率 ...」の説明文

風速が取れていない（None など）ときは補正 0 になり、通常版と同じ結果になる。
"""
import json
import os

# ---- ここを変えると補正の強さが変わる（調整用） --------------------------

# 1号艇の1着率が 1%ポイント 変わるごとに、何点足し引きするか（大きいほど風を重視）
POINTS_PER_PCT = 1.0

# 補正の上限（±この値で頭打ち）。trifecta_picker 側の WIND_SHIFT_LIMIT より小さくしておく
WIND_SHIFT_CAP = 12.0

# 風速帯の区切り（wind_stats.json の bands と同じ並び）
# (風速[m]がこれ以下, 帯の名前)
BANDS = [(1, "0-1m"), (3, "2-3m"), (5, "4-5m")]
BAND_LAST = "6m+"

# 風データの置き場所（このファイルからの相対パス）
STATS_PATH = os.path.join("history_data", "wind_stats.json")

# --------------------------------------------------------------------------

_cache = {}


def load_wind_stats(path=None):
    """wind_stats.json を読み込む（一度読んだら使い回す）。読めなければ None。"""
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [os.path.join(here, STATS_PATH), STATS_PATH]
    else:
        candidates = [path]
    for p in candidates:
        if p in _cache:
            return _cache[p]
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    _cache[p] = json.load(f)
                return _cache[p]
            except (OSError, ValueError):
                return None
    return None


def wind_band(speed):
    """風速[m]を風速帯の名前（"0-1m" など）に直す。数値でなければ None。"""
    try:
        v = float(speed)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    for upper, name in BANDS:
        if v < upper + 1:  # 1m → 0-1m、3m → 2-3m、5m → 4-5m（小数は切り下げ扱い）
            return name
    return BAND_LAST


def _find_venue(stats, venue):
    """会場名（"蒲郡"）または会場番号（7 / "7"）から、会場のデータを探す。"""
    venues = stats.get("venues", {})
    key = str(venue).strip()
    if key in venues:
        return venues[key]
    for v in venues.values():
        if v.get("name") == key:
            return v
    return None


def _result(shift=0.0, note="風補正なし", **extra):
    out = {"shift": shift, "note": note, "band": None, "est": None,
           "base": None, "diff": None, "n": None}
    out.update(extra)
    return out


def calc_wind_shift(venue, wind_speed, stats=None):
    """会場と風速から風補正を計算する。

    戻り値: {"shift": 補正の点数（足し引きする値）, "note": 画面に出す説明文,
             "band": 風速帯, "est": その帯の推定1着率, "base": 会場全体の1着率,
             "diff": est − base（%ポイント）, "n": その帯のレース数}
    風速・会場・データが分からないときは shift=0.0（通常版と同じ結果になる）。
    """
    if stats is None:
        stats = load_wind_stats()
    if not stats:
        return _result(note="風補正なし（wind_stats.json が読めません）")

    band = wind_band(wind_speed)
    if band is None:
        return _result(note="風補正なし（風速が取れていません）")

    v = _find_venue(stats, venue)
    if v is None:
        return _result(note=f"風補正なし（会場「{venue}」のデータがありません）", band=band)

    b = v.get("bands", {}).get(band)
    base = v.get("rate")
    if not b or base is None:
        return _result(note=f"風補正なし（{v.get('name', venue)}・風{band}のデータなし）", band=band)

    est = b.get("est")
    if est is None:
        # est がないときは、レース数が十分な場合だけ実測の1着率を使う
        reliable_n = stats.get("settings", {}).get("reliable_n", 100)
        if b.get("n", 0) >= reliable_n and b.get("rate") is not None:
            est = b["rate"]
        else:
            return _result(note=f"風補正なし（{v.get('name', venue)}・風{band}はレース数が少ない）",
                           band=band, n=b.get("n"))

    diff = est - base
    shift = max(-WIND_SHIFT_CAP, min(WIND_SHIFT_CAP, diff * POINTS_PER_PCT))
    shift = round(shift, 1)
    name = v.get("name", venue)
    note = (f"{name}・風{band}：1号艇の1着率 {est:.1f}%（会場平均 {base:.1f}%、"
            f"{diff:+.1f}%pt）→ 風補正 {shift:+.1f}点（n={b.get('n')}）")
    return _result(shift=shift, note=note, band=band, est=est, base=base,
                   diff=round(diff, 1), n=b.get("n"))


if __name__ == "__main__":
    # 動作確認：実データがあればそれを、なければ小さなサンプルで確認する
    st = load_wind_stats()
    if st is None:
        st = {"settings": {"reliable_n": 100}, "venues": {
            "7": {"name": "蒲郡", "rate": 56.1, "bands": {
                "0-1m": {"rate": 62.4, "n": 502, "est": 62.0},
                "2-3m": {"rate": 54.5, "n": 1220, "est": 54.6},
                "4-5m": {"rate": 53.1, "n": 335, "est": 53.3},
                "6m+": {"rate": 44.4, "n": 18, "est": 47.5}}}}}
        print("（wind_stats.json が見つからないのでサンプルで確認）")
    for sp in (0, 2, 4, 7, None):
        r = calc_wind_shift("蒲郡", sp, st)
        print(f"風速 {sp}: {r['note']}")
