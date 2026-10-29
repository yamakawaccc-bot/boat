"""check_st_treatment.py
展示STのマイナス（Fらしき値）の扱い方を比べる。
trifecta_picker.py / analyze_picker.py / tune_picker.py と同じ場所に置く。
"""
import sys

import trifecta_picker as tp
import tune_picker as tn


def variant_races(races, transform):
    out = []
    for r in races:
        vals = [transform(s) for s in r["st_raw"]]
        feat = dict(r["feat"])
        feat["ex_st"] = tp._norm(vals, False)
        out.append({**r, "feat": feat})
    return out


def as_none(s):
    return s if (s is not None and s >= 0) else None


def as_is(s):
    return s


def as_abs(s):
    return abs(s) if s is not None else None


def main():
    races, skipped = tn.load_races()
    if not races:
        print("使えるレースがありません。")
        return 1
    print(f"■ 使ったレース: {len(races)}（{tn.DAYS}日分、うち新しい{tn.TEST_DAYS}日を検証に使用）")

    base = {**tp.WEIGHTS, "course": 4.0}
    st_w2 = {**base, "ex_st": base["ex_st"] * 2}
    no_st = {**base, "ex_st": 0.0}

    sets = {
        "A": variant_races(races, as_none),
        "B": variant_races(races, as_is),
        "C": variant_races(races, as_abs),
    }
    rows = [
        ("A", sets["A"], base), ("B", sets["B"], base), ("C", sets["C"], base),
        ("D", sets["A"], no_st),
        ("A2", sets["A"], st_w2), ("B2", sets["B"], st_w2), ("C2", sets["C"], st_w2),
    ]

    print("\n■ 展示STの扱いを変えて比べる")
    print("  A=現行（マイナスはなし） B=マイナスのまま")
    print("  C=絶対値（F.02→0.02） D=展示STを使わない")
    print("  A2/B2/C2=展示STの重みを2倍")
    print("\n  3艇の順位の合計（小さいほど良い）")
    print("      全期間 新10日 上位3艇的中数(新10日)")
    for name, rs, w in rows:
        test = [r for r in rs if r["off"] <= tn.TEST_DAYS]
        allo = tn.objective(rs, w)
        newo = tn.objective(test, w)
        ov = tn.evaluate(test, w)[3]
        print(f"  {name:<3} {allo:>6.3f} {newo:>6.3f}   {ov:>5.3f}")
    print("  （でたらめなら合計10.50、上位3艇の的中数は1.50）")
    print("  差が0.02以下なら、実質同じと見てください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
