# v22 이미지 검색 Google/Bing 크롤링 전환 (Wikimedia 제거)

## 배경 (문제 상황)

- 품종을 학명으로 검색하면 실제로는 Google에 컬러 실사 사진이 많은데, 시스템은 Wikimedia Commons의
  오래된 흑백 식물도감 삽화를 우선 후보로 보여주는 문제가 있었다.
- 원인: 실제 이미지 검색(Google Images) 소스가 아예 없었고, ①Serper 텍스트 검색으로 찾은 상위
  웹페이지를 크롤링해 `<img>` 태그를 추출하는 방식과 ②Wikimedia Commons API 검색만 쓰고 있었다.
  ①은 매칭 조건이 까다로워 후보가 거의 안 나왔고, ②는 항상 후보가 풍부해서 결과적으로 Commons가
  상위를 차지했다.

## 검토한 대안과 결정 (대화에서 확정된 방향)

1. **Serper Images 같은 유료 이미지 검색 API는 쓰지 않는다.** (요금 문제로 순수 크롤링만 사용하기로 결정)
2. Google 이미지 검색 결과 페이지를 브라우저 없이 HTML 크롤링으로 시도한다. 다만 Render의 고정 서버 IP에서는
   Google이 봇으로 판단해 차단·캡차·JS 전용 렌더링으로 막을 가능성이 높다는 점을 사전에 공유했다.
3. Google이 막히면 **Bing 이미지 검색 크롤링**으로 자동 폴백한다 (Bing은 `iusc` 앵커의 `m` 속성에
   이미지 JSON이 정적으로 박혀있어 헤드리스 브라우저 없이도 안정적으로 파싱 가능).
4. 기존 웹페이지 크롤링(`_web_page_candidates`)은 3순위 보조로 남긴다 (이미 나가는 Serper 텍스트검색
   비용 안에서 도는 것이라 추가 비용 없음).
5. **Wikimedia Commons는 완전히 제거한다.** 흑백 고서 이미지 품질이 사용에 부적합하다고 판단.
   (`wikimedia_service.py` 파일 자체는 삭제하지 않고 남겨두되, 파이프라인에서는 더 이상 호출하지 않음.)

## 실제 배포 후 발견된 버그와 수정

- **버그 1**: `routers/ai_reports.py`에 `BUILD_VERSION`이 별도로 하드코딩되어 있어, 응답의
  `build_version` 값이 실제 조사 로직 버전과 무관하게 항상 구버전 문자열로 덮어써지고 있었다.
  → `plant_research_service.BUILD_VERSION`을 단일 소스로 import해서 쓰도록 수정.
- **버그 2 (핵심)**: 배포 후 로그로 확인한 결과 Bing 크롤링은 매 쿼리 10개씩 정상 수집했지만
  (`iusc_records=25~35, candidates=10`), 최종 화면에는 사진이 0개로 나왔다. 원인은
  `_image_candidates()`의 관련성 필터(`relevance <= 0`이면 제외)였다. 이 필터는 원래 텍스트 검색
  스니펫을 검증하려고 만든 것인데, 이미지 검색 결과는 검색어 자체가 이미 학명이라 이미 타겟팅되어
  있음에도, 개별 이미지의 파일명/대체텍스트/원본페이지 URL에 학명 문자열이 우연히 없으면 무조건
  걸러버려서 정상 후보 20개가 전부 삭제되고 있었다.
  → 관련성 점수가 낮아도 버리지 않고 최소 기본점수(30점)를 부여하도록 수정. 텍스트 일치가 있으면
  그만큼 가점만 추가로 준다.
- Google 크롤링은 여전히 `status=200`이지만 후보 0개로 나오는 상태(HTML 구조 변경 또는 JS 렌더링
  전용으로 추정). 기능은 Bing 폴백으로 정상 동작하지만 근본 해결은 아니므로 향후 확인 필요.

## 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/services/google_image_crawler.py` (신규) | Google 이미지 검색 페이지 HTML 크롤링. 실패 원인(동의 페이지/캡차/짧은 응답)을 로그로 자동 판별. |
| `backend/app/services/bing_image_service.py` (신규) | Bing 이미지 검색 결과(`iusc` JSON) 크롤링. Google 실패/부족 시 자동 보강. |
| `backend/app/services/plant_research_service.py` | Wikimedia 호출 제거, Google→Bing 크롤링 체인 연결, 부위별(전체/근접) 쿼리 세트 적용, 관련성 필터 버그 수정, 진단 로그 추가. `BUILD_VERSION`을 `v22-google-bing-image-crawl`로 갱신. |
| `backend/app/routers/ai_reports.py` | 자체 `BUILD_VERSION` 하드코딩 제거, `plant_research_service.BUILD_VERSION` 단일 소스 사용. |

## 이미지 검색 쿼리 세트

- 전체사진: `{학명}`, `{학명} plant`, `{학명} mature plant`
- 근접사진: `{학명} flower`, `{학명} flower close up`, `{학명} bloom`, `{학명} inflorescence`

## 우선순위 체인

```
1순위: Google 이미지 크롤링 (무료, 현재 구조상 자주 실패)
2순위: Bing 이미지 크롤링 (무료, 현재 안정적으로 작동 확인됨)
3순위: 기존 Serper 웹검색 결과 페이지 크롤링 (보조)
※ Wikimedia Commons는 더 이상 사용하지 않음
```

## 남은 과제 (다음 세션에서 로그 확인 필요)

- Google 크롤링이 `status=200`인데도 후보 0개인 원인 상세 진단 (`BLOCKED_BY_CONSENT_PAGE` /
  `BLOCKED_BY_CAPTCHA` / `SUSPICIOUSLY_SHORT_HTML` 로그 태그로 다음 배포 후 확인 예정).
- Invoice 원본 유지·수량만 변경 로직, 품종정보 정확도, HWPX 안정화는 기존 구조가 요구사항과
  이미 부합하는 것으로 분석됨 — 실제 오작동 사례가 나오면 우선순위 2 이후로 진행.
