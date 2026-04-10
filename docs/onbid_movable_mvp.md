# 온비드 동산 알림 MVP

## 목표

온비드 동산은 초기에 "좋은 물건 자동판단"까지 밀지 않고, 아래 수준의 **관심 품목 알림**을 먼저 만드는 것을 목표로 한다.

- 목록 진입
- 제목 / 카테고리 / 최저입찰가 / 입찰기간 / 링크 추출
- 관심 키워드 기반 필터
- 텔레그램 알림

즉, 첫 단계는 "판단 엔진"이 아니라 **내가 놓치기 싫은 동산이 올라오면 알려주는 채널**이다.

## 현재 확보한 것

- 온비드 메인 진입 가능
- 부동산 상세 진입 payload 확보
- 상세 탭 응답 구조 확인
- `callInterfaceApi.do` 같은 공통 API 존재 확인
- 다만 동산/부동산 공통으로 **목록 본체 요청은 아직 미확정**

## 현재 판단

- `requests`만으로 바로 운영 소스를 붙이기에는 아직 이르다
- 다음 단계는 **Playwright로 목록 DOM을 읽는 1차 수집**
- 이 단계에서 안정적으로 10건 정도만 읽혀도 "알림 전용 MVP"는 바로 만들 수 있다

## MVP 범위

### 1단계

- 온비드 동산 목록 페이지 접속
- 첫 페이지 상위 N건 추출
- 추출 필드:
  - title
  - category
  - min_bid_price
  - bid_period
  - source_url

### 2단계

- 설정 파일의 `include_categories`, `exclude_categories`, `keywords`, `exclude_keywords` 기반 필터
- 예:
  - 카테고리 포함: `자동차/운송장비`, `물품(기계)`, `물품(기타)`
  - 포함: `명품`, `시계`, `가방`, `카메라`, `노트북`
  - 제외: `토지`, `아파트`, `오피스텔`

### 3단계

- 신규 목록만 텔레그램 전송
- 초기 메시지는 아래 정도면 충분

```text
📦 [온비드동산] 카메라
제목: ...
최저입찰가: ...
입찰기간: ...
링크: ...
```

## 다음에 필요한 것

1. 실제 온비드 동산 목록 URL 확정
2. Playwright에서 목록 카드/행 셀렉터 확정
3. 10건 스모크 테스트
4. 그 다음에만 `run_daily.py` 편입 검토

## 현재 확보한 URL 후보

- 현재 1차 우선 후보:
  - `https://medu.onbid.co.kr/mo/cta/onbidbest/clickTop20CltrListByEtc.do`
  - 실제 Playwright 렌더링 기준으로 물건 텍스트가 확인됨
- 내부 data 경로 후보:
  - `https://medu.onbid.co.kr/mo/cta/onbidbest/data/clickTop20CltrListByEtc.do`
- 보조 후보:
  - `https://medu.onbid.co.kr/mo/cta/onbidbest/interestTop20CltrListByEtc.do`
  - `https://medu.onbid.co.kr/mo/cta/onbidbest/halfOutletCltrListByEtc.do`

설명:
- 메뉴 JS에서 `동산/기타자산` 관련 실제 라우팅 문자열을 확인했다.
- Playwright 렌더링 결과:
  - `관심물건 BEST20`: 비어 있음
  - `50% 물건`: 비어 있음
  - `클릭랭킹 TOP20`: 실제 동산 물건 텍스트 확인
- 따라서 다음 단계는 `clickTop20CltrListByEtc.do`를 기준으로 DOM 셀렉터를 고정하는 것이다.

## 추가 탐색 메모

- 일반 모바일 검색 페이지:
  - `https://medu.onbid.co.kr/mo/cta/cltr/cltrSearch.do`
- 실제 목록 로드 경로:
  - `/mo/cta/cltr/data/cltrSearchList.do`
- 필터 팝업:
  - `https://medu.onbid.co.kr/mo/cta/cltr/cltrSearchFilterPopup.do`

현재 확인한 동산 구분 코드는 아래와 같다.

- `bizDvsnCd=0002`: 자동차/운송장비
- `bizDvsnCd=0003`: 물품(기계)
- `bizDvsnCd=0004`: 물품(기타)

자동차 프리셋도 별도로 존재한다.

- `searchType=OCL`: 온카랜드
  - `searchCtgrId1=0002`
  - `searchCtgrNm1=자동차/운송장비`
  - `searchCtgrId2=12100`
  - `searchCtgrNm2=자동차`
  - `searchCtgrId3=12101,12102,12103,12105`
  - `searchCtgrNm3=승용차 외3 선택`

의미:
- 지금 운영 중인 `clickTop20` 랭킹 페이지가 비어 있을 때도
- 향후에는 `cltrSearchList.do` 쪽으로 넘어가면 자동차/기계/기타를 코드 기준으로 직접 검색할 수 있는 가능성이 높다.

현재 직접 확인한 결과:
- 자동차/운송장비(`OCL`): 0건
- 물품(기계): 2건
- 물품(기타): 4건

샘플:
- 물품(기계): `삼성 모니터 -shh` / `컴퓨터및주변기기` / `100,000원`
- 물품(기타): `수박` / `과실목` / `111,111원`

참고:
- `scripts/onbid_movable_data_probe.py` 로 동일 검증을 다시 실행할 수 있다.
- 현재 실험 알림 기본 preset은 `machine`, `other` 두 개를 사용한다.
- 자동차(`ocl`)는 구조는 확인됐지만 현재 조회 결과가 0건이라 관찰용으로만 둔다.

## 스모크 테스트 후보

- 자동차 전용(온카랜드) 빠른 확인:
  - `https://medu.onbid.co.kr/mo/cta/cltr/cltrSearch.do?searchType=OCL`
- 스크립트:
  - `scripts/onbid_ocl_smoke_test.py`

의미:
- 랭킹 페이지에 자동차가 안 떠도
- `searchType=OCL`로 자동차/운송장비 프리셋 검색 결과가 바로 뜨는지 독립적으로 확인할 수 있다.

## 운영 원칙

- 법원경매/customs처럼 바로 운영 소스로 붙이지 않는다
- 목록 안정성이 검증되기 전까지는 **실험용 스크립트**로 유지
- 1주 운영 관찰 이후에만 정식 source로 승격한다
