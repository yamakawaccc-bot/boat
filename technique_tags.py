#!/usr/bin/env python3
"""
technique_tags.py
選手ごとの「決まり手タグ」（逃げ型・まくり型など）を作る集計スクリプト。
既存のスクレイパーとは別ファイル。点数や買い目には使わず、表示専用の参考情報。

データ元: Boatrace Open API（結果データ）
  https://boatraceopenapi.github.io/api/v1/YYYY/YYYYMMDD.json
  - 1日1ファイルに全24場分が入っている
  - 対応期間は2026-01-01以降
  - 決まり手: result.technique_number_source（元の文字列）
  - 1着の選手: result.racers のうち place_number == 1 の number（登録番号）

使い方:
  python technique_tags.py                 # 直近90日で集計して technique_data/technique_tags.json を作る
  python technique_tags.py --days 180      # 期間を伸ばす（取得済みの日は再取得しない）
  python technique_tags.py --show 4148     # 1人分の結果を表示
  python technique_tags.py --no-fetch      # 取得せず、取得済みデータだけで再集計

アプリ側から使う:
  from technique_tags import load_tags, get_tag, format_tag
  tags = load_tags()
  print(format_tag(get_tag(tags, 4148)))   # 例: "逃げ型" / "逃げ型（データ少なめ）" / ""
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---- 設定（ここを変えれば基準を調整できる） -------------------------------
API_URL = "https://boatraceopenapi.github.io/api/v1/{year}/{ymd}.json"
API_START = date(2026, 1, 1)          # APIの対応開始日
JST = timezone(timedelta(hours=9))

DEFAULT_DAYS = 90                      # 集計期間（まず3ヶ月、あとで伸ばす）
MIN_WINS_NORMAL = 10                   # 1着がこの回数以上 → タグを通常表示
MIN_WINS_WEAK = 5                      # 1着がこの回数以上 → 「データ少なめ」付きで表示
TOP_SHARE = 0.5                        # 最多の決まり手が1着全体のこの割合以上 → ◯◯型
REQUEST_INTERVAL = 1.0                 # リクエスト間隔（秒）。API側に負荷をかけない

DATA_DIR = Path(__file__).with_name("technique_data")
WINS_DIR = DATA_DIR / "wins"           # 日ごとの「1着×決まり手」キャッシュ
OUT_PATH = DATA_DIR / "technique_tags.json"
# --------------------------------------------------------------------------


def today_jst() -> date:
    return datetime.now(JST).date()


def fetch_day(d: date, retries: int = 3):
    """1日分のJSONを取得。404ならNone。失敗が続けばRuntimeError。"""
    url = API_URL.format(year=d.year, ymd=d.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "technique-tags/1.0"})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_err = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{d} の取得に失敗: {last_err}")


def _is_first(racer: dict) -> bool:
    p = racer.get("place_number")
    if isinstance(p, int):
        return p == 1
    src = str(racer.get("place_number_source") or "").strip()
    return src in ("1", "１")


def extract_wins(day_json: dict) -> list[list]:
    """1日分のJSONから [[選手登録番号, 決まり手], ...]（1着のみ）を取り出す。
    同着は1着が複数人になるので、全員を数える。
    結果なし・決まり手なしのレース（中止など）は飛ばす。"""
    wins: list[list] = []
    stadiums = (day_json.get("programs") or {}).get("stadiums") or {}
    for st in stadiums.values():
        for race in ((st or {}).get("races") or {}).values():
            result = (race or {}).get("result")
            if not result:
                continue
            tech = result.get("technique_number_source") or result.get("technique_number")
            if tech in (None, ""):
                continue
            tech = str(tech).strip()
            for racer in (result.get("racers") or {}).values():
                num = racer.get("number")
                if num is None or not _is_first(racer):
                    continue
                wins.append([int(num), tech])
    return wins


def update_cache(start: date, end: date) -> None:
    """start〜endの各日について、未取得の日だけ取得してキャッシュする。"""
    WINS_DIR.mkdir(parents=True, exist_ok=True)
    fetched = 0
    d = start
    while d <= end:
        path = WINS_DIR / f"{d:%Y%m%d}.json"
        if not path.exists():
            if fetched:
                time.sleep(REQUEST_INTERVAL)
            fetched += 1
            try:
                data = fetch_day(d)
            except RuntimeError as e:
                print(f"  {d}: {e}（スキップ。次回また試します）", file=sys.stderr)
                d += timedelta(days=1)
                continue
            if data is None:
                print(f"  {d}: データなし（404）")
            else:
                wins = extract_wins(data)
                path.write_text(
                    json.dumps({"date": d.isoformat(), "wins": wins}, ensure_ascii=False),
                    encoding="utf-8",
                )
                print(f"  {d}: 1着 {len(wins)}件を保存")
        d += timedelta(days=1)


def load_wins(start: date, end: date) -> list[list]:
    wins: list[list] = []
    d = start
    while d <= end:
        path = WINS_DIR / f"{d:%Y%m%d}.json"
        if path.exists():
            wins.extend(json.loads(path.read_text(encoding="utf-8")).get("wins", []))
        d += timedelta(days=1)
    return wins


def build_tags(wins: list[list]) -> dict:
    """選手ごとにタグを判定する。
    level: normal=通常表示 / weak=データ少なめ / none=タグなし（内訳だけ）"""
    per: dict[int, Counter] = defaultdict(Counter)
    for num, tech in wins:
        per[int(num)][tech] += 1

    tags: dict[str, dict] = {}
    for num, counter in per.items():
        n = sum(counter.values())
        top_tech, top_count = counter.most_common(1)[0]
        share = top_count / n
        if n < MIN_WINS_WEAK:
            level, tag = "none", None
        else:
            level = "normal" if n >= MIN_WINS_NORMAL else "weak"
            tag = f"{top_tech}型" if share >= TOP_SHARE else "バランス型"
        tags[str(num)] = {
            "tag": tag,
            "level": level,
            "wins": n,
            "top_share": round(share, 3),
            "breakdown": dict(counter.most_common()),
        }
    return tags


def save_tags(tags: dict, start: date, end: date) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "thresholds": {
            "min_wins_normal": MIN_WINS_NORMAL,
            "min_wins_weak": MIN_WINS_WEAK,
            "top_share": TOP_SHARE,
        },
        "racers": tags,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


# ---- アプリ側から使う関数 -------------------------------------------------
def load_tags(path: Path | None = None) -> dict:
    """technique_tags.json を読み、{登録番号(str): 情報} を返す。"""
    return json.loads(Path(path or OUT_PATH).read_text(encoding="utf-8")).get("racers", {})


def get_tag(tags: dict, racer_number) -> dict:
    return tags.get(str(racer_number), {"tag": None, "level": "none", "wins": 0, "breakdown": {}})


def format_tag(entry: dict) -> str:
    """カードに出す一言。タグなしなら空文字。"""
    if not entry.get("tag"):
        return ""
    return entry["tag"] + ("（データ少なめ）" if entry.get("level") == "weak" else "")
# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="選手ごとの決まり手タグを集計する")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help="集計期間（日数）")
    ap.add_argument("--no-fetch", action="store_true", help="取得せず、取得済みデータだけで再集計")
    ap.add_argument("--show", type=int, metavar="登録番号", help="1人分の結果を表示")
    args = ap.parse_args()

    end = today_jst() - timedelta(days=1)  # 当日は途中なので含めない
    start = max(API_START, end - timedelta(days=args.days - 1))
    print(f"集計期間: {start} 〜 {end}")

    if not args.no_fetch:
        update_cache(start, end)

    tags = build_tags(load_wins(start, end))
    save_tags(tags, start, end)
    print(f"{len(tags)}人分を {OUT_PATH} に保存しました")

    if args.show is not None:
        entry = get_tag(tags, args.show)
        print(args.show, format_tag(entry) or "(タグなし)", entry)


if __name__ == "__main__":
    main()
