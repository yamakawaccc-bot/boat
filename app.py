# -*- coding: utf-8 -*-
"""競艇アプリ (Streamlit)  タブ：「展示タイム」「レース検索」

次のファイルと同じ場所（リポジトリのルート）に置いて起動する:
    exhibition_scraper.py / racelist.py / scenario.py / venue_stats.py
    trifecta_picker.py / race_table.py / race_filter.py / data/racer_stats.csv
    technique_tags.py / technique_data/technique_tags.json（決まり手タグ。なくても動く）
    streamlit run app.py
"""
import datetime as dt

import pandas as pd
import streamlit as st

import exhibition_scraper as ex
import racelist as rl
import scenario as sn
import venue_stats as vs
import trifecta_picker as tp
import race_filter as rf
import race_table as rt

try:  # 決まり手タグ（なくてもアプリは動く）
    import technique_tags as tt
except Exception:
    tt = None

JST = dt.timezone(dt.timedelta(hours=9))
COLS = {
    "course": "枠", "start_exhibition_course": "進入",
    "racer_name": "選手", "racer_class": "級別",
    "exhibition_time": "展示", "順位": "順位",
    "tilt": "チルト", "weight_kg": "体重", "adjust_weight": "調整",
    "start_exhibition_st": "ST展示", "parts_exchange": "部品", "prev_st": "前走ST",
    "local_win": "当地勝率", "local_2rate": "当地2連率",
    "motor_2rate": "モーター2連率", "avg_st": "平均ST",
    "f_count": "F", "l_count": "L",
}
NUMFMT = {"exhibition_time": "{:.2f}", "順位": "{:.0f}", "tilt": "{:.1f}",
          "start_exhibition_course": "{:.0f}",
          "weight_kg": "{:.1f}", "adjust_weight": "{:.1f}", "prev_st": "{:.2f}",
          "local_win": "{:.2f}", "local_2rate": "{:.1f}", "motor_2rate": "{:.1f}",
          "avg_st": "{:.2f}", "f_count": "{:.0f}", "l_count": "{:.0f}"}


# ======================================================================
# 展示タイム：補助関数
# ======================================================================
def cell(v, f):
    return "-" if pd.isna(v) else f.format(v)


def text(v):
    return "-" if pd.isna(v) or v == "" else str(v)


def st_text(rec):
    """スタート展示ST。フライング(F)なら先頭に F を付ける。"""
    v = rec.get("start_exhibition_st")
    if pd.isna(v):
        return "-"
    f = rec.get("start_exhibition_f")
    flag = bool(f) if pd.notna(f) else False
    return ("F" if flag else "") + f"{v:.2f}".lstrip("0")


def approach_text(df):
    """展示時点の進入（スタート展示の並び順）を文字にする。

    例：展示の進入　1-3-2-4-5-6（枠なりではない）
    取れていないときは空文字を返す。数字は枠番（号艇）を、内側のコースから並べたもの。
    """
    if "start_exhibition_course" not in df.columns:
        return ""
    sub = df.dropna(subset=["start_exhibition_course"])
    if sub.empty:
        return ""
    order = [int(b) for b in sub.sort_values("start_exhibition_course")["course"]]
    label = "枠なり" if order == sorted(order) else "枠なりではない"
    return f"展示の進入　{'-'.join(str(b) for b in order)}（{label}）"


def build_table(df):
    """表示用に、すべて文字列にした表を作る（空欄は「-」）。"""
    out = {}
    for key, label in COLS.items():
        if key == "start_exhibition_st":
            out[label] = [st_text(r) for r in df.to_dict("records")]
        elif key in NUMFMT:
            if key in df.columns:
                out[label] = [cell(v, NUMFMT[key]) for v in df[key]]
        elif key in df.columns:
            out[label] = [text(v) for v in df[key]]
    return pd.DataFrame(out, index=df.index)


def build_boats(df):
    """表示中のデータ（展示＋出走表）から、三連単の採点用データを作る。"""
    def g(rec, k):
        v = rec.get(k)
        return None if pd.isna(v) else v

    boats = []
    for rec in df.to_dict("records"):
        f = rec.get("start_exhibition_f")
        ex_f = bool(f) if pd.notna(f) else False
        boats.append({
            "boat": int(rec["course"]),
            "cls": g(rec, "racer_class"),
            "local": g(rec, "local_win"),
            "motor": g(rec, "motor_2rate"),
            "ex_time": g(rec, "exhibition_time"),
            # 展示でFを切った艇のSTは数字が小さく出るので、採点では使わない（中立扱い）
            "ex_st": None if ex_f else g(rec, "start_exhibition_st"),
        })
    return boats


# ======================================================================
# 決まり手タグ（参考表示。点数や買い目には使わない）
# ======================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_tags():
    if tt is None:
        return {}
    try:
        return tt.load_tags()
    except Exception:
        return {}


def tag_text(toban):
    """選手登録番号から「逃げ型」などの一言を返す。取れなければ「-」。"""
    if tt is None or pd.isna(toban):
        return "-"
    return tt.format_tag(tt.get_tag(get_tags(), int(toban))) or "-"


def breakdown_text(toban):
    """決まり手の内訳。例：逃げ12 / まくり3（1着15回）"""
    if tt is None or pd.isna(toban):
        return "データなし"
    e = tt.get_tag(get_tags(), int(toban))
    if not e.get("wins"):
        return "データなし"
    parts = " / ".join(f"{k}{c}" for k, c in e["breakdown"].items())
    return f"{parts}（1着{e['wins']}回）"


# ======================================================================
# 展示タイム：データ取得（キャッシュ）
# ======================================================================
@st.cache_data(ttl=600, show_spinner=False)
def get_venues(ymd: str):
    return ex.list_live_venues(ymd)


@st.cache_data(ttl=120, show_spinner=False)
def get_race(jcd: int, ymd: str, rno: int):
    return ex.scrape_beforeinfo(jcd, ymd, [rno], verbose=False)


@st.cache_data(ttl=3600, show_spinner=False)
def get_racelist(jcd: int, ymd: str, rno: int):
    try:
        return rl.scrape_racelist(jcd, ymd, rno)
    except Exception:
        return []


@st.cache_data(ttl=86400, show_spinner=False)
def get_venue_stats(jcd: int):
    try:
        return vs.fetch_venue_stats(jcd)
    except Exception:
        return None


# ======================================================================
# 検索：補助関数・データ取得
# ======================================================================
@st.cache_data(ttl=300, show_spinner="出走表と成績を読み込み中…")
def get_table(min_starts: int) -> pd.DataFrame:
    # 出走表は5分キャッシュ(アクセスを増やさないため)
    return rt.build_table(rt.fetch_programs(), rt.load_stats(min_starts))


def pct(v: int) -> str:
    return f"{v}%"


def num(v) -> str:
    return "—" if pd.isna(v) else f"{v:.1f}"


def starts(v) -> str:
    return "" if pd.isna(v) else f"（{int(v)}走）"


def boat_no(v) -> str:
    return "—" if pd.isna(v) else f"{int(v)}号艇"


def render_card(r: pd.Series, kind: str) -> None:
    head = f"**{r['会場']} {int(r['R'])}R**　🕒 {r['締切'] or '—'}"
    line1 = f"1号艇 {r['1号艇']}　逃げ率 **{num(r['1逃げ率'])}%**{starts(r['1出走'])}"
    if kind == "gachi":
        line2 = f"2号艇 {r['2号艇']}　逃し率 **{num(r['2逃し率'])}%**{starts(r['2出走'])}"
    else:
        line2 = f"{boat_no(r['攻め艇'])} {r['攻め艇名']}　差し・捲り率 **{num(r['攻め最大率'])}%**"
    with st.container(border=True):
        st.markdown(f"{head}  \n{line1}  \n{line2}")  # 行末の空白2つ＝改行


def show_results(df: pd.DataFrame, kind: str, cols: list, as_table: bool) -> None:
    st.subheader(f"{len(df)}件")
    if df.empty:
        st.info("該当するレースはありません。条件をゆるめてみてください。")
        return
    df = df.sort_values("締切")
    if as_table:
        st.dataframe(df[cols], hide_index=True, use_container_width=True)
    else:
        for _, r in df.iterrows():
            render_card(r, kind)


# ======================================================================
# タブ1：展示タイム
# ======================================================================
def render_exhibition():
    d = st.date_input("日付", value=dt.datetime.now(JST).date(), key="ex_date")
    ymd = d.strftime("%Y%m%d")

    venues = get_venues(ymd)
    if not venues:
        st.warning("開催中の会場が見つかりませんでした。")
        return
    names = dict(venues)

    jcd = st.selectbox("会場", list(names), format_func=lambda j: names[j],
                       key="ex_venue")
    rno = st.radio("レース", list(range(1, 13)), horizontal=True,
                   format_func=lambda r: f"{r}R", key="ex_rno")

    if st.button("最新に更新", key="ex_refresh"):
        st.cache_data.clear()
        st.rerun()

    with st.spinner("取得中..."):
        rows = get_race(jcd, ymd, rno)
        info = get_racelist(jcd, ymd, rno)
        vstats = get_venue_stats(jcd)

    if not rows:
        st.info("まだ公開されていません（または中止・取得失敗）。")
    else:
        df = pd.DataFrame(rows)
        if info:
            df = df.merge(pd.DataFrame(info).drop(columns=["date", "stadium", "race"]),
                          on="course", how="left")
        df["順位"] = df["exhibition_time"].rank(method="min").astype("Int64")
        w = rows[0]
        st.caption(f"気温 {w.get('air_temp')}℃ / 風 {w.get('wind')}m / "
                   f"水温 {w.get('water_temp')}℃ / 波 {w.get('wave')}cm")
        approach = approach_text(df)
        if approach:
            st.caption(approach)
        table_view = build_table(df)
        # 選手の隣に決まり手タグを入れる（参考表示。点数や買い目には使わない）
        if "toban" in df.columns:
            cols_now = list(table_view.columns)
            pos = cols_now.index("選手") + 1 if "選手" in cols_now else min(2, len(cols_now))
            table_view.insert(pos, "決まり手", [tag_text(v) for v in df["toban"]])
        best = df["exhibition_time"].min()
        mask = (df["exhibition_time"] == best).tolist()
        styled = table_view.style.apply(
            lambda col: ["background-color:#0a7d8c;color:#ffffff;font-weight:bold"
                         if m else "" for m in mask],
            subset=["展示"])
        st.dataframe(styled, hide_index=True)

        if "toban" in df.columns and get_tags():
            with st.expander("決まり手の内訳（直近の1着）"):
                for rec in df.to_dict("records"):
                    st.markdown(f"**{int(rec['course'])}号艇 {text(rec.get('racer_name'))}**"
                                f"　{breakdown_text(rec.get('toban'))}")
                st.caption("※ 直近の1着だけを数えた参考情報です。1着が少ない選手はあてになりません。")

        st.markdown("#### 展開の目安")
        try:
            for title, body in sn.build_scenarios(df, w.get("wind"), w.get("wave"),
                                                venue=vstats):
                st.markdown(f"**{title}**　{body}")
        except Exception:
            st.caption("展開の目安を作れませんでした。")
        st.caption("※ ルールによる簡易的な目安です。的中を保証するものではありません。")

        st.markdown("#### 三連単の候補（1号艇軸）")
        try:
            pk_n = st.selectbox("点数", ["自動", 4, 5, 6, 7, 8, 9, 10], key="tri_n")
            pk = tp.pick(build_boats(df), None if pk_n == "自動" else pk_n)
            st.markdown(f"**判定：{pk['label']}**（1号艇の点差 {pk['gap']}）"
                        f"→ **{pk['n']}点**")
            st.dataframe([{"組み合わせ": c, "点数": s} for c, s in pk["combos"]],
                         hide_index=True)
            st.caption("各艇の点数　" + " / ".join(
                f"{b}号艇 {s}" for b, s in sorted(pk["scores"].items())))
            if not info:
                st.caption("※ 出走表が取れなかったため、級別・当地勝率・モーターは中立扱いです。")
            st.caption("※ 採点ルールによる候補です。最後はオッズと照らして判断してください。")
        except Exception:
            st.caption("三連単の候補を作れませんでした。")

    with st.expander("この会場の全レースをCSVで保存"):
        st.caption("12R分を順に取得します（1分ほどかかります）。")
        if st.button("12R分を取得", key="ex_csv_go"):
            with st.spinner("取得中..."):
                allrows = ex.scrape_beforeinfo(jcd, ymd, range(1, 13), verbose=False)
            for r in allrows:
                r["stadium_name"] = names[jcd]
            st.session_state["csv"] = (pd.DataFrame(allrows)
                                       .to_csv(index=False).encode("utf-8-sig"))
            st.session_state["csv_name"] = f"exhibition_{ymd}_{jcd:02d}.csv"
        if "csv" in st.session_state:
            st.download_button("CSVをダウンロード", st.session_state["csv"],
                               file_name=st.session_state["csv_name"], mime="text/csv")


# ======================================================================
# タブ2：レース検索（ガチガチ / 穴）
# ======================================================================
def render_search():
    st.caption("今日のレースを、逃げ率・逃し率・差し捲り率の条件で探します")

    if not rt.STATS_PATH.exists():
        st.error(f"{rt.STATS_PATH} がありません。GitHub Actionsの build-stats を実行してください。")
        return

    with st.expander("設定"):
        min_starts = st.slider("率に使う最低出走数", 5, 50, 10, key="sr_min",
                               help="これより出走数が少ない選手の率は使いません")
        upcoming = st.checkbox("締切前のレースだけ", value=True, key="sr_up")
        as_table = st.checkbox("表で表示する（カードをやめる）", value=False, key="sr_tbl")

    try:
        table = get_table(min_starts)
    except Exception as e:  # 出走表の取得失敗など
        st.error(f"出走表を取得できませんでした: {e}")
        return

    if upcoming:
        table = rf.only_upcoming(table)
    st.caption(f"対象レース: {len(table)}件")

    tab_gachi, tab_ana = st.tabs(["ガチガチ", "穴"])

    with tab_gachi:
        st.write("1号艇の逃げ率が高く、2号艇の逃し率も高いレース")
        nige_min = st.select_slider("1号艇 逃げ率（以上）", options=[50, 55, 60, 65, 70, 75],
                                    value=70, format_func=pct, key="sr_nige_min")
        nigashi_min = st.select_slider("2号艇 逃し率（以上）", options=[35, 40, 45, 50, 55, 60],
                                       value=50, format_func=pct, key="sr_nigashi_min")
        show_results(rf.search_gachigachi(table, nige_min, nigashi_min), "gachi",
                     ["会場", "R", "締切", "1号艇", "1逃げ率", "2号艇", "2逃し率"], as_table)

    with tab_ana:
        st.write("1号艇の逃げ率が低く、2〜6号艇に差し・捲りの強い選手がいるレース")
        nige_max = st.select_slider("1号艇 逃げ率（以下）", options=[20, 30, 40, 45, 50, 55, 60],
                                    value=50, format_func=pct, key="sr_nige_max")
        attack_min = st.select_slider("2〜6号艇 差し・捲り率（以上）",
                                      options=[10, 15, 20, 25, 30, 35, 40],
                                      value=20, format_func=pct, key="sr_attack_min")
        show_results(rf.search_ana(table, nige_max, attack_min), "ana",
                     ["会場", "R", "締切", "1号艇", "1逃げ率", "攻め艇", "攻め艇名", "攻め最大率"],
                     as_table)
        st.caption("差し・捲り率 = 差し・捲り・捲り差しで1着になった割合の合計。"
                   "「攻め艇」はその率が一番高い号艇です。")


# ======================================================================
# 画面
# ======================================================================
st.set_page_config(page_title="競艇", page_icon="🚤", layout="centered")
st.title("🚤 競艇")

tab_ex, tab_search = st.tabs(["展示タイム", "レース検索"])
with tab_ex:
    render_exhibition()
with tab_search:
    render_search()
