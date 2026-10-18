# -*- coding: utf-8 -*-
"""trifecta_view.py
出走表（racelist.py）と直前情報（exhibition_scraper.py）を艇番でくっつけて、
trifecta_picker.py の pick() に渡し、三連単の候補を画面に出す。

同じフォルダに置くファイル:
    exhibition_scraper.py / racelist.py / trifecta_picker.py

app.py からの使い方（表示したい場所に2行足すだけ）:
    from trifecta_view import render_trifecta
    render_trifecta()
"""
import datetime as dt

import streamlit as st

from exhibition_scraper import list_live_venues, scrape_beforeinfo
from racelist import scrape_racelist
from trifecta_picker import pick

JST = dt.timezone(dt.timedelta(hours=9))


def build_boats(jcd, yyyymmdd, rno):
    """出走表と直前情報を艇番でくっつけて、pick() 用の boats を作る。

    戻り値: (boats または None, 注意メッセージまたは None)
    """
    entries = scrape_racelist(jcd, yyyymmdd, rno)
    if not entries:
        return None, "出走表が取れませんでした。"

    before = {
        r["course"]: r
        for r in scrape_beforeinfo(jcd, yyyymmdd, [rno], verbose=False)
    }

    boats = []
    for e in entries:
        b = before.get(e["course"], {})
        ex_f = bool(b.get("start_exhibition_f"))
        boats.append({
            "boat": e["course"],
            "cls": e.get("racer_class"),
            "local": e.get("local_win"),
            "motor": e.get("motor_2rate"),
            "ex_time": b.get("exhibition_time"),
            # 展示でFを切った艇のSTは数字が小さく出るので、採点では使わない（中立扱い）
            "ex_st": None if ex_f else b.get("start_exhibition_st"),
            "ex_f": ex_f,
        })

    note = None
    if not any(x["ex_time"] is not None for x in boats):
        note = "展示タイムがまだ出ていません。展示の項目は中立扱いで採点しています。"
    return boats, note


@st.cache_data(ttl=600)
def _venues(yyyymmdd):
    return list_live_venues(yyyymmdd)


def render_trifecta():
    st.subheader("三連単の候補（1号艇軸）")

    d = st.date_input("日付", dt.datetime.now(JST).date(), key="tri_date")
    ymd = d.strftime("%Y%m%d")

    venues = _venues(ymd)
    if not venues:
        st.warning("開催会場が見つかりませんでした。")
        return
    venue = st.selectbox(
        "会場", venues, format_func=lambda v: f"{v[1]}（{v[0]:02d}）", key="tri_venue"
    )
    rno = st.selectbox("レース", list(range(1, 13)), key="tri_rno")

    if st.button("候補を出す", key="tri_go"):
        boats, note = build_boats(venue[0], ymd, rno)
        st.session_state["tri_result"] = (boats, note)

    if "tri_result" not in st.session_state:
        return
    boats, note = st.session_state["tri_result"]
    if boats is None:
        st.error(note)
        return
    if note:
        st.warning(note)

    manual = st.selectbox("点数", ["自動", 4, 5, 6, 7, 8, 9, 10], key="tri_n")
    try:
        r = pick(boats, None if manual == "自動" else manual)
    except ValueError as e:
        st.error(str(e))
        return

    st.markdown(
        f"**判定：{r['label']}**（1号艇の点差 {r['gap']}）→ **{r['n']}点**"
    )
    st.dataframe(
        [{"組み合わせ": c, "点数": s} for c, s in r["combos"]],
        hide_index=True,
    )

    st.caption("各艇の点数")
    sc = r["scores"]
    st.dataframe(
        [
            {
                "艇": b["boat"],
                "点数": sc.get(b["boat"]),
                "クラス": b["cls"],
                "当地勝率": b["local"],
                "展示T": b["ex_time"],
                "展示ST": "F" if b["ex_f"] else b["ex_st"],
                "モーター2連率": b["motor"],
            }
            for b in boats
        ],
        hide_index=True,
    )
