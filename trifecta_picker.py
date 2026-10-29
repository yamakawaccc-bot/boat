"""trifecta_picker.py
1号艇が軸のレース向け：三連単の候補を採点順に並べる（最後の判断はオッズと照らして人間が行う）

【流れ】
1. 各艇を4項目（クラス・当地勝率・展示タイム・展示ST・モーター2連率）で採点（0〜100点）
2. 1号艇の点数が他艇の最高点とどれだけ差があるかで「堅い／荒れ」を自動判定
3. 判定に応じて 4〜10点 の組み合わせを表示

【入力の形】boats = 6艇分のリスト。足りない値は None でOK（その項目は中立扱い）
    {"boat": 1, "cls": "A1", "local": 7.12, "ex_time": 6.75, "ex_st": 0.12, "motor": 41.3}
    cls      : "A1" "A2" "B1" "B2"
    local    : 当地勝率
    ex_time  : 展示タイム（小さいほど良い）
    ex_st    : 展示ST（小さいほど良い。Fなど数値でないものは None 扱い）
    motor    : モーター2連率

【Streamlit での使い方】
    from trifecta_picker import pick
    r = pick(boats)
    st.write(f"判定：{r['label']}（1号艇の点差 {r['gap']}）→ {r['n']}点")
    st.dataframe([{"組み合わせ": c, "点数": s} for c, s in r["combos"]])
"""
from itertools import permutations

# ---- ここを変えると採点・判定が変わる（調整用） --------------------------

CLASS_POINT = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}

# 項目ごとの重み（大きいほど重視）
WEIGHTS = {"cls": 1.0, "local": 1.0, "ex_time": 1.5, "ex_st": 1.0, "motor": 1.0}

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

# 表示点数がこの値以上なら、1号艇が1着以外（2・3着）の組み合わせも含める
FREE_HEAD_FROM = 8

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


def score_boats(boats):
    """各艇を0〜100点で採点して {艇番: 点数} を返す。"""
    cols = {
        "cls": ([CLASS_POINT.get(str(b.get("cls", "")).upper()) for b in boats], True),
        "local": ([_to_float(b.get("local")) for b in boats], True),
        "ex_time": ([_to_float(b.get("ex_time")) for b in boats], False),
        "ex_st": ([_to_float(b.get("ex_st")) for b in boats], False),
        "motor": ([_to_float(b.get("motor")) for b in boats], True),
    }
    total_w = sum(WEIGHTS.values())
    scores = [0.0] * len(boats)
    for key, (vals, hib) in cols.items():
        for i, n in enumerate(_norm(vals, hib)):
            scores[i] += WEIGHTS[key] * n
    return {b["boat"]: round(s / total_w * 100, 1) for b, s in zip(boats, scores)}


def pick(boats, n_override=None):
    """候補の組み合わせを返す。

    戻り値: {"label": 判定, "gap": 1号艇の点差, "n": 表示点数,
             "scores": {艇番: 点数}, "combos": [("1-3-5", 点数), ...]}
    n_override に点数を入れると、自動判定を使わず手動でその点数にできる。
    """
    sc = score_boats(boats)
    if 1 not in sc:
        raise ValueError("1号艇のデータがありません")

    gap = sc[1] - max(v for k, v in sc.items() if k != 1)
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

    return {
        "label": label,
        "gap": round(gap, 1),
        "n": n,
        "scores": sc,
        "combos": combos[:n],
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
    print(f"判定：{r['label']}（点差 {r['gap']}）→ {r['n']}点")
    print("各艇の点数:", r["scores"])
    for combo, s in r["combos"]:
        print(combo, s)
