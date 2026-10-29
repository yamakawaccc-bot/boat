"""analyze_picker.py
Boatrace Open API の出走表・直前情報・結果を過去30日分つないで、
今の trifecta_picker.py（点数ロジック）の成績を調べる。標準ライブラリだけで動く。
trifecta_picker.py と同じフォルダに置くこと。

出力
  ■1 使ったデータの確認
  ■2 今のロジックの的中率・回収率（判定ごと）
  ■3 スコア順位と実際の着順の関係（2・3着がどれだけ当たっているか）
  ■4 艇番別の着順
  ■5 項目ごとの予測力（2・3着の順位予測。どの項目が効いているか）

使い方
    python analyze_picker.py
GitHub Actions なら analyze_picker.yml を手動実行（workflow_dispatch）。
"""
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

import trifecta_picker as tp

BASE = "https://boatraceopenapi.github.io/{kind}/v2/{y}/{ymd}.json"
KINDS = ["programs", "previews", "results"]
DAYS = 30  # 何日前まで使うか（うまくいけば90などに増やす）

# Open APIの項目 → pick()の入力への対応（ここを変えると別の項目で試せる）
CLASS_MAP = {1: "A1", 2: "A2", 3: "B1", 4: "B2"}
LOCAL_KEY = "racer_local_top_2_percent"  # 当地勝率の代わりに当地2連率を使う
MOTOR_KEY = "racer_assigned_motor_top_2_percent"


# ---- 取得 ------------------------------------------------------------------

def fetch(kind, d):
    url = BASE.format(kind=kind, y=d.year, ymd=d.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "analyze-picker"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  取得エラー {kind} {d}: HTTP {e.code}")
        data = None
    except Exception as e:
        print(f"  取得エラー {kind} {d}: {e}")
        data = None
    time.sleep(0.2)
    return data


def race_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def boats_of(race):
    for v in race.values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "racer_boat_number" in v[0]:
            return v
    return []


def keyed_races(data):
    keyed = {}
    for r in race_list(data):
        k = (r.get("race_stadium_number"), r.get("race_number"))
        if None not in k:
            keyed[k] = r
    return keyed


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---- レースの組み立て ---------------------------------------------------------

def make_race(prog, prev, res, skipped):
    pb = {b.get("racer_boat_number"): b for b in boats_of(prog)}
    vb = {b.get("racer_boat_number"): b for b in boats_of(prev)}
    rb = {b.get("racer_boat_number"): b for b in boats_of(res)}
    want = [1, 2, 3, 4, 5, 6]
    if sorted(pb) != want or sorted(vb) != want:
        skipped["6艇そろわず"] += 1
        return None

    places = defaultdict(list)
    for n, b in rb.items():
        pl = num(b.get("racer_place_number"))
        if pl is not None:
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
    for n in want:
        st = num(vb[n].get("racer_start_timing"))
        if st is not None and st < 0:  # マイナスはF扱い。アプリと同じく数値なし(None)にする
            st = None
        boats.append({
            "boat": n,
            "cls": CLASS_MAP.get(pb[n].get("racer_class_number")),
            "local": pb[n].get(LOCAL_KEY),
            "ex_time": vb[n].get("racer_exhibition_time"),
            "ex_st": st,
            "motor": pb[n].get(MOTOR_KEY),
        })
    return {"boats": boats, "order": order, "combo": combo, "pay": pay,
            "cls_raw": [pb[n].get("racer_class_number") for n in want]}


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
            r = make_race(prog[key], prev[key], res[key], skipped)
            if r:
                races.append(r)
    return races, skipped


# ---- 集計の部品 ---------------------------------------------------------------

def avg_ranks(scores):
    """{艇: 点数} → {艇: 順位}（1が最高。同点は平均順位）"""
    out = {}
    for b, s in scores.items():
        higher = sum(1 for x in scores.values() if x > s)
        same = sum(1 for x in scores.values() if x == s)
        out[b] = higher + (same + 1) / 2
    return out


def scorer_with(weights):
    """項目の重みを一時的に差し替えて採点する関数を返す。"""
    def f(boats):
        old = dict(tp.WEIGHTS)
        tp.WEIGHTS.clear()
        tp.WEIGHTS.update(weights)
        try:
            return tp.score_boats(boats)
        finally:
            tp.WEIGHTS.clear()
            tp.WEIGHTS.update(old)
    return f


def course_only(boats):
    return {b["boat"]: 7 - b["boat"] for b in boats}


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


# ---- 各セクション -------------------------------------------------------------

def section1(races, skipped):
    print("■ 1. 使ったデータ")
    print(f"  使えたレース: {len(races)}（{DAYS}日分）")
    for k, v in skipped.items():
        print(f"  除外: {k} {v}")
    cnt = defaultdict(int)
    for r in races:
        for c in r["cls_raw"]:
            cnt[c] += 1
    total = sum(cnt.values())
    names = {1: "A1", 2: "A2", 3: "B1", 4: "B2"}
    share = " / ".join(f"{names.get(c, c)} {cnt[c] / total * 100:.0f}%" for c in sorted(cnt, key=str))
    print(f"  級別の割合: {share}")
    print("  （A1が全体の2割前後、B2が1割未満なら、数字と級の対応は合っています）")
    st_none = sum(1 for r in races for b in r["boats"] if b["ex_st"] is None)
    print(f"  展示STなし（F含む）: {st_none}艇 / {len(races) * 6}艇")
    w1 = sum(1 for r in races if r["order"][0] == 1)
    print(f"  1号艇が1着: {w1}レース（{w1 / len(races) * 100:.0f}%）")


def section2(races):
    print("\n■ 2. 今のロジックの成績（100円ずつ全点買い）")
    print("判定     レース 的中% 回収%")
    agg = defaultdict(lambda: [0, 0, 0, 0])
    for r in races:
        res = tp.pick(r["boats"])
        a = agg[res["label"]]
        a[0] += 1
        a[2] += res["n"] * 100
        if r["combo"] in [c for c, _ in res["combos"]]:
            a[1] += 1
            a[3] += r["pay"]
    total = [0, 0, 0, 0]
    for label in [t[2] for t in tp.TIERS]:
        a = agg.get(label)
        if not a:
            continue
        print(f"{label:<6} {a[0]:>6} {a[1] / a[0] * 100:>5.1f} {a[3] / a[2] * 100:>5.1f}")
        total = [x + y for x, y in zip(total, a)]
    if total[0]:
        print(f"全体   {total[0]:>6} {total[1] / total[0] * 100:>5.1f} {total[3] / total[2] * 100:>5.1f}")
    print("  （ボートレースの控除後の平均は回収率75%前後）")


def section3(races):
    print("\n■ 3. 点数の順位 → 実際の着順（%）")
    print("着順  1位  2位  3位  4位  5位  6位  ←点数の順位")
    tab = [[0] * 6 for _ in range(3)]
    for r in races:
        sc = tp.score_boats(r["boats"])
        ranked = sorted(sc, key=lambda b: (-sc[b], b))
        for p in range(3):
            tab[p][ranked.index(r["order"][p])] += 1
    for p in range(3):
        print(f"{p + 1}着 " + " ".join(f"{x / len(races) * 100:>3.0f}%" for x in tab[p]))
    print("  （でたらめなら各17%）")


def section4(races):
    print("\n■ 4. 艇番別の着順（%）")
    print("艇番  1着  2着  3着")
    for n in range(1, 7):
        row = [sum(1 for r in races if r["order"][p] == n) / len(races) * 100 for p in range(3)]
        print(f"{n}号艇 " + " ".join(f"{x:>3.0f}%" for x in row))


def evaluate(races, scorer):
    m1, m2, m3 = [], [], []
    for r in races:
        sc = scorer(r["boats"])
        m1.append(avg_ranks(sc)[r["order"][0]])
        if r["order"][0] == 1:
            rk = avg_ranks({b: s for b, s in sc.items() if b != 1})
            m2.append(rk[r["order"][1]])
            m3.append(rk[r["order"][2]])
    return mean(m1), mean(m2), mean(m3), len(m2)


def section5(races):
    print("\n■ 5. 項目ごとの予測力（順位の平均。小さいほど良い）")
    print("                1着艇 2着艇 3着艇")
    print("  でたらめ        3.50  3.00  3.00")
    now = dict(tp.WEIGHTS)
    rows = [("現行（全項目）", scorer_with(now))]
    names = {"cls": "級別のみ", "local": "当地のみ", "ex_time": "展示タイムのみ",
             "ex_st": "展示STのみ", "motor": "モーターのみ"}
    for key, label in names.items():
        rows.append((label, scorer_with({k: (1.0 if k == key else 0.0) for k in now})))
    rows.append(("艇番のみ（内が上）", course_only))
    n2 = 0
    for label, scorer in rows:
        a, b, c, n2 = evaluate(races, scorer)
        print(f"  {label:<12} {a:>5.2f} {b:>5.2f} {c:>5.2f}")
    print(f"  （2着艇・3着艇は、1号艇が1着の{n2}レースで、1号艇を除く5艇の中での順位）")


def main():
    races, skipped = load_races()
    if not races:
        print("使えるレースがありません。URLやネットワークを確認してください。")
        return 1
    section1(races, skipped)
    section2(races)
    section3(races)
    section4(races)
    section5(races)
    return 0


if __name__ == "__main__":
    sys.exit(main())
