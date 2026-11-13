"""Edger — a mobile-first SEC EDGAR company dashboard built on edgartools.

Views (kept in the URL so a home-screen shortcut reopens the same place):
  ?t=AAPL            company view
  ?v=watch           watchlist & comparison
"""
from __future__ import annotations

import streamlit as st

from edger import data, view_company, view_compare, watchlist
from edger.ui import inject_css, resolve_identity

st.set_page_config(page_title="Edger", page_icon="📊", layout="centered",
                   initial_sidebar_state="collapsed")
inject_css()

VIEWS = {"company": ":material/search: 종목", "watch": ":material/star: 관심·비교"}
QUICK = ["AAPL", "NVDA", "MSFT", "TSM", "KO", "JPM", "O"]


def set_ticker(value: str) -> None:
    value = (value or "").strip().upper()
    if not value:
        return
    st.query_params["t"] = value
    st.query_params["v"] = "company"
    recent = [t for t in st.session_state.get("recent", []) if t != value]
    st.session_state["recent"] = [value, *recent][:6]


def on_ticker_input() -> None:
    set_ticker(st.session_state.get("ticker_input", ""))


def on_recent_pick() -> None:
    pick = st.session_state.get("recent_pick")
    if pick:
        st.session_state["ticker_input"] = pick
        set_ticker(pick)
    st.session_state["recent_pick"] = None


def on_quick_pick() -> None:
    pick = st.session_state.get("quick_pick")
    if pick:
        st.session_state["ticker_input"] = pick
        set_ticker(pick)
    st.session_state["quick_pick"] = None


def welcome() -> None:
    """Empty state: say what the app does and offer one-tap starting points."""
    st.markdown(
        '<div class="ed-welcome"><div class="ed-wt">미국 상장사를 SEC 공시로 한눈에</div>'
        '<ul><li><b>실적·재무</b> 연간·TTM·분기, 재무 안정성, 전체 재무제표</li>'
        '<li><b>사업</b> 사업부문·제품·지역별 매출 비중</li>'
        '<li><b>가치·배당</b> PER·EV/EBITDA, 역대 배당</li>'
        '<li><b>공시·내부자</b> 10-K·8-K 앱에서 읽기, 임원 매매</li></ul></div>',
        unsafe_allow_html=True)
    st.markdown("**바로 보기**")
    st.pills("바로 보기", QUICK + ["DEMO"], key="quick_pick", on_change=on_quick_pick,
             label_visibility="collapsed", format_func=lambda t: "예시(DEMO)" if t == "DEMO" else t)
    st.caption("DEMO는 네트워크 없이 볼 수 있는 예시 데이터입니다. 관심종목은 ⭐ 관심·비교에서 모아 볼 수 있습니다.")


def on_view_change() -> None:
    st.query_params["v"] = st.session_state.get("view") or "company"


# ---------------------------------------------------------------- header
view = st.query_params.get("v") or "company"
if view not in VIEWS:
    view = "company"
st.session_state["view"] = view
with st.container(key="topbar"):
    brand, nav = st.columns([1, 2.6], vertical_alignment="center")
    brand.markdown('<div class="ed-app">📊 <b>Edger</b></div>', unsafe_allow_html=True)
    nav.segmented_control("화면", list(VIEWS), format_func=VIEWS.get, key="view", on_change=on_view_change,
                          label_visibility="collapsed", width="stretch")

watchlist.init()  # start reading browser storage early so the list is ready when needed

identity = resolve_identity()
ticker = (st.query_params.get("t") or "").upper()
if not identity and view == "company" and ticker and not data.is_demo(ticker):
    st.warning("SEC는 모든 요청에 이름과 이메일(User-Agent)을 요구합니다. 한 번만 입력하면 됩니다.")
    with st.form("identity_form"):
        value = st.text_input("이름 이메일", placeholder="Hong Gildong hong@example.com")
        if st.form_submit_button("저장", width="stretch") and value.strip():
            st.session_state["identity"] = value.strip()
            st.rerun()
    st.caption("배포할 때는 Secrets 의 `EDGAR_IDENTITY` 에 넣어두면 이 단계가 생략됩니다.")
    st.stop()
if identity:
    data.configure_identity(identity)

# ---------------------------------------------------------------- views
if view == "watch":
    if not identity and any(not data.is_demo(t) for t in watchlist.load()):
        st.warning("관심종목을 불러오려면 SEC용 이름·이메일이 필요합니다. 🔎 종목 화면에서 먼저 입력하세요.")
    else:
        view_compare.render()
else:
    if "ticker_input" not in st.session_state:
        st.session_state["ticker_input"] = ticker
    st.text_input("티커", key="ticker_input", on_change=on_ticker_input, icon=":material/search:",
                  placeholder="티커 검색 (예: AAPL) 후 엔터", label_visibility="collapsed")
    others = [t for t in st.session_state.get("recent", []) if t != ticker]  # not the one on screen
    if others:
        st.pills("최근 본 종목", others, key="recent_pick", on_change=on_recent_pick,
                 label_visibility="collapsed")
    if not ticker:
        welcome()
    else:
        view_company.render(ticker)

watchlist.sync()
