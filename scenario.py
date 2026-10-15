# -*- coding: utf-8 -*-
"""展開の目安（段階1：ルールによる推定）

表のデータから「逃げ」「まくり・差し」などの展開を文章にする。
数字の傾向を整理するだけの簡易ルールで、的中を保証するものではない。
"""
import pandas as pd

# 判定の目安（ここの数字を変えると判定が変わる）
ST_GAP_BIG = 0.04      # 1号艇が2〜4号艇よりこれ以上遅いと「かなり遅い」
ST_GAP_SMALL = 0.02    # これ以上なら「やや遅い」
ATTACK_ST_GAP = 0.03   # 1号艇よりこれ以上速いと「攻める側」の材料
MOTOR_HIGH = 40.0      # モーター2連率が高めの目安
ATTACK_MIN_SCORE = 3   # 攻める艇と判定する点数
SPREAD_SMALL = 0.12    # 展示タイムの差がこれ未満なら「差が小さい」
INN_STRONG = 58.0      # 会場の1コース1着率がこれ以上なら「イン強い」
INN_WEAK = 52.0        # これ以下なら「イン弱め」
BASE_WIN = {2: 13.0, 3: 12.5, 4: 10.5, 5: 6.0, 6: 2.0}  # 全国的な目安（1着率%）
COURSE_BONUS_GAP = 2.0 # 会場のコース1着率が目安よりこれ以上高ければ加点
KM_MIN_SHARE = 30.0    # 決まり手の割合がこれ以上なら、その会場の傾向として使う

STYLE = {2: "差し", 3: "まくり", 4: "まくり／まくり差し",
         5: "まくり差し（外から展開待ち）", 6: "まくり差し（外から展開待ち）"}


def _v(rec, key):
    v = rec.get(key)
    return None if v is None or pd.isna(v) else v


def _idx(rec):
    """スタート指標：展示STと平均STの平均（小さいほど速い）。"""
    vals = [x for x in (_v(rec, "start_exhibition_st"), _v(rec, "avg_st"))
            if x is not None]
    return sum(vals) / len(vals) if vals else None


def _rank_map(vals, reverse=False):
    items = {c: v for c, v in vals.items() if v is not None}
    return {c: 1 + sum(1 for x in items.values() if (x > v if reverse else x < v))
            for c, v in items.items()}


def _f_flag(rec):
    f = rec.get("start_exhibition_f")
    return bool(f) if pd.notna(f) else False


def _style(c, venue):
    """そのコースの攻め方。会場データがあれば、その会場で多い決まり手を使う。"""
    if venue and c in venue:
        km = {k: venue[c]["km"].get(k, 0.0) for k in ("まくり", "差し", "まくり差し")}
        best = max(km, key=km.get)
        if km[best] >= KM_MIN_SHARE:
            return best
    return STYLE[c]


def _venue_text(venue):
    parts = []
    v1 = venue.get(1, {}).get("w1")
    if v1 is not None:
        tag = "強め" if v1 >= INN_STRONG else ("弱め" if v1 <= INN_WEAK else "標準的")
        parts.append(f"1コース1着率{v1:.1f}%（全国の目安は55%前後、{tag}）")
    km_parts = []
    for c in (2, 3, 4):
        d = venue.get(c)
        if not d:
            continue
        km = {k: d["km"].get(k, 0.0) for k in ("まくり", "差し", "まくり差し")}
        best = max(km, key=km.get)
        km_parts.append(f"{c}コース{best}{km[best]:.0f}%")
    if km_parts:
        parts.append("決まり手の傾向は" + "、".join(km_parts))
    period = venue.get("period")
    tail = f"（集計 {period}）" if period else ""
    return "。".join(parts) + "。" + tail


def _names(cs):
    return "・".join(f"{c}号艇" for c in cs)


def build_scenarios(df, wind=None, wave=None, venue=None):
    """[(見出し, 本文), ...] を返す。"""
    boats = {int(r["course"]): r for r in df.to_dict("records")}
    if 1 not in boats or len(boats) < 5:
        return [("展開", "艇のデータがそろってから表示します。")]

    idx = {c: _idx(r) for c, r in boats.items()}
    ex_rank = _rank_map({c: _v(r, "exhibition_time") for c, r in boats.items()})
    st_rank = _rank_map(idx)
    mo = {c: _v(r, "motor_2rate") for c, r in boats.items()}
    mo_rank = _rank_map(mo, reverse=True)

    # --- 1号艇の逃げ ---
    s1, why1 = 0, []
    r1 = ex_rank.get(1)
    if r1 is not None:
        if r1 <= 2:
            s1 += 1
            why1.append("展示タイムが上位")
        elif r1 >= 5:
            s1 -= 1
            why1.append("展示タイムが下位")
    others = [idx[c] for c in (2, 3, 4) if idx.get(c) is not None]
    if idx.get(1) is not None and others:
        gap = idx[1] - min(others)
        if gap >= ST_GAP_BIG:
            s1 -= 2
            why1.append(f"スタートが2〜4号艇より{gap:.2f}秒ほど遅め")
        elif gap >= ST_GAP_SMALL:
            s1 -= 1
            why1.append("スタートが2〜4号艇よりやや遅め")
        elif gap <= -ST_GAP_SMALL:
            s1 += 1
            why1.append("スタートが2〜4号艇より速め")
    cls1 = boats[1].get("racer_class")
    if cls1 in ("A1", "A2"):
        s1 += 1
        why1.append(f"級別が{cls1}")
    elif cls1 == "B2":
        s1 -= 1
        why1.append("級別が低め（B2）")
    v1 = venue.get(1, {}).get("w1") if venue else None
    if v1 is not None:
        if v1 >= INN_STRONG:
            s1 += 1
            why1.append(f"この会場は1コースが強い（1着率{v1:.0f}%）")
        elif v1 <= INN_WEAK:
            s1 -= 1
            why1.append(f"この会場は1コースが弱め（1着率{v1:.0f}%）")
    verdict = "有利" if s1 >= 2 else ("五分" if s1 >= 0 else "不利")
    out = [("1号艇の逃げ",
            f"{verdict}。" + ("、".join(why1) if why1 else "材料が少なく判断しにくい"))]

    if venue:
        out.insert(0, ("会場のクセ", _venue_text(venue)))

    # --- 攻める艇 ---
    atk = []
    for c in range(2, 7):
        if c not in boats:
            continue
        sc, why = 0, []
        if idx.get(c) is not None and idx.get(1) is not None \
                and idx[1] - idx[c] >= ATTACK_ST_GAP:
            sc += 1
            why.append("スタートが1号艇より速い")
        if st_rank.get(c) == 1:
            sc += 1
            why.append("スタート指標が最上位")
        if _f_flag(boats[c]):
            sc += 1
            why.append("展示でF（踏み込む気配）")
        if ex_rank.get(c) is not None and ex_rank[c] <= 2:
            sc += 1
            why.append("展示タイム上位")
        if mo.get(c) is not None and mo[c] >= MOTOR_HIGH:
            sc += 1
            why.append("モーター2連率が高め")
        if venue and c in venue and c in BASE_WIN \
                and venue[c]["w1"] - BASE_WIN[c] >= COURSE_BONUS_GAP:
            sc += 1
            why.append(f"この会場は{c}コースの1着率が高め（{venue[c]['w1']:.0f}%）")
        if sc >= ATTACK_MIN_SCORE:
            atk.append((-sc, ex_rank.get(c) or 9, c, why))
    atk.sort()
    atk = atk[:2]
    if atk:
        out.append(("攻めそうな艇", "　".join(
            f"{c}号艇（{_style(c, venue)}）＝{'、'.join(w)}" for _, _, c, w in atk)))
    else:
        out.append(("攻めそうな艇", "目立って攻めそうな艇は見当たりません。"))

    # --- 展開のイメージ ---
    ac = [c for _, _, c, _ in atk]
    if s1 >= 2 and not ac:
        img = "1号艇が逃げる形が本線。相手は足の良い艇から探す展開です。"
    elif s1 >= 2:
        img = f"1号艇の逃げが本線。{_names(ac)}が攻めれば、差し・まくり差しで絡みます。"
    elif s1 < 0 and ac:
        img = f"{_names(ac)}の攻めが決まれば、1号艇は押し出される形もありえます。"
    elif s1 < 0:
        img = "1号艇の逃げにやや不安。ただ、攻める艇が目立たず、混戦になりやすい形です。"
    elif ac:
        img = f"1号艇の逃げと、{_names(ac)}の攻めが拮抗する形です。"
    else:
        img = "目立った攻め筋はなく、1号艇が先行する形が中心です。"
    out.append(("展開のイメージ", img))

    # --- 足・スタートで目立つ艇 ---
    tot = []
    for c in boats:
        rs = [x for x in (ex_rank.get(c), st_rank.get(c), mo_rank.get(c))
              if x is not None]
        if len(rs) >= 2:
            tot.append((sum(rs) / len(rs), c))
    tot.sort()
    if tot:
        out.append(("足・スタートで目立つ艇",
                    "、".join(f"{c}号艇" for _, c in tot[:2])
                    + "（展示・スタート・モーターの順位の平均が良い艇）"))

    # --- 注意点 ---
    notes = []
    fx = [c for c in sorted(boats) if _f_flag(boats[c])]
    if fx:
        notes.append(f"{_names(fx)}は展示でF。本番もスタートで攻める可能性があります。")
    fh = [c for c in sorted(boats)
          if (_v(boats[c], "f_count") or 0) >= 1]
    if fh:
        notes.append(f"{_names(fh)}はF持ち。スタートを慎重にする可能性があります。")
    times = [r["exhibition_time"] for r in boats.values()
             if _v(r, "exhibition_time") is not None]
    if len(times) >= 5 and max(times) - min(times) < SPREAD_SMALL:
        notes.append(f"展示タイムの差は{max(times) - min(times):.2f}秒と小さく、"
                     "足だけでは決まりにくいです。")
    if wind is not None and not pd.isna(wind) and wind >= 5:
        notes.append("風が強く、スタートや展開が荒れやすい水面です（風向きは未反映）。")
    if wave is not None and not pd.isna(wave) and wave >= 5:
        notes.append("波があり、ターンが難しい水面です。ミスや転覆に注意。")
    if notes:
        out.append(("注意点", "　".join(notes)))
    return out
