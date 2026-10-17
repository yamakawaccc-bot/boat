"""
Streamlit の検索画面（ガチガチレース / 穴レース）— 1レース1枚のカード表示

置き場所: race_table.py, race_filter.py, data/racer_stats.csv と同じリポジトリ(ルート)
起動:     streamlit run search_app.py
必要:     requirements.txt に streamlit / pandas / requests
"""
import pandas as pd
import streamlit as st

import race_filter as rf
import race_table as rt

st.set_page_config(page_title="レース検索", page_icon="🚤", layout="centered")
st.title("🚤 レース検索")
st.caption("今日のレースを、逃げ率・逃し率・差し捲り率の条件で探します")


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


def show(df: pd.DataFrame, kind: str, cols: list) -> None:
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


if not rt.STATS_PATH.exists():
    st.error(f"{rt.STATS_PATH} がありません。GitHub Actionsの build-stats を実行してください。")
    st.stop()

with st.expander("設定"):
    min_starts = st.slider("率に使う最低出走数", 5, 50, 10, help="これより出走数が少ない選手の率は使いません")
    upcoming = st.checkbox("締切前のレースだけ", value=True)
    as_table = st.checkbox("表で表示する（カードをやめる）", value=False)

try:
    table = get_table(min_starts)
except Exception as e:  # 出走表の取得失敗など
    st.error(f"出走表を取得できませんでした: {e}")
    st.stop()

if upcoming:
    table = rf.only_upcoming(table)
st.caption(f"対象レース: {len(table)}件")

tab_gachi, tab_ana = st.tabs(["ガチガチ", "穴"])

with tab_gachi:
    st.write("1号艇の逃げ率が高く、2号艇の逃し率も高いレース")
    nige_min = st.select_slider("1号艇 逃げ率（以上）", options=[50, 55, 60, 65, 70, 75], value=70, format_func=pct)
    nigashi_min = st.select_slider("2号艇 逃し率（以上）", options=[35, 40, 45, 50, 55, 60], value=50, format_func=pct)
    show(rf.search_gachigachi(table, nige_min, nigashi_min), "gachi",
         ["会場", "R", "締切", "1号艇", "1逃げ率", "2号艇", "2逃し率"])

with tab_ana:
    st.write("1号艇の逃げ率が低く、2〜6号艇に差し・捲りの強い選手がいるレース")
    nige_max = st.select_slider("1号艇 逃げ率（以下）", options=[20, 30, 40, 45, 50, 55, 60], value=50, format_func=pct)
    attack_min = st.select_slider("2〜6号艇 差し・捲り率（以上）", options=[10, 15, 20, 25, 30, 35, 40], value=20, format_func=pct)
    show(rf.search_ana(table, nige_max, attack_min), "ana",
         ["会場", "R", "締切", "1号艇", "1逃げ率", "攻め艇", "攻め艇名", "攻め最大率"])
    st.caption("差し・捲り率 = 差し・捲り・捲り差しで1着になった割合の合計。「攻め艇」はその率が一番高い号艇です。")
