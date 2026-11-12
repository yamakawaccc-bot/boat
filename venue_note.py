# -*- coding: utf-8 -*-
"""会場のコース優劣を一言で出す（参考表示。点数や買い目には使わない）

venue_stats.fetch_venue_stats() の結果（直近3か月のコース別成績）を使う。
app.py からは  import venue_note as vn  →  vn.show(st, vstats)  で呼ぶ。
"""

# 1コースの1着率で「イン強め／弱め」を決める目安（%）。しっくりこなければここを変える
IN_STRONG = 60.0   # これ以上 → イン強め
IN_WEAK = 52.0     # これ未満 → イン弱め


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


def show(st, vstats):
    """Streamlitの画面に、会場のクセを小さく表示する（取れなければ何も出さない）。"""
    s = summarize(vstats)
    if s is None:
        return
    nums = " / ".join(f"{c}:{v:.1f}" for c, v in enumerate(s["by_course"], 1))
    lines = [f"会場のクセ：**{s['label']}**（1コース1着率 {s['by_course'][0]:.1f}%）",
             f"コース別1着率(%)　{nums}"]
    if s["period"]:
        lines.append(f"集計 {s['period']}　※参考表示です（点数には使っていません）")
    st.caption("  \n".join(lines))  # 行末の空白2つ＝改行
