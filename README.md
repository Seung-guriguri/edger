# Edger 📊

[edgartools](https://github.com/dgunning/edgartools) 기반의 **모바일 우선** SEC EDGAR 기업 대시보드 (Streamlit).

### 🔎 종목 화면
- **핵심 지표**: 주가·시가총액(PER), 최근 회계연도 매출·순이익·영업이익률·ROE와 전년 대비 변화
- **📈 재무**: 연간/분기 매출·영업이익·순이익·FCF·EPS·주식수 추이, 마진, ROE·ROIC,
  1년·3년·5년 성장률(CAGR), 현금·차입금·부채비율, **전체 재무제표**(손익·재무상태·현금흐름)
- **💹 주가·가치**: 주가 차트(1~10년), 52주 최고·최저, PER·PSR·PBR·EV/EBIT·FCF 수익률(최근 4분기 기준),
  연도별 PER과 현재 PER 비교
- **📄 공시**: 10-K(사업 개요·리스크 요인·MD&A), 10-Q, 8-K(항목별 내용·보도자료)를 **앱 안에서 읽기**,
  종류별 공시 목록
- **👤 내부자**: 최근 Form 4 거래, 장내 매수·매도 합계와 월별 차트

### ⭐ 관심·비교 화면
- 관심종목 표(주가, 일간 변동, 시총, PER, 매출 증가율, 영업이익률, ROE) — 행을 누르면 종목 화면으로
- 최대 5개 종목을 골라 매출·성장률·마진·ROE·ROIC 추이 비교
- 관심종목은 **폰 브라우저에 저장**되어 다시 열어도 유지됩니다 (계정 불필요)

네트워크 없이 둘러보려면 티커에 `DEMO` 를 입력하세요. 관심·비교 화면에서는 `DEMO DEMOB DEMOC` 를 추가하면
예시 회사 3곳을 비교해 볼 수 있습니다.

## 로컬 실행

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 이름과 이메일 입력
streamlit run app.py
```

SEC는 모든 요청에 `이름 이메일` 형태의 User-Agent를 요구합니다. `secrets.toml` 이나 환경변수
`EDGAR_IDENTITY` 로 설정하거나, 설정하지 않으면 앱 첫 화면에서 입력받습니다.

### 같은 와이파이의 폰에서 보기

`streamlit run app.py` 출력의 **Network URL** (예: `http://192.168.0.10:8501`)을 폰 브라우저에서 엽니다.

## 폰에서 어디서나 쓰기 (무료 배포)

1. 이 저장소를 GitHub에 푸시
2. [share.streamlit.io](https://share.streamlit.io) 에서 저장소 연결, 메인 파일 `app.py` 선택
3. 앱 설정 → **Secrets** 에 `EDGAR_IDENTITY = "Your Name you@example.com"` 입력
4. 폰 브라우저로 URL을 열고 **홈 화면에 추가** 하면 앱처럼 실행됩니다

`?t=AAPL` 처럼 URL에 티커를 넣으면 바로 그 종목이 열리므로, 자주 보는 종목은 북마크해 두면 편합니다.
무료 플랜은 한동안 접속이 없으면 잠들어서 첫 접속에 30초 정도 걸릴 수 있습니다.

## 구조

```
app.py                 화면 전환(종목 / 관심·비교), 검색, SEC 이메일 설정
edger/view_company.py  종목 화면 (재무 / 주가·가치 / 공시 / 내부자 탭)
edger/view_compare.py  관심종목 표와 비교 차트
edger/ui.py            공통 스타일, 캐시된 데이터 로더, KPI 카드
edger/data.py          edgartools 호출 (회사 정보, XBRL facts, 재무제표, 공시 목록·본문, Form 4)
edger/metrics.py       XBRL facts → 연간/분기 재무 표, ROE·ROIC, CAGR, TTM, 밸류에이션
edger/market.py        주가 (yfinance)
edger/watchlist.py     관심종목 (브라우저 localStorage)
edger/charts.py        모바일용 Plotly 차트 (드래그/줌 비활성화로 스크롤 방해 없음)
edger/demo.py          오프라인 예시 데이터 (DEMO, DEMOB, DEMOC)
tests/                 pytest
```

## 참고

- SEC 데이터는 6시간, 주가는 15분 캐시합니다 (SEC 요청 제한: 초당 10회).
- 주가는 SEC에 없어서 Yahoo Finance(yfinance)에서 가져옵니다. Yahoo가 일시적으로 막혀도
  재무·공시 탭은 그대로 동작하고 주가·밸류에이션만 비어 보입니다.
- 밸류에이션은 최근 4분기 합계(TTM) 기준이며, 분기 데이터가 부족하면 최근 회계연도로 대신합니다.
- ROIC의 차입금은 XBRL 태그 기준 추정치입니다 (리스 부채 등은 제외될 수 있음).
- 내부자 탭은 Form 4 한 건당 SEC 요청 1회가 필요해 처음 열 때 몇 초 걸립니다.
- 재무 수치는 회사가 제출한 XBRL 태그에서 계산하므로 회사별로 일부 항목이 비어 있을 수 있습니다.
  투자 판단 전 원문 공시를 확인하세요.

## 테스트

```bash
pip install pytest
pytest -q
```
