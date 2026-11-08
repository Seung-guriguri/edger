"""Smoke tests: render the app headlessly with the offline demo companies."""
from streamlit.testing.v1 import AppTest

APP = "../app.py"


def run(tab: str | None = None, **params) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    for k, v in params.items():
        at.query_params[k] = v
    if tab:
        at.session_state["company_tab"] = tab
    at.run()
    assert not at.exception, at.exception
    return at


def test_company_view_renders():
    at = run(t="DEMO")
    assert not at.error
    labels = [m.label for m in at.metric]
    for expected in ("주가", "시가총액", "매출", "영업이익", "EPS", "순차입금"):
        assert any(label.startswith(expected) for label in labels), (expected, labels)
    assert len(at.tabs) == 4


def test_valuation_tab():
    at = run(tab="💹 주가·가치", t="DEMO")
    labels = [m.label for m in at.metric]
    for expected in ("52주 최고", "PER", "PBR", "EV/EBITDA", "EV/EBIT", "PEG", "EPS", "BPS", "배당수익률",
                     "총 주주수익률"):
        assert expected in labels, (expected, labels)


def test_insider_tab():
    at = run(tab="👤 내부자", t="DEMO")
    assert "장내 매수" in [m.label for m in at.metric]


def test_statements_never_blank():
    at = run(t="DEMO")
    for period in ("연간", "분기"):  # TTM has no filed statement: covered in test_ttm_basis
        at.segmented_control(key="period").set_value(period).run()
        for kind in ("손익계산서", "재무상태표", "현금흐름표"):
            at.segmented_control(key="stmt_kind").set_value(kind).run()
            assert not at.exception
            assert not at.warning, (period, kind, [w.value for w in at.warning])
    labels = [m.label for m in at.metric]
    assert "이자보상배율" in labels and "유동비율" in labels


def test_filing_reader():
    at = run(tab="📄 공시", t="DEMO")
    at.selectbox(key="reader_pick").select_index(0).run()  # the latest 10-K in the demo list
    assert not at.exception
    assert any(e.label.startswith("사업 개요") for e in at.expander), [e.label for e in at.expander]


def test_watchlist_compare():
    at = run(v="watch")
    assert any("관심종목이 없습니다" in i.value for i in at.info)
    at.text_input(key="wl_add").set_value("DEMO DEMOB DEMOC").run()
    assert not at.exception
    assert at.session_state["watchlist"] == ["DEMO", "DEMOB", "DEMOC"]
    assert at.multiselect(key="cmp_pick").value == ["DEMO", "DEMOB", "DEMOC"]
    at.pills(key="cmp_metric").set_value("ROE").run()
    assert not at.exception


def test_star_adds_to_watchlist():
    at = run(t="DEMOB")
    at.button(key="star").click().run()
    assert at.session_state["watchlist"] == ["DEMOB"]


def test_empty_state():
    at = run()
    assert any("DEMO" in i.value for i in at.info)


def test_compare_eps_and_table_columns():
    at = run(v="watch")
    at.text_input(key="wl_add").set_value("DEMO DEMOB").run()
    at.pills(key="cmp_metric").set_value("EPS").run()
    assert not at.exception
    cols = list(at.dataframe[0].value.columns)
    assert "EV/EBITDA" in cols and "EPS" in cols


def test_ttm_basis():
    at = run(t="DEMO")
    at.segmented_control(key="period").set_value("TTM").run()
    assert not at.exception
    assert any("TTM 25.12" in md.value for md in at.markdown)
    # TTM at fiscal year end equals the fiscal year
    ttm_rev = next(m.value for m in at.metric if m.label == "매출")
    ttm_op = next(m.value for m in at.metric if m.label == "영업이익")
    at.segmented_control(key="period").set_value("연간").run()
    assert any("FY25" in md.value for md in at.markdown)
    assert next(m.value for m in at.metric if m.label == "매출") == ttm_rev
    assert next(m.value for m in at.metric if m.label == "영업이익") == ttm_op


def test_basis_survives_tab_switch():
    at = run(t="DEMO")
    at.segmented_control(key="period").set_value("TTM").run()
    at.session_state["company_tab"] = "📄 공시"
    at.run()
    assert at.segmented_control(key="period").value == "TTM"
    assert any("TTM 25.12" in md.value for md in at.markdown)
