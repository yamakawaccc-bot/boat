"""check_preview_data.py
Boatrace Open API の直前情報（previews）の過去データに、
展示タイム・展示STが入っているかを確認する。標準ライブラリだけで動く。

やること
1. 1日前〜365日前の数日分を取得して、データが存在するか確認
2. JSONの全項目を調べて、展示タイム・STらしい項目を探す
   （項目名が分からなくても、値の範囲で推定する）
3. 日ごとに「入っている数／全艇数」を表示

使い方
    python check_preview_data.py
GitHub Actions なら check_preview_data.yml を手動実行（workflow_dispatch）。
"""
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

BASE = "https://boatraceopenapi.github.io/previews/v2/{y}/{ymd}.json"

# 何日前のデータを確認するか（増やすと遠い過去まで確認できる）
OFFSETS = [1, 7, 14, 30, 60, 90, 180, 365]

CANDIDATE = re.compile(r"exhib|tenji|timing|time|(^|_)st($|_)", re.I)
TIMING_KEY = re.compile(r"timing|(^|_)st($|_)", re.I)


def fetch(d):
    """その日のJSONを返す。無ければ None。"""
    url = BASE.format(y=d.year, ymd=d.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "check-preview-data"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  取得エラー {d}: HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  取得エラー {d}: {e}")
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


def to_num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def leaf(path):
    return path.split(".")[-1].replace("[]", "")


def count(out, path):
    vals = out.get(path, [])
    return sum(1 for v in vals if filled(v)), len(vals)


def judge(days, paths):
    """値の範囲から、展示タイム・STらしい項目を推定する。"""
    tm, st = [], []
    for p in sorted(paths):
        nums = []
        for out in days.values():
            for v in out.get(p, []):
                x = to_num(v) if filled(v) else None
                if x is not None:
                    nums.append(x)
        if len(nums) < 5:
            continue
        if sum(6.0 <= x <= 7.5 for x in nums) / len(nums) >= 0.8:
            tm.append(p)
        if TIMING_KEY.search(leaf(p)) and sum(-1.0 <= x <= 1.0 for x in nums) / len(nums) >= 0.8:
            st.append(p)
    return tm, st


def main():
    today = date.today()
    days = {}

    print("■ 1. 取得できた日（直前情報）")
    for off in OFFSETS:
        d = today - timedelta(days=off)
        data = fetch(d)
        if data is None:
            print(f"  {d}（{off}日前）: なし")
            continue
        out = defaultdict(list)
        walk(data, "", out)
        days[d] = out
        print(f"  {d}（{off}日前）: あり（項目{len(out)}種）")

    if not days:
        print("\n取得できた日がありません。URLかネットワークを確認してください。")
        return 1

    latest = max(days)
    all_paths = set()
    for out in days.values():
        all_paths.update(out.keys())

    print("\n■ 2. 展示タイム・STの候補")
    tm, st = judge(days, all_paths)
    print("  展示タイムらしい項目:", ", ".join(tm) if tm else "見つかりませんでした")
    print("  展示STらしい項目:", ", ".join(st) if st else "見つかりませんでした")

    print("\n■ 3. 候補項目の入り具合（入っている数／全艇数）")
    cand = sorted(p for p in all_paths if CANDIDATE.search(leaf(p)))
    cand = sorted(set(cand) | set(tm) | set(st))
    if not cand:
        print("  名前が候補に合う項目がありません。下の全項目を確認してください。")
    for p in cand:
        mark = "★" if p in tm or p in st else " "
        print(f"{mark} {p}")
        for d in sorted(days):
            f, n = count(days[d], p)
            if n:
                print(f"     {d}: {f}/{n}")
        sample = [v for v in days[latest].get(p, []) if filled(v)][:3]
        if sample:
            print(f"     例: {sample}")

    print(f"\n■ 4. 全項目一覧（{latest}の分。入っている数／全体）")
    for p in sorted(days[latest]):
        f, n = count(days[latest], p)
        print(f"  {p}: {f}/{n}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
