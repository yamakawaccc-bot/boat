"""check_join_data.py
Boatrace Open API の「出走表(programs)」「直前情報(previews)」「結果(results)」を
過去30日分取得して、(場・R)でつなげられるかを確認する。標準ライブラリだけで動く。

出力
  ■1 日ごとのレース数と、3つ揃ったレース数
  ■2 出走表と結果の全項目（次のステップで点数の計算に使う項目名の確認用）

使い方
    python check_join_data.py
GitHub Actions なら check_join_data.yml を手動実行（workflow_dispatch）。
"""
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

BASE = "https://boatraceopenapi.github.io/{kind}/v2/{y}/{ymd}.json"
KINDS = ["programs", "previews", "results"]
DAYS = 30  # 何日前まで確認するか（うまくいけば90などに増やす）


def fetch(kind, d):
    """その日のJSONを返す。無ければ None。"""
    url = BASE.format(kind=kind, y=d.year, ymd=d.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "check-join-data"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  取得エラー {kind} {d}: HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  取得エラー {kind} {d}: {e}")
        return None


def walk(node, path, out):
    """JSONの全項目を {項目のパス: [値, ...]} に集める。"""
    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, f"{path}.{k}" if path else k, out)
    elif isinstance(node, list):
        for v in node:
            walk(v, path + "[]", out)
    else:
        out[path].append(node)


def filled(v):
    return v is not None and v != ""


def race_list(data):
    """JSONの中からレースのリストを取り出す。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def boats_of(race):
    """レースの中から6艇のリストを取り出す。"""
    for v in race.values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "racer_boat_number" in v[0]:
            return v
    return []


def keyed_races(data):
    """{(場, R): レース} にする。"""
    keyed = {}
    for r in race_list(data):
        k = (r.get("race_stadium_number"), r.get("race_number"))
        if None not in k:
            keyed[k] = r
    return keyed


def show(n):
    return "-" if n is None else str(n)


def main():
    today = date.today()
    schema = {}  # kind -> (日付, 全項目)
    tot = defaultdict(int)

    print("■ 1. 日ごとのレース数")
    print("日付  出走表 直前 結果 3揃い 展示6艇")
    for off in range(1, DAYS + 1):
        d = today - timedelta(days=off)
        races = {}
        for kind in KINDS:
            data = fetch(kind, d)
            time.sleep(0.2)
            if data is None:
                races[kind] = None
                continue
            races[kind] = keyed_races(data)
            if kind in ("programs", "results") and kind not in schema:
                out = defaultdict(list)
                walk(data, "", out)
                schema[kind] = (d, out)

        if all(races[k] is not None for k in KINDS):
            common = set(races["programs"]) & set(races["previews"]) & set(races["results"])
        else:
            common = set()

        n6 = 0
        for k in common:
            boats = boats_of(races["previews"][k])
            if len(boats) == 6 and all(filled(b.get("racer_exhibition_time")) for b in boats):
                n6 += 1

        counts = [None if races[k] is None else len(races[k]) for k in KINDS]
        print(f"{d:%m/%d} {show(counts[0]):>5} {show(counts[1]):>4} {show(counts[2]):>4} {len(common):>4} {n6:>5}")
        for name, c in zip(KINDS, counts):
            tot[name] += c or 0
        tot["common"] += len(common)
        tot["n6"] += n6

    print(f"合計 {tot['programs']:>5} {tot['previews']:>4} {tot['results']:>4} {tot['common']:>4} {tot['n6']:>5}")

    for num, kind, title in ((2, "programs", "出走表"), (3, "results", "結果")):
        print(f"\n■ {num}. {title}の全項目（入っている数／全体、例）")
        if kind not in schema:
            print("  取得できませんでした")
            continue
        d, out = schema[kind]
        print(f"  （{d}の分）")
        for p in sorted(out):
            vals = out[p]
            f = sum(1 for v in vals if filled(v))
            ex = next((v for v in vals if filled(v)), "")
            print(f"  {p}: {f}/{len(vals)} 例:{ex}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
