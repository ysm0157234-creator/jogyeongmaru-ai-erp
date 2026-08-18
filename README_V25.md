# v25 이미지 검색 병렬화 (조사 지연 완화)

## 배경

v24에서 이미지 소스를 iNaturalist + DuckDuckGo + Bing으로 늘리면서 HTTP 요청이 20회가 됐고,
이걸 **전부 순차로** 실행하고 있었다. 요청 하나하나의 왕복시간이 그대로 쌓인다.

로컬(가정용 회선) 측정: **17.4초**. Render 무료 플랜 + 싱가포르 리전에서는 이보다 훨씬 느리다.

## 수정

전부 네트워크 대기라서 병렬로 던지면 거의 "가장 느린 요청 하나"의 시간으로 끝난다.

1. **전체사진 · 근접사진 동시 실행** — 두 조사는 서로 독립적이다.
2. **쿼리별 검색 동시 실행** (`collect()`) — 결과는 쿼리 순서대로 모아서 **순위는 그대로 보존**한다.
3. **iNaturalist · DuckDuckGo 동시 실행** — 서로 독립적이다.
4. **iNaturalist 결과 캐시** — 같은 학명을 전체·근접에서 두 번 조회하던 낭비 제거.
5. **타임아웃 15초 → 8초** — 요청 하나가 멈춰도 전체를 붙잡지 못하게.

정렬 안정성: 병렬 실행이지만 중복 제거와 인터리브는 **쿼리 순서대로** 적용하므로,
결과 순서는 완료 순서에 좌우되지 않고 매번 동일하다.

## 측정 결과

| | 수정 전 (v24) | 수정 후 (v25) |
|---|---|---|
| 전체+근접 소요 | 17.4초 | **2.6초** |
| HTTP 요청 수 | 20회 | 20회 (동일, 병렬 실행) |

약 6.7배 빨라졌다.

## 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/services/plant_research_service.py` | `ThreadPoolExecutor` 도입 — 역할별·쿼리별·소스별 병렬화. `BUILD_VERSION` → `v25-parallel-image-search`. |
| `backend/app/services/inaturalist_service.py` | 학명 기준 결과 캐시(`_PHOTO_CACHE`), 타임아웃 8초. |
| `backend/app/services/duckduckgo_image_service.py` | 타임아웃 8초. |
| `backend/app/services/bing_image_service.py` | 타임아웃 8초. |

## 참고: 조사 자체는 원래 백그라운드 작업이다

`POST /api/ai-reports/generate`는 `BackgroundTasks`로 즉시 반환하고,
프론트가 `waitForDraft()`로 2초마다 폴링하며 **최대 8분**까지 기다린다.
따라서 이미지 수집 지연만으로 8분 한도를 넘기지는 않는다.
"타임아웃"이 어디서 나는지에 따라 원인이 다르므로 아래를 구분해야 한다.

- `조사 시간이 8분을 초과했습니다` → 프론트 폴링 한도 초과 (조사 전체가 느림)
- `생성 실패` + 오류 메시지 → 백그라운드 작업 중 예외 (Gemini/Serper/Drive 쪽 가능성)
- 로그인/첫 요청부터 느림 → Render 무료 플랜 인스턴스 슬립에서 깨어나는 시간
