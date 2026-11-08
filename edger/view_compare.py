"""Watchlist overview and side-by-side comparison of up to five companies."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import charts, fmt, watchlist
from .metrics import change
from .ui import load_profile, load_snapshot, plot, theme_mode

MAX_COMPARE = 5

# label -> (table column or special key, is_percent)
COMPARE_METRICS = {
    "매출": ("revenue", False),
    "매출 성장률": ("revenue_growth", True),
    "영업이익률": ("operating_margin", True),
    "순이익률": ("net_margin", True),
    "FCF 마진": ("fcf_margin", True),
    "ROE": ("roe", True),
    "ROIC": ("roic", True),
}


def _open_company(ticker: str) -> None:
    st.query_params["t"] = ticker
    st.query_params["v"] = "company"
    st.session_state["ticker_input"] = ticker


def _add_from_input() -> None:
    value = (st.session_state.get("wl_add") or "").strip().upper()
    for t in [v.strip() for v in value.replace(",", " ").split() if v.strip()]:
        watchlist.add(t)
    st.session_state["wl_add"] = ""


def render() -> None:
    items = watchlist.load()

    st.text_input("관심종목 추가", key="wl_add", on_change=_add_from_input,
                  placeholder="관심종목 추가 (예: AAPL MSFT) 후 엔터", label_visibility="collapsed")
    if not items:
        st.info("관심종목이 없습니다. 위에 티커를 입력하거나, 종목 화면에서 ☆ 버튼을 누르세요. "
                "오프라인으로 해보려면 `DEMO DEMOB DEMOC` 를 추가하세요.")
        return

    snaps, failed = {}, []
    with st.spinner(f"관심종목 {len(items)}개 불러오는 중…"):
        for t in items:
            try:
                snaps[t] = load_snapshot(t)
            except Exception:
                failed.append(t)
    if failed:
        st.warning(f"불러오지 못한 종목: {', '.join(failed)}")

    _table(snaps)
    _compare(snaps)

    with st.expander("관심종목 편집"):
        keep = st.multiselect("관심종목", items, default=items, key="wl_edit",
                              label_visibility="collapsed")
        if st.button("변경 저장", width="stretch") and keep != items:
            for t in items:
                if t not in keep:
                    watchlist.remove(t)
            st.rerun()
        st.caption("관심종목은 이 기기의 브라우저에 저장됩니다.")


def _table(snaps: dict) -> None:
    rows = []
    for t, s in snaps.items():
        q, v, annual = s["quote"], s["valuation"], s["annual"]
        _, growth = change(annual, "revenue")
        om = annual["operating_margin"].dropna() if not annual.empty else pd.Series(dtype=float)
        roe = annual["roe"].dropna() if not annual.empty else pd.Series(dtype=float)
        rows.append({
            "티커": t,
            "주가": fmt.per_share(q.get("price")) if q.get("price") else "–",
            "일간": fmt.pct(q.get("change"), signed=True),
            "시총": fmt.money(s.get("market_cap")),
            "PER": f"{v['per']:.1f}" if v.get("per") else "–",
            "매출↑": fmt.pct(growth, signed=True),
            "영업이익률": fmt.pct(om.iloc[-1]) if len(om) else "–",
            "ROE": fmt.pct(roe.iloc[-1]) if len(roe) else "–",
        })
    st.markdown("**관심종목** <span class='ed-meta'>행을 누르면 종목 화면으로</span>", unsafe_allow_html=True)
    event = st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         on_select="rerun", selection_mode="single-row", key="wl_table")
    sel = event.selection.rows if event and event.selection else []
    if sel:
        _open_company(rows[sel[0]]["티커"])
        del st.session_state["wl_table"]  # otherwise coming back would jump straight away again
        st.rerun()
    st.caption("매출↑ = 최근 회계연도 매출 증가율, PER = 최근 4분기 기준.")


def _compare(snaps: dict) -> None:
    tickers = list(snaps)
    if len(tickers) < 2:
        st.caption("관심종목이 2개 이상이면 비교 차트가 나타납니다.")
        return
    st.markdown("**비교**")
    chosen = st.multiselect("비교할 종목", tickers, default=tickers[:3], max_selections=MAX_COMPARE,
                            key="cmp_pick", label_visibility="collapsed",
                            placeholder=f"비교할 종목 선택 (최대 {MAX_COMPARE}개)")
    if not chosen:
        return
    metric = st.pills("비교 지표", list(COMPARE_METRICS), default="매출 성장률", key="cmp_metric",
                      label_visibility="collapsed") or "매출 성장률"
    col, percent = COMPARE_METRICS[metric]

    series = {}
    for t in chosen:  # keep watchlist order so each ticker keeps its color
        annual = snaps[t]["annual"]
        if annual.empty:
            series[t] = None
            continue
        values = annual["revenue"].pct_change() if col == "revenue_growth" else annual[col]
        series[t] = pd.Series(values.values, index=annual["label"].values).tail(8)
    labels = sorted({lbl for s in series.values() if s is not None for lbl in s.index})
    series = {t: (s.reindex(labels) if s is not None else None) for t, s in series.items()}
    plot(charts.compare_lines(series, theme_mode(), percent=percent))

    names = []
    for t in chosen:
        try:
            names.append(f"**{t}** {load_profile(t).get('name', '')}")
        except Exception:
            names.append(f"**{t}**")
    st.caption(" · ".join(names) + ". 회계연도 기준이라 결산월이 다른 회사는 시기가 조금 어긋납니다.")
