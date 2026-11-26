"""trifecta_picker.py
1号艇が軸のレース向け：三連単の候補を採点順に並べる（最後の判断はオッズと照らして人間が行う）

【流れ】
1. 各艇を5項目（クラス・当地勝率・展示タイム・展示ST・モーター2連率）で採点（0〜100点）
2. 1号艇の点数が他艇の最高点とどれだけ差があるかで「堅い／荒れ」を自動判定
   （判定は従来どおり、艇番の補正なしの点数で行う）
3. 判定に応じて 4〜8点 の組み合わせを表示
   （候補の並び順は、艇番＝コースの補正を足した点数で決める）

【2026-10-29 の変更】
過去30日・約4600レースの検証で、内側の艇ほど上位に来やすい傾向を点数に足すと、
2・3着の順位予測と的中率が良くなった（検証期間：的中率 23.1% → 34.7%）。
そのため、候補の並び順だけに艇番の補正を足した。判定（堅い／荒れ）は変えていない。
荒れの表示点数は 10点 → 8点。

【2026-11-06 の追加】荒れ度（1〜5）
1号艇の点差から「1＝本命寄り 〜 5＝荒れる予想」を5段階で出す。
区切りは競艇記録ログ約200件を5等分した値を丸めたもの（LEVELS）。
判定（堅い／荒れ）や表示点数には影響しない。表示するだけ。

【2026-11-20 の変更】1号艇頭の最低点数（HEAD1_MIN）
競艇記録ログ約400件で、荒れ判定のうち本線の頭が1号艇以外のレース（98件）は、
頭の的中が23.5%、同じレースで1号艇が1着になったのは42.9%だった。
点数順だと、1号艇が負けている荒れでは「1号艇が頭の組み合わせ」が押し出されやすい。
そこで、表示点数が FREE_HEAD_FROM 以上（やや荒れ・荒れ）のとき、
表示する点数の中に「1号艇が頭の組み合わせ」を最低 HEAD1_MIN 点は入れる。
足りないときは、点数順で入っていない1号艇頭の組み合わせを上位から追加し、
その分、1号艇頭でない組み合わせを点数の低い順に外す。
判定・荒れ度・表示点数（n）は変わらない。HEAD1_MIN = 0 にすると従来どおり。

【2026-11-26 の追加】風補正（wind_shift）※参考用・記録には使わない
pick(boats, wind_shift=◯) と渡すと、1号艇の点数（判定用・並び順用の両方）に
その値を足し引きした「風考慮版」の候補が出る。プラスなら1号艇に有利、マイナスなら不利。
wind_shift を渡さない（または 0）なら、従来とまったく同じ結果になる。
補正の値は ±WIND_SHIFT_LIMIT で頭打ちにする。値の出し方（会場×風速帯の過去データから）は
別ファイルで作る予定。この関数は「渡された値を足すだけ」で、風のデータは読まない。

【入力の形】boats = 6艇分のリスト。足りない値は None でOK（その項目は中立扱い）
    {"boat": 1, "cls": "A1", "local": 7.12, "ex_time": 6.75, "ex_st": 0.12, "motor": 41.3}
    cls      : "A1" "A2" "B1" "B2"
    local    : 当地勝率
    ex_time  : 展示タイム（小さいほど良い）
    ex_st    : 展示ST（小さいほど良い。Fなど数値でないものは None 扱い）
    motor    : モーター2連率

【戻り値】pick(boats) → dict
    label        : 判定（堅い／やや堅い／やや荒れ／荒れ）
    level        : 荒れ度（1＝本命寄り 〜 5＝荒れる予想）
    gap          : 1号艇の点差（判定用の点数どうしの差）
    n            : 表示点数
    scores       : 各艇の点数（判定用。従来と同じ。風補正を渡したときは1号艇に反映）
    order_scores : 各艇の点数（候補の並び順用。艇番の補正つき。風補正を渡したときは1号艇に反映）
    combos       : [("1-3-5", 点数), ...]
    head1_added  : 1号艇頭の最低点数のために追加した組み合わせ（なければ空リスト）
    wind_shift   : 実際に使った風補正の値（頭打ち後。使っていなければ 0.0）

【Streamlit での使い方】
    from trifecta_picker import pick
    r = pick(boats)                      # 通常版（記録はこちら）
    rw = pick(boats, wind_shift=-6.0)    # 風考慮版（参考・記録しない）
    st.write(f"判定：{r['label']}（1号艇の点差 {r['gap']}）／荒れ度 {r['level']}/5 → {r['n']}点")
    st.dataframe([{"組み合わせ": c, "点数": s} for c, s in r["combos"]])
"""
from itertools import permutations

# ---- ここを変えると採点・判定が変わる（調整用） --------------------------

CLASS_POINT = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}

# 判定用：項目ごとの重み（大きいほど重視）。1号艇の点差の計算に使う
WEIGHTS = {"cls": 1.0, "local": 1.0, "ex_time": 1.5, "ex_st": 1.0, "motor": 1.0}

# 並び順用：判定用の重みに、艇番（コース）の補正 "course" を足したもの
# course は内側の艇ほど高い（1号艇が最大、6号艇が0）。0にすると従来の並び順に戻る
ORDER_WEIGHTS = {"cls": 1.0, "local": 1.0, "ex_time": 1.5, "ex_st": 1.0, "motor": 1.0,
                 "course": 4.0}

# 着順ごとの重み（1着・2着・3着）
POS_WEIGHT = (1.0, 0.7, 0.4)

# (1号艇の点差がこれ以上, 表示点数, ラベル) を上から順に判定
# 点差 = 1号艇の点数 − 他艇の最高点
TIERS = [
    (10, 4, "堅い"),
    (-5, 6, "やや堅い"),
    (-20, 8, "やや荒れ"),
    (None, 8, "荒れ"),
]

# 荒れ度（1＝本命寄り 〜 5＝荒れる予想）。判定の TIERS とは別に、表示用で使う
# (1号艇の点差がこれ以上, 荒れ度) を上から順に判定。どれにも当てはまらなければ 5
# 2026-11-06：ログ約200件を5等分した区切りを丸めた値
#   荒れ度ごとの1号艇1着率（ログ）：1=75% 2=67% 3=48% 4=54% 5=38%
LEVELS = [
    (13, 1),
    (-1, 2),
    (-15, 3),
    (-33, 4),
]
LEVEL_MAX = 5

# 表示点数がこの値以上なら、1号艇が1着以外（2・3着）の組み合わせも含める
FREE_HEAD_FROM = 8

# 2026-11-20：FREE_HEAD_FROM 以上のとき、表示点数の中に入れる
# 「1号艇が頭の組み合わせ」の最低点数。0にすると従来どおり（点数順のみ）
HEAD1_MIN = 2

# 2026-11-26：風補正（wind_shift）の上限。±この値で頭打ちにする（風考慮版の暴走防止）
WIND_SHIFT_LIMIT = 15.0

# --------------------------------------------------------------------------


def _to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _norm(values, higher_is_better=True):
    """最小〜最大を0〜1に直す。None は中央値で補う。"""
    known = sorted(v for v in values if v is not None)
    if not known:
        return [0.5] * len(values)
    mid = known[len(known) // 2]
    vals = [mid if v is None else v for v in values]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return [0.5] * len(vals)
    out = [(v - lo) / (hi - lo) for v in vals]
    return out if higher_is_better else [1 - x for x in out]


def score_boats(boats, weights=None):
    """各艇を0〜100点で採点して {艇番: 点数} を返す。

    weights を省略すると判定用の WEIGHTS を使う。
    weights に "course" を含めると、艇番（コース）の補正も加わる。
    """
    w = WEIGHTS if weights is None else weights
    cols = {
        "cls": ([CLASS_POINT.get(str(b.get("cls", "")).upper()) for b in boats], True),
        "local": ([_to_float(b.get("local")) for b in boats], True),
        "ex_time": ([_to_float(b.get("ex_time")) for b in boats], False),
        "ex_st": ([_to_float(b.get("ex_st")) for b in boats], False),
        "motor": ([_to_float(b.get("motor")) for b in boats], True),
    }
    if "course" in w:
        cols["course"] = ([7 - b["boat"] for b in boats], True)  # 内側ほど高い

    total_w = sum(w.values())
    scores = [0.0] * len(boats)
    for key, (vals, hib) in cols.items():
        if key not in w:
            continue
        for i, n in enumerate(_norm(vals, hib)):
            scores[i] += w[key] * n
    return {b["boat"]: round(s / total_w * 100, 1) for b, s in zip(boats, scores)}


def aredo(gap):
    """1号艇の点差から荒れ度（1＝本命寄り 〜 5＝荒れる予想）を返す。"""
    for min_gap, level in LEVELS:
        if gap >= min_gap:
            return level
    return LEVEL_MAX


def _is_head1(combo):
    """"1-3-5" のように、1号艇が頭の組み合わせか"""
    return combo[0].startswith("1-")


def _ensure_head1(combos, n, head1_min):
    """上位 n 点の中に、1号艇頭の組み合わせを最低 head1_min 点入れる。

    combos は点数の高い順に並んだ全候補。
    戻り値: (表示する n 点, 追加した組み合わせ名のリスト)
    """
    top = combos[:n]
    have = sum(1 for x in top if _is_head1(x))
    need = head1_min - have
    if need <= 0:
        return top, []

    # 点数順で入っていない1号艇頭を、上位から必要な分だけ追加
    extra = [x for x in combos[n:] if _is_head1(x)][:need]
    if not extra:
        return top, []

    # 1号艇頭でない組み合わせを、点数の低い順に同じ数だけ外す
    non_head1 = [x for x in top if not _is_head1(x)]
    drop = {x[0] for x in non_head1[-len(extra):]}
    new_top = [x for x in top if x[0] not in drop] + extra
    new_top.sort(key=lambda x: -x[1])
    return new_top, [x[0] for x in extra]


def _clamp_wind_shift(x):
    """風補正を ±WIND_SHIFT_LIMIT に収める。None・数値でないものは 0。"""
    v = _to_float(x)
    if v is None:
        return 0.0
    return max(-WIND_SHIFT_LIMIT, min(WIND_SHIFT_LIMIT, v))


def pick(boats, n_override=None, wind_shift=0.0):
    """候補の組み合わせを返す。

    戻り値: {"label": 判定, "level": 荒れ度, "gap": 1号艇の点差, "n": 表示点数,
             "scores": {艇番: 点数}, "order_scores": {艇番: 点数},
             "combos": [("1-3-5", 点数), ...], "head1_added": [追加した組み合わせ],
             "wind_shift": 使った風補正}
    n_override に点数を入れると、自動判定を使わず手動でその点数にできる。
    wind_shift に値を入れると、1号艇の点数にその値を足し引きした「風考慮版」になる
    （プラス＝1号艇に有利、マイナス＝不利）。0 または省略なら従来どおり。
    """
    judge = score_boats(boats)                 # 判定用（従来どおり）
    sc = score_boats(boats, ORDER_WEIGHTS)     # 並び順用（艇番の補正つき）
    if 1 not in judge:
        raise ValueError("1号艇のデータがありません")

    # 風補正：1号艇の点数だけに足し引きする（0なら何も変わらない）
    shift = _clamp_wind_shift(wind_shift)
    if shift:
        judge = {**judge, 1: round(judge[1] + shift, 1)}
        sc = {**sc, 1: round(sc[1] + shift, 1)}

    gap = judge[1] - max(v for k, v in judge.items() if k != 1)
    for min_gap, n, label in TIERS:
        if min_gap is None or gap >= min_gap:
            break
    if n_override:
        n = n_override
        label = "手動"

    free = n >= FREE_HEAD_FROM
    combos = []
    for a, b, c in permutations(sc.keys(), 3):
        if free:
            if 1 not in (a, b, c):
                continue
        elif a != 1:
            continue
        s = POS_WEIGHT[0] * sc[a] + POS_WEIGHT[1] * sc[b] + POS_WEIGHT[2] * sc[c]
        combos.append((f"{a}-{b}-{c}", round(s, 1)))
    combos.sort(key=lambda x: -x[1])

    if free and HEAD1_MIN > 0:
        shown, added = _ensure_head1(combos, n, HEAD1_MIN)
    else:
        shown, added = combos[:n], []

    return {
        "label": label,
        "level": aredo(round(gap, 1)),
        "gap": round(gap, 1),
        "n": n,
        "scores": judge,
        "order_scores": sc,
        "combos": shown,
        "head1_added": added,
        "wind_shift": shift,
    }


if __name__ == "__main__":
    # 動作確認用のサンプル（数値は適当）
    sample = [
        {"boat": 1, "cls": "A1", "local": 7.10, "ex_time": 6.74, "ex_st": 0.12, "motor": 42.0},
        {"boat": 2, "cls": "A2", "local": 6.20, "ex_time": 6.80, "ex_st": 0.15, "motor": 35.0},
        {"boat": 3, "cls": "B1", "local": 5.30, "ex_time": 6.78, "ex_st": 0.14, "motor": 38.0},
        {"boat": 4, "cls": "A2", "local": 6.00, "ex_time": 6.76, "ex_st": 0.11, "motor": 45.0},
        {"boat": 5, "cls": "B1", "local": 5.10, "ex_time": 6.82, "ex_st": None, "motor": 30.0},
        {"boat": 6, "cls": "B2", "local": 4.20, "ex_time": 6.85, "ex_st": 0.18, "motor": 28.0},
    ]
    r = pick(sample)
    print(f"判定：{r['label']}（点差 {r['gap']}）／荒れ度 {r['level']}/5 → {r['n']}点")
    print("各艇の点数（判定用）:", r["scores"])
    print("各艇の点数（並び順用）:", r["order_scores"])
    for combo, s in r["combos"]:
        print(combo, s)
    if r["head1_added"]:
        print("1号艇頭の最低点数で追加:", r["head1_added"])

    # 風考慮版のデモ（1号艇に不利な風を想定して -12 点）
    rw = pick(sample, wind_shift=-12.0)
    print()
    print(f"[風考慮版 wind_shift={rw['wind_shift']}] 判定：{rw['label']}"
          f"（点差 {rw['gap']}）／荒れ度 {rw['level']}/5 → {rw['n']}点")
    for combo, s in rw["combos"]:
        print(combo, s)
