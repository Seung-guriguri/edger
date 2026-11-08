"""Smoke tests: render the app headlessly with the offline demo companies."""
from streamlit.testing.v1 import AppTest

APP = "../app.py"


def run(tab: str | None = None, fin_view: str | None = None, **params) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    for k, v in params.items():
        at.query_params[k] = v
    if tab:
        at.session_state["company_tab"] = tab
    if fin_view:
        at.session_state["fin_view"] = fin_view
    at.run()
    assert not at.exception, at.exception
    return at


def page_text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def kpi_value(at: AppTest, label: str) -> str:
    import re
    m = re.search(rf'<div class="ed-kl">{re.escape(label)}</div><div class="ed-kv">([^<]+)</div>', page_text(at))
    assert m, label
    return m.group(1)


def test_signals():
    at = run(t="DEMO")
    text = page_text(at)
    assert "한눈에 보기" in text
    for label in ("밸류에이션", "성장", "수익성", "재무 안정성"):
        assert label in text, label


def test_company_view_renders():
    at = run(t="DEMO")
    assert not at.error
    labels = [m.label for m in at.metric]
    text = page_text(at)
    for kpi in ("매출", "영업이익", "순이익", "EPS", "ed-kgrid"):
        assert kpi in text, kpi
    for expected in ("ed-hp", "시총", "PER", "결산"):  # price, market cap and PER live in the header
        assert expected in text, expected
    assert len(at.tabs) == 6
    at = run(t="DEMO", fin_view="안정성")
    text = page_text(at)
    for expected in ("재무 안정성", "분기말 기준", "총차입금", "부채비율", "D/E", "리스 포함", "유동비율", "이자보상배율"):
        assert expected in text, expected


def test_valuation_tab():
    at = run(tab="가치", t="DEMO")
    text = page_text(at)
    assert "52주 최고" in text
    for expected in ("PER", "PBR", "EV/EBITDA", "EV/EBIT", "PEG", "EPS", "BPS", "1년 전 대비"):
        assert expected in text, expected


def test_insider_tab():
    at = run(tab="내부자", t="DEMO")
    assert "장내 매수" in page_text(at)


def test_statements_never_blank():
    at = run(t="DEMO", fin_view="재무제표")
    for period in ("연간", "분기"):  # TTM has no filed statement: covered in test_ttm_basis
        at.segmented_control(key="period").set_value(period).run()
        for kind in ("손익계산서", "재무상태표", "현금흐름표"):
            at.segmented_control(key="stmt_kind").set_value(kind).run()
            assert not at.exception
            assert not at.warning, (period, kind, [w.value for w in at.warning])
    at.session_state["fin_view"] = "안정성"
    at.run()
    assert "이자보상배율" in page_text(at) and "유동비율" in page_text(at)


def test_filing_reader():
    at = run(tab="공시", t="DEMO")
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
    assert "미국 상장사를 SEC 공시로" in page_text(at)
    at.pills(key="quick_pick").set_value("DEMO").run()
    assert not at.exception
    assert at.query_params["t"] == ["DEMO"] or at.query_params["t"] == "DEMO"


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
    ttm_rev = kpi_value(at, "매출")
    ttm_op = kpi_value(at, "영업이익")
    at.segmented_control(key="period").set_value("연간").run()
    assert any("FY25" in md.value for md in at.markdown)
    assert kpi_value(at, "매출") == ttm_rev
    assert kpi_value(at, "영업이익") == ttm_op


def test_basis_survives_tab_switch():
    at = run(t="DEMO")
    at.segmented_control(key="period").set_value("TTM").run()
    at.session_state["company_tab"] = "공시"
    at.run()
    assert at.segmented_control(key="period").value == "TTM"
    assert any("TTM 25.12" in md.value for md in at.markdown)


def test_dividend_tab():
    at = run(tab="배당", t="DEMO")
    assert not at.error
    text = page_text(at)
    for expected in ("최근 12개월 배당", "최근 배당", "연속 배당", "연속 증액", "배당 성장률", "배당성향",
                     "자사주 매입액", "총 주주수익률"):
        assert expected in text, expected
    at.segmented_control(key="div_view").set_value("회차별").run()
    assert not at.exception


def test_dividend_tab_non_payer():
    at = run(tab="배당", t="DEMOB")
    assert any("배당 기록이 없습니다" in i.value for i in at.info)


def test_business_tab():
    at = run(tab="사업", t="DEMO")
    assert not at.error
    text = page_text(at)
    for expected in ("사업 개요", "매출 구성", "Industrial Robots", "영업이익률", "연도별 구성", "비용 구조",
                     "매출원가", "매출의", "ed-dot"):
        assert expected in text, expected
    at.segmented_control(key="biz_axis").set_value("지역").run()
    assert not at.exception and "United States" in page_text(at)
