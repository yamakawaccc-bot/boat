# -*- coding: utf-8 -*-
"""展示タイム スマホ用アプリ (Streamlit)

exhibition_scraper.py / racelist.py / scenario.py / venue_stats.py と同じフォルダに置いて起動する:
    streamlit run app.py
"""
import datetime as dt

import pandas as pd
import streamlit as st

import exhibition_scraper as ex
import racelist as rl
import scenario as sn
import venue_stats as vs

JST = dt.timezone(dt.timedelta(hours=9))
COLS = {
    "course": "枠", "racer_name": "選手", "racer_class": "級別",
    "exhibition_time": "展示", "順位": "順位",
    "tilt": "チルト", "weight_kg": "体重", "adjust_weight": "調整",
    "start_exhibition_st": "ST展示", "parts_exchange": "部品", "prev_st": "前走ST",
    "local_win": "当地勝率", "local_2rate": "当地2連率",
    "motor_2rate": "モーター2連率", "avg_st": "平均ST",
    "f_count": "F", "l_count": "L",
}
NUMFMT = {"exhibition_time": "{:.2f}", "順位": "{:.0f}", "tilt": "{:.1f}",
          "weight_kg": "{:.1f}", "adjust_weight": "{:.1f}", "prev_st": "{:.2f}",
          "local_win": "{:.2f}", "local_2rate": "{:.1f}", "motor_2rate": "{:.1f}",
          "avg_st": "{:.2f}", "f_count": "{:.0f}", "l_count": "{:.0f}"}


# --- helpers ---
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
# --- end helpers ---


st.set_page_config(page_title="展示タイム", page_icon="🚤", layout="centered")
st.title("🚤 展示タイム")


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
    if not info:
        st.caption("※ 出走表データ（級別・当地成績・モーターなど）は取得できませんでした。")
    show = build_table(df)
    best = df["exhibition_time"].min()
    mask = (df["exhibition_time"] == best).tolist()
    styled = show.style.apply(
        lambda col: ["background-color:#0a7d8c;color:#ffffff;font-weight:bold"
                     if m else "" for m in mask],
        subset=["展示"])
    st.dataframe(styled, hide_index=True)

    st.markdown("#### 展開の目安")
    try:
        for title, body in sn.build_scenarios(df, w.get("wind"), w.get("wave"),
                                            venue=vstats):
            st.markdown(f"**{title}**　{body}")
    except Exception:
        st.caption("展開の目安を作れませんでした。")
    st.caption("※ ルールによる簡易的な目安です。的中を保証するものではありません。")

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
