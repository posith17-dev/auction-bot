# auction-bot

법원경매 일일 수집기 MVP입니다.

현재 목표는 "좋은 경매 물건을 자동 판단해서 채널로 보내는 것"이고, 첫 소스로 법원경매(`courtauction.go.kr`)를 붙였습니다.
다음 소스 후보로 관세청 공매공고 공개 게시판 collector를 추가했고, 현재 본청/부산 게시판 첫 페이지 10건 파싱까지 확인했습니다.

## 현재 상태

- 소스: 법원경매
- 저장: DuckDB
- 출력:
  - daily markdown report
  - 텔레그램 신규 알림
- 스케줄링:
  - `auction-daily.service`
  - `auction-daily.timer`
- 보존 정책:
  - 최근 3개월 데이터만 유지

## 현재 검증된 검색 프로필

현재는 코드 캡처로 검증된 프로필만 사용합니다.

- `seoul_apartment`
  - 서울중앙지방법원
  - 부동산 > 건물 > 주거용건물 > 아파트
  - 기일입찰
- `seoul_apartment_upto_5eok`
  - 위와 동일
  - 감정가 5억 이하

다른 법원/유형/지역은 추측으로 넣지 않았습니다.
전국 확장을 하려면 각 검색 조건 코드(`select*Lst.on`)를 한 번씩 더 캡처해야 합니다.

## 프로젝트 구조

```text
/home/ubuntu/auction-bot/
├── collector/
│   ├── court_auction.py
│   └── customs_notice.py
├── storage/
│   ├── auction.duckdb
│   └── schema.py
├── alerts/
│   └── telegram.py
├── reports/
│   └── daily_report.py
├── deploy/
│   ├── auction-daily.service
│   ├── auction-daily.timer
│   └── install_auction_timer.sh
├── config.yaml
└── run_daily.py
```

## 핵심 동작

### 1. 수집

`collector/court_auction.py`는 법원경매 `searchControllerMain.on` 목록조회 요청을 재현합니다.

중요:
- 쿠키 없이도 목록조회가 동작하는 것을 확인했습니다.
- 상세 URL은 현재 "상세 진입 후보 deep-link" 수준입니다.
  - 메시지로는 충분하지만, 완전한 상세 permalink는 아직 아닙니다.

### 2. 저장

`storage/schema.py`는 `listings` 테이블에 upsert합니다.

주요 컬럼:
- `listing_id`
- `search_name`
- `title`
- `address`
- `region`
- `property_type`
- `appraisal_price`
- `min_bid_price`
- `discount_rate`
- `discount_score`
- `round_score`
- `opportunity_score`
- `price_bucket`
- `auction_date`
- `source_url`

### 3. 알림

`run_daily.py`는 신규 물건만 대상으로 알림 필터를 적용합니다.

현재 알림 조건:
- 할인율 30% 이상
- 아파트/다세대
- 서울
- 감정가 5억 이하

조건 매칭이 0건이면 텔레그램은 보내지 않고, 리포트에만 남깁니다.

### 4. 리포트

`reports/daily_report.py`는 아래 섹션을 생성합니다.

- `search summaries`
- `alert matches`
- `top discount listings`
- `top opportunity listings`
- `fetched listings`

## 실행

수동 실행:

```bash
/home/ubuntu/trading-system/.venv/bin/python /home/ubuntu/auction-bot/run_daily.py --config /home/ubuntu/auction-bot/config.yaml
```

타이머 확인:

```bash
systemctl status auction-daily.timer --no-pager -n 20
systemctl status auction-daily.service --no-pager -n 30
```

## 텔레그램 설정

`config.yaml`에는 채널 `chat_id`만 남기고, 봇 토큰은 파일에 직접 두지 않는 방향으로 정리했습니다.

토큰 로드 순서:
1. 환경변수
2. `/home/ubuntu/trading-bot/.env`
3. `/home/ubuntu/trading-system/config/secrets.env`

운영 메모:
- 토큰은 한 번 채팅에 노출됐기 때문에, 실제 운영 전 BotFather에서 재발급 권장

## 현재 한계

- 법원경매 상세보기 링크는 아직 완전하지 않음
- 전국/다유형 확장은 추가 코드 캡처 필요
- 동일 사건의 가격/유찰횟수 변화는 아직 별도 이벤트로 분리하지 않음

## 다음 단계 후보

1. 서울 다세대 / 경기 아파트 프로필 추가
2. 동일 사건 변화 감지 알림
3. 상세 permalink 개선
4. 온비드 또는 다른 공개 소스 추가
5. 관세청 공매공고 공개 게시판 연결

## 관세청 공매공고 메모

- collector: `collector/customs_notice.py`
- 현재 검증 범위:
  - `https://www.customs.go.kr/kcs/ad/go/gongMeList.do?mi=2898&tcd=1`
  - `https://www.customs.go.kr/busan/ad/go/gongMeList.do?mi=7178&tcd=1`
  - 본청/부산 첫 페이지 공고 10건 파싱 확인
- 주의:
  - `pageIndex`, `pageUnit` 파라미터는 공개 게시판에서 안정적으로 동작하는지 아직 미확정이라 기본 요청에서는 제외했습니다.
  - 세관별로 `list_path`, `detail_path`, `referer`가 달라질 수 있어 설정 기반으로 일반화했습니다.
