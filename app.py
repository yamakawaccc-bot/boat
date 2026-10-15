# -*- coding: utf-8 -*-
"""展示タイム スマホ用アプリ (Streamlit)

exhibition_scraper.py と同じフォルダに置いて起動する:
    streamlit run app.py
"""
import datetime as dt

import pandas as pd
import streamlit as st

import exhibition_scraper as ex

JST = dt.timezone(dt.timedelta(hours=9))
COLS = {
    "course": "枠", "racer_name": "選手", "exhibition_time": "展示", "順位": "順位",
    "tilt": "チルト", "weight_kg": "体重", "adjust_weight": "調整",
    "start_exhibition_st": "ST展示", "parts_exchange": "部品", "prev_st": "前走ST",
}

st.set_page_config(page_title="展示タイム", page_icon="🚤", layout="centered")
st.title("🚤 展示タイム")


@st.cache_data(ttl=600, show_spinner=False)
def get_venues(ymd: str):
    return ex.list_live_venues(ymd)


@st.cache_data(ttl=120, show_spinner=False)
def get_race(jcd: int, ymd: str, rno: int):
    return ex.scrape_beforeinfo(jcd, ymd, [rno], verbose=False)


d = st.date_input("日付", value=dt.datetime.now(JST).date())
ymd = d.strftime("%Y%m%d")

venues = get_venues(ymd)
if not venues:
    st.warning("開催中の会場が見つかりませんでした。")
    st.stop()
names = dict(venues)

jcd = st.selectbox("会場", list(names), format_func=lambda j: names[j])
rno = st.radio("レース", list(range(1, 13)), horizontal=True,
               format_func=lambda r: f"{r}R")

if st.button("最新に更新"):
    st.cache_data.clear()
    st.rerun()

with st.spinner("取得中..."):
    rows = get_race(jcd, ymd, rno)

if not rows:
    st.info("まだ公開されていません（または中止・取得失敗）。")
else:
    df = pd.DataFrame(rows)
    df["順位"] = df["exhibition_time"].rank(method="min").astype("Int64")
    w = rows[0]
    st.caption(f"気温 {w.get('air_temp')}℃ / 風 {w.get('wind')}m / "
               f"水温 {w.get('water_temp')}℃ / 波 {w.get('wave')}cm")
    show = df[[c for c in COLS if c in df.columns]].rename(columns=COLS)
    st.dataframe(show.style.highlight_min(subset=["展示"], color="#cdeff2"),
                 hide_index=True)

with st.expander("この会場の全レースをCSVで保存"):
    st.caption("12R分を順に取得します（1分ほどかかります）。")
    if st.button("12R分を取得"):
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
