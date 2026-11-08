# Edger 📊

[edgartools](https://github.com/dgunning/edgartools) 기반의 **모바일 우선** SEC EDGAR 기업 대시보드 (Streamlit).

티커를 입력하면 다음을 보여줍니다.

- **핵심 지표**: 최근 회계연도 매출·순이익·영업이익률·잉여현금흐름, 전년 대비 변화
- **재무**: 연간/분기 매출·영업이익·순이익·FCF·EPS 추이, 수익성(마진) 추이, 현금·부채비율, 표 보기
- **공시**: 최근 공시 목록 (정기보고서/수시공시/내부자/주총/지분 필터), 탭하면 SEC 원문
- **내부자**: 최근 Form 4 거래, 장내 매수·매도 합계와 월별 차트

네트워크 없이 둘러보려면 티커에 `DEMO` 를 입력하세요 (예시 데이터).

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
app.py              Streamlit 화면 (모바일 레이아웃, 캐싱)
edger/data.py       edgartools 호출 (회사 정보, XBRL facts, 공시 목록, Form 4)
edger/metrics.py    XBRL facts → 연간/분기 재무 표 (태그 변경 대응, 4분기·분기 현금흐름 차감 계산)
edger/charts.py     모바일용 Plotly 차트 (드래그/줌 비활성화로 스크롤 방해 없음)
edger/demo.py       오프라인 예시 데이터 (DEMO)
tests/              pytest
```

## 참고

- 데이터는 6시간 캐시합니다 (SEC 요청 제한: 초당 10회).
- 내부자 탭은 Form 4 한 건당 SEC 요청 1회가 필요해 처음 열 때 몇 초 걸립니다.
- 재무 수치는 회사가 제출한 XBRL 태그에서 계산하므로 회사별로 일부 항목이 비어 있을 수 있습니다.
  투자 판단 전 원문 공시를 확인하세요.

## 테스트

```bash
pip install pytest
pytest -q
```
