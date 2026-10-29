"""tune_picker.py
analyze_picker.py の続き。標準ライブラリだけで動く。
trifecta_picker.py と analyze_picker.py と同じフォルダに置くこと。

やること
  ■1 使ったデータ（訓練期間と検証期間の分け方）
  ■2 展示STの中身（マイナス・なし・値の大きさと着順の関係）
  ■3 点数の重みの調整
       A 現行
       B 現行＋艇番（コース）の補正だけ足す
       C 全項目の重みを調整
     古い20日で重みを探し、新しい10日で成績を確認する（合わせすぎの防止）
  ■4 候補の的中率・回収率（判定は現行のまま、候補の並び順だけ変える）

使い方
    python tune_picker.py
GitHub Actions なら tune_picker.yml を手動実行（workflow_dispatch）。
"""
import sys
from collections import defaultdict
from datetime import date, timedelta
from itertools import permutations

import trifecta_picker as tp
from analyze_picker import (CLASS_MAP, KINDS, LOCAL_KEY, MOTOR_KEY, boats_of,
                            fetch, keyed_races, num)

DAYS = 30       # 何日前まで使うか（うまくいけば90などに増やす）
TEST_DAYS = 10  # 新しい方の何日を検証に使うか（残りの古い日で重みを探す）

KEYS = ["cls", "local", "ex_time", "ex_st", "motor", "course"]
LABELS = {"cls": "級別", "local": "当地", "ex_time": "展示T", "ex_st": "展示ST",
          "motor": "モーター", "course": "艇番"}
GRID = (0, 0.5, 1, 1.5, 2, 3, 4, 6)  # 重みの候補
TRIPLES = list(permutations(range(6), 3))


# ---- データの組み立て ---------------------------------------------------------

def make_race(prog, prev, res, off, skipped):
    pb = {b.get("racer_boat_number"): b for b in boats_of(prog)}
    vb = {b.get("racer_boat_number"): b for b in boats_of(prev)}
    rb = {b.get("racer_boat_number"): b for b in boats_of(res)}
    want = [1, 2, 3, 4, 5, 6]
    if sorted(pb) != want or sorted(vb) != want:
        skipped["6艇そろわず"] += 1
        return None

    place = {}
    places = defaultdict(list)
    for n, b in rb.items():
        pl = num(b.get("racer_place_number"))
        if pl is not None:
            place[n] = int(pl)
            places[int(pl)].append(n)
    if any(len(places.get(i, [])) != 1 for i in (1, 2, 3)):
        skipped["着順が不明（中止など）"] += 1
        return None
    order = (places[1][0], places[2][0], places[3][0])
    combo = "-".join(str(x) for x in order)

    pays = {}
    for x in (res.get("payouts") or {}).get("trifecta") or []:
        pays[x.get("combination")] = num(x.get("payout"))
    pay = pays.get(combo)
    if pay is None:
        skipped["三連単の払戻なし"] += 1
        return None

    boats = []
    st_raw = []
    for n in want:
        st = num(vb[n].get("racer_start_timing"))
        st_raw.append(st)
        boats.append({
            "boat": n,
            "cls": CLASS_MAP.get(pb[n].get("racer_class_number")),
            "local": pb[n].get(LOCAL_KEY),
            "ex_time": vb[n].get("racer_exhibition_time"),
            "ex_st": None if (st is not None and st < 0) else st,  # アプリと同じ扱い
            "motor": pb[n].get(MOTOR_KEY),
        })

    cols = {
        "cls": ([tp.CLASS_POINT.get(str(b["cls"]).upper()) for b in boats], True),
        "local": ([tp._to_float(b["local"]) for b in boats], True),
        "ex_time": ([tp._to_float(b["ex_time"]) for b in boats], False),
        "ex_st": ([tp._to_float(b["ex_st"]) for b in boats], False),
        "motor": ([tp._to_float(b["motor"]) for b in boats], True),
    }
    feat = {k: tp._norm(v, hib) for k, (v, hib) in cols.items()}
    feat["course"] = [(6 - i) / 5 for i in range(6)]  # 1号艇=1.0 〜 6号艇=0.0

    cur = tp.pick(boats)
    return {
        "off": off, "feat": feat, "pay": pay, "n": cur["n"], "label": cur["label"],
        "order_idx": tuple(x - 1 for x in order),
        "st_raw": st_raw, "place": [place.get(n) for n in want],
        "cur_hit": combo in [c for c, _ in cur["combos"]],
    }


def load_races():
    races = []
    skipped = defaultdict(int)
    today = date.today()
    for off in range(1, DAYS + 1):
        d = today - timedelta(days=off)
        data = {k: fetch(k, d) for k in KINDS}
        if any(v is None for v in data.values()):
            skipped["取得できなかった日"] += 1
            continue
        prog, prev, res = (keyed_races(data[k]) for k in KINDS)
        for key in sorted(set(prog) & set(prev) & set(res)):
            r = make_race(prog[key], prev[key], res[key], off, skipped)
            if r:
                races.append(r)
    return races, skipped


# ---- 採点と評価 ---------------------------------------------------------------

def scores(feat, w):
    tot = sum(w.values())
    return [round(sum(w[k] * feat[k][i] for k in KEYS) / tot * 100, 1) for i in range(6)]


def rank_of(s, j):
    higher = sum(1 for x in s if x > s[j])
    same = sum(1 for x in s if x == s[j])
    return higher + (same + 1) / 2


def evaluate(races, w):
    """(1着艇, 2着艇, 3着艇の順位の平均, 上位3艇の的中数の平均)"""
    r = [0.0, 0.0, 0.0]
    ov = 0
    for race in races:
        s = scores(race["feat"], w)
        oi = race["order_idx"]
        for p in range(3):
            r[p] += rank_of(s, oi[p])
        top3 = sorted(range(6), key=lambda i: (-s[i], i))[:3]
        ov += len(set(top3) & set(oi))
    n = len(races)
    return r[0] / n, r[1] / n, r[2] / n, ov / n


def objective(races, w):
    a, b, c, _ = evaluate(races, w)
    return a + b + c


def search(train, w0, keys):
    """1項目ずつ重みを動かして、訓練期間の成績が良くなる形を探す。"""
    w = dict(w0)
    best = objective(train, w)
    for _ in range(4):
        improved = False
        for k in keys:
            for v in GRID:
                if v == w[k]:
                    continue
                trial = dict(w)
                trial[k] = v
                if sum(trial.values()) == 0:
                    continue
                o = objective(train, trial)
                if o < best - 1e-9:
                    best, w, improved = o, trial, True
        if not improved:
            break
    return w


def replay(races, w):
    """判定（点数n）は現行のまま、候補の並び順だけ w の採点で決める。"""
    pw = tp.POS_WEIGHT
    h = stake = ret = 0
    for r in races:
        s = scores(r["feat"], w)
        n = r["n"]
        free = n >= tp.FREE_HEAD_FROM
        combos = []
        for a, b, c in TRIPLES:
            if free:
                if 0 not in (a, b, c):
                    continue
            elif a != 0:
                continue
            combos.append((round(pw[0] * s[a] + pw[1] * s[b] + pw[2] * s[c], 1), (a, b, c)))
        combos.sort(key=lambda x: -x[0])
        stake += n * 100
        if r["order_idx"] in [c for _, c in combos[:n]]:
            h += 1
            ret += r["pay"]
    return len(races), h, stake, ret


# ---- 各セクション -------------------------------------------------------------

def section1(races, skipped, train, test):
    print("■ 1. 使ったデータ")
    print(f"  使えたレース: {len(races)}（{DAYS}日分）")
    for k, v in skipped.items():
        print(f"  除外: {k} {v}")
    print(f"  訓練（古い{DAYS - TEST_DAYS}日）: {len(train)}レース / 検証（新しい{TEST_DAYS}日）: {len(test)}レース")


def section2(races):
    print("\n■ 2. 展示STと着順（全艇）")
    print("   艇数  1着  3着内 平均着順")
    bins = [("マイナス", lambda s: s is not None and s < 0),
            ("なし", lambda s: s is None),
            ("0.05以下", lambda s: s is not None and 0 <= s <= 0.05),
            ("0.06〜0.10", lambda s: s is not None and 0.05 < s <= 0.10),
            ("0.11〜0.15", lambda s: s is not None and 0.10 < s <= 0.15),
            ("0.16〜0.20", lambda s: s is not None and 0.15 < s <= 0.20),
            ("0.21以上", lambda s: s is not None and s > 0.20)]
    rows = [(name, [], f) for name, f in bins]
    allp = []
    for r in races:
        for s, pl in zip(r["st_raw"], r["place"]):
            if pl is None:
                continue
            allp.append(pl)
            for name, lst, f in rows:
                if f(s):
                    lst.append(pl)

    def line(label, ps):
        if not ps:
            print(f"  {0:>5}    -     -     -   {label}")
            return
        n = len(ps)
        print(f"  {n:>5} {sum(p == 1 for p in ps) / n * 100:>3.0f}% {sum(p <= 3 for p in ps) / n * 100:>4.0f}% {sum(ps) / n:>6.2f}   {label}")

    for name, lst, _ in rows:
        line(name, lst)
    line("全体", allp)


def section3_4(train, test, races):
    now = dict(tp.WEIGHTS)
    wa = {**now, "course": 0.0}
    wb = search(train, wa, ["course"])
    wc = search(train, wa, KEYS)
    variants = [("A", wa), ("B", wb), ("C", wc)]

    print("\n■ 3. 重みの調整（古い期間で探索 → 新しい期間で確認）")
    print("  A=現行  B=現行＋艇番の補正だけ追加  C=全項目を調整")
    for name, w in variants:
        print(f"  {name} " + " ".join(f"{LABELS[k]}{w[k]:g}" for k in KEYS))
    print("  （重みは割合だけが意味を持つ。全体を2倍にしても同じ）")

    print("\n  順位の平均（検証期間。小さいほど良い）")
    print("      1着艇 2着艇 3着艇 上位3艇の的中数")
    print("  ー  3.50  3.50  3.50   1.50（でたらめ）")
    for name, w in variants:
        a, b, c, ov = evaluate(test, w)
        print(f"  {name}  {a:>5.2f} {b:>5.2f} {c:>5.2f}   {ov:>5.2f}")
    print("  （上位3艇の的中数 = 点数上位3艇のうち3着内に入った数の平均）")
    print("  3艇の順位の合計（訓練 → 検証）:")
    for name, w in variants:
        print(f"    {name}  {objective(train, w):.2f} → {objective(test, w):.2f}")

    print("\n■ 4. 候補の的中率・回収率（判定は現行のまま、並び順だけ変更）")
    print("     訓練期間      検証期間")
    print("    的中%  回収%  的中%  回収%")
    for name, w in variants:
        cells = []
        for part in (train, test):
            n, h, stake, ret = replay(part, w)
            cells.append(f"{h / n * 100:>5.1f} {ret / stake * 100:>6.1f}")
        print(f"  {name} {cells[0]}  {cells[1]}")
    h = sum(r["cur_hit"] for r in races)
    n, h2, _, _ = replay(races, wa)
    print(f"  （現行の再現チェック: 全体の的中 {h}件 と {h2}件 → {'一致' if h == h2 else '少しズレあり'}）")
    print("  回収率は大きな配当でぶれるので、的中率の動きを重視してください")


def main():
    races, skipped = load_races()
    if not races:
        print("使えるレースがありません。URLやネットワークを確認してください。")
        return 1
    train = [r for r in races if r["off"] > TEST_DAYS]
    test = [r for r in races if r["off"] <= TEST_DAYS]
    section1(races, skipped, train, test)
    section2(races)
    section3_4(train, test, races)
    return 0


if __name__ == "__main__":
    sys.exit(main())
