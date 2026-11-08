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

VIEWS = {"company": "🔎 종목", "watch": "⭐ 관심·비교"}


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


def on_view_change() -> None:
    st.query_params["v"] = st.session_state.get("view") or "company"


# ---------------------------------------------------------------- header
st.title("📊 Edger")
st.markdown('<div class="ed-sub">SEC EDGAR 공시 · 재무 · 주가 · 내부자 거래</div>', unsafe_allow_html=True)

view = st.query_params.get("v") or "company"
if view not in VIEWS:
    view = "company"
st.session_state["view"] = view
st.segmented_control("화면", list(VIEWS), format_func=VIEWS.get, key="view", on_change=on_view_change,
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
    st.text_input("티커", key="ticker_input", on_change=on_ticker_input,
                  placeholder="티커 입력 (예: AAPL, NVDA) 후 엔터", label_visibility="collapsed")
    if st.session_state.get("recent"):
        st.pills("최근 본 종목", st.session_state["recent"], key="recent_pick", on_change=on_recent_pick,
                 label_visibility="collapsed")
    if not ticker:
        st.info("티커를 입력하세요. 네트워크 없이 둘러보려면 **DEMO** 를 입력하면 예시 데이터를 볼 수 있습니다.")
    else:
        view_company.render(ticker)

watchlist.sync()
