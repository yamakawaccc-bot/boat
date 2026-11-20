# -*- coding: utf-8 -*-
"""会場のコース優劣・風速ごとのクセを一言で出す（参考表示。点数や買い目には使わない）

コース優劣: venue_stats.fetch_venue_stats() の結果（直近3か月のコース別成績）を使う。
風速のクセ: history_data/wind_stats.json（2026年の過去結果から作成。wind_stats.py）を使う。
app.py からは  import venue_note as vn  →  vn.show(st, vstats)  で呼ぶ。
風速のクセも出したいときは  vn.show(st, vstats, stadium_number=会場番号, wind_speed=風速)  と呼ぶ
（風速が分からなければ wind_speed を省略してよい。会場の風速別の表だけ出る）。
"""
import re

# 1コースの1着率で「イン強め／弱め」を決める目安（%）。しっくりこなければここを変える
IN_STRONG = 60.0   # これ以上 → イン強め
IN_WEAK = 52.0     # これ未満 → イン弱め

# ---- 風速のクセ（2026-11-20 追加） ------------------------------------------
# 風速別の数字が会場の平均より、これ以上（pt）低い／高いときに ▼ / ▲ を付ける
WIND_MARK_PT = 5.0
# ---------------------------------------------------------------------------

_WIND_CACHE = {"loaded": False, "stats": None}


def summarize(vstats):
    """会場のコース別1着率をまとめる。取れなければ None。
    戻り値: {"label": "イン強め", "by_course": [1〜6コースの1着率], "period": "..."}"""
    if not vstats:
        return None
    try:
        by_course = [float(vstats[c]["w1"]) for c in range(1, 7)]
    except (KeyError, TypeError, ValueError):
        return None
    w1 = by_course[0]
    if w1 >= IN_STRONG:
        label = "イン強め"
    elif w1 < IN_WEAK:
        label = "イン弱め"
    else:
        label = "標準"
    return {"label": label, "by_course": by_course, "period": vstats.get("period")}


# ---- 風速のクセ ---------------------------------------------------------------
def _load_wind_stats():
    """wind_stats.json を1回だけ読む。読めなければ None（風速の表示だけが出なくなる）。"""
    if not _WIND_CACHE["loaded"]:
        _WIND_CACHE["loaded"] = True
        try:
            from wind_stats import load_wind_stats
            _WIND_CACHE["stats"] = load_wind_stats()
        except Exception:  # noqa: BLE001  ファイルが無い等。表示しないだけにする
            _WIND_CACHE["stats"] = None
    return _WIND_CACHE["stats"]


def _to_meters(wind_speed):
    """風速を整数のmにする。'3m' '3.0' 3 などに対応。分からなければ None。"""
    if wind_speed is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(wind_speed))
    if not m:
        return None
    return int(round(float(m.group())))


def wind_note(stats, stadium_number, wind_speed=None):
    """風速のクセの表示用データを作る。取れなければ None。
    戻り値: {"name": 会場名, "venue_rate": 会場平均, "table": [(風速帯, 数字, 参考か), ...],
             "now": None または {"meters","band","value","diff","reference","mark"}}
    数字は、レースが十分あれば実際の1着率、少なければ補正値（reference=True）。"""
    if not stats:
        return None
    try:
        v = stats["venues"][str(int(stadium_number))]
        bands = stats["bands"]
        reliable_n = stats.get("settings", {}).get("reliable_n", 100)
    except (KeyError, TypeError, ValueError):
        return None

    def value_of(b):
        reference = b["n"] < reliable_n
        return (b["est"] if reference else b["rate"]), reference

    table = []
    for name in bands:
        val, ref = value_of(v["bands"][name])
        table.append((name, val, ref))

    now = None
    meters = _to_meters(wind_speed)
    if meters is not None:
        try:
            from wind_report import band_of
            band = band_of(meters)
        except Exception:  # noqa: BLE001
            band = None
        if band in v["bands"]:
            val, ref = value_of(v["bands"][band])
            diff = val - v["rate"]
            mark = "▼" if diff <= -WIND_MARK_PT else ("▲" if diff >= WIND_MARK_PT else "")
            now = {"meters": meters, "band": band, "value": val, "diff": diff,
                   "reference": ref, "mark": mark}
    return {"name": v["name"], "venue_rate": v["rate"], "table": table, "now": now}


def _show_wind(st, stadium_number, wind_speed):
    note = wind_note(_load_wind_stats(), stadium_number, wind_speed)
    if note is None:
        return
    lines = []
    if note["now"]:
        n = note["now"]
        tail = "（レース少なめ・参考）" if n["reference"] else ""
        lines.append(
            f"風速のクセ：風速{n['meters']}m（{n['band']}）の1号艇1着率 **約{n['value']:.0f}%**{n['mark']}"
            f"（会場平均{note['venue_rate']:.0f}%、{n['diff']:+.0f}pt）{tail}")
    table = " / ".join(f"{b}:{v:.0f}{'*' if ref else ''}" for b, v, ref in note["table"])
    lines.append(f"風速別の1号艇1着率(%)　{table}")
    foot = "※2026年の過去結果から集計。参考表示です（点数には使っていません）"
    if any(ref for _, _, ref in note["table"]):
        foot += "　*はレース少なめ"
    lines.append(foot)
    st.caption("  \n".join(lines))


def show(st, vstats, stadium_number=None, wind_speed=None):
    """Streamlitの画面に、会場のクセを小さく表示する（取れなければ何も出さない）。
    stadium_number を渡すと、風速のクセも出す（wind_speed は省略可）。"""
    s = summarize(vstats)
    if s is not None:
        nums = " / ".join(f"{c}:{v:.1f}" for c, v in enumerate(s["by_course"], 1))
        lines = [f"会場のクセ：**{s['label']}**（1コース1着率 {s['by_course'][0]:.1f}%）",
                 f"コース別1着率(%)　{nums}"]
        if s["period"]:
            lines.append(f"集計 {s['period']}　※参考表示です（点数には使っていません）")
        st.caption("  \n".join(lines))  # 行末の空白2つ＝改行

    if stadium_number is not None:
        _show_wind(st, stadium_number, wind_speed)
