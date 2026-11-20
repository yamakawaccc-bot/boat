#!/usr/bin/env python3
"""
schema_check.py
Boatrace Open API（結果データ）に「風向・風速」などが入っているかを確認するだけのスクリプト。
データは保存しない。画面（Actionsのログ）に出すだけ。

確認すること:
  1. 1レース分のデータにどんな項目があるか
  2. 風・波・天気に関係しそうな項目の場所と値
  3. 2026-01-01 のデータが取れるか（APIの対応開始日）
"""
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

API_URL = "https://boatraceopenapi.github.io/api/v1/{year}/{ymd}.json"
JST = timezone(timedelta(hours=9))
KEYWORDS = ("wind", "wave", "weather", "temperature", "air", "water")


def fetch_day(d):
    url = API_URL.format(year=d.year, ymd=d.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "schema-check/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        print(f"  {d}: HTTP {e.code}")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  {d}: 取得失敗 {e}")
        return None


def show(obj, indent=0, depth=0):
    """構造を表示。番号キーの辞書やリストは最初の1件だけ見せる。"""
    pad = "  " * indent
    if depth > 8:
        return
    if isinstance(obj, dict):
        keys = list(obj.keys())
        if keys and all(str(k).isdigit() for k in keys):
            print(f"{pad}(番号キー {len(keys)}件。最初の1件 {keys[0]} だけ表示)")
            show(obj[keys[0]], indent, depth + 1)
            return
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}:")
                show(v, indent + 1, depth + 1)
            else:
                print(f"{pad}{k} = {repr(v)[:60]}")
    elif isinstance(obj, list):
        print(f"{pad}(リスト {len(obj)}件。最初の1件だけ表示)")
        if obj:
            show(obj[0], indent, depth + 1)


def find_keys(obj, path="", out=None):
    """風・波などに関係しそうなキーの場所と値を集める（最初に見つかった数件）。"""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}/{k}"
            if any(w in str(k).lower() for w in KEYWORDS):
                out.append((p, v if not isinstance(v, (dict, list)) else "(中身あり)"))
            find_keys(v, p, out)
    elif isinstance(obj, list):
        for v in obj[:1]:
            find_keys(v, path + "[0]", out)
    return out


def first_race(day_json):
    stadiums = (day_json.get("programs") or {}).get("stadiums") or {}
    for sk, st in stadiums.items():
        for rk, race in ((st or {}).get("races") or {}).items():
            if (race or {}).get("result"):
                return sk, rk, race, st
    return None


def main():
    yesterday = datetime.now(JST).date() - timedelta(days=2)
    print(f"=== 1) {yesterday} のデータの構造 ===")
    data = fetch_day(yesterday)
    if data:
        print("最上位のキー:", list(data.keys()))
        found = first_race(data)
        if found:
            sk, rk, race, st = found
            print(f"\n[1レース分の構造] 会場キー={sk} / レースキー={rk}")
            show(race)
            print("\n[会場（レースの外側）に付いている項目]")
            show({k: v for k, v in st.items() if k != "races"})
        else:
            print("結果ありのレースが見つかりませんでした")

        print("\n=== 2) 風・波・天気に関係しそうな項目 ===")
        hits = find_keys(data)
        seen = set()
        for p, v in hits:
            key = p.split("/")[-1]
            if key in seen:
                continue
            seen.add(key)
            print(f"{p} = {v}")
        if not hits:
            print("見つかりませんでした")

    print("\n=== 3) 対応開始日 2026-01-01 のデータ ===")
    first = fetch_day(date(2026, 1, 1))
    print("取れた" if first else "取れなかった")


if __name__ == "__main__":
    main()
