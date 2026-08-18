# v23 이미지 관련도 정렬 수정 (Bing 결과가 무관한 사진만 뜨던 문제)

## 증상

배포된 사이트에서 Bing 크롤링 사진은 정상적으로 뜨는데, **품종과 전혀 관련 없는 사진만** 상위에 노출됐다.

## 원인 (v22에서 넣은 수정의 부작용)

v22에서 "관련성 점수 0이면 버린다"는 필터가 정상 후보까지 전부 삭제하는 버그를 고치면서
`relevance = max(relevance, 30)` 으로 최소 기본점수를 줬다. 그런데 이 값이 실제 점수보다 커서
**관련도 신호 자체를 없애버렸다.**

- `_score()`는 첫 단어 14점 + 나머지 단어 각 9점이다. 학명은 두 단어(`Yucca filamentosa`)이므로
  **완벽하게 일치해도 23점**이고, 이는 기본점수 30점보다 낮다.
- 따라서 `max(23, 30)`과 `max(0, 30)`이 **똑같이 30점**이 된다. 일치한 사진과 무관한 사진이 동점.
- 최종 점수 = 30 + `_domain_priority(context_url)`인데, 크롤링 이미지의 원본 페이지는 대부분
  우선순위 목록에 없는 블로그라 일괄 40점. 결국 **거의 모든 후보가 정확히 70점**이 된다.
- 전부 동점이니 정렬은 `key`의 두 번째 항목인 **제목 가나다순**으로 결정된다. 사실상 무작위다.
- 즉 **Bing이 매겨준 관련도 순위(우리가 가진 가장 강한 신호)가 완전히 버려지고 있었다.**

추가로, 여러 쿼리 결과를 그냥 이어붙이고 있어서 1번 쿼리의 10위가 2번 쿼리의 1위보다 앞에 왔다.

## 수정 내용

### 1. 검색 순위를 점수의 기준으로 삼는다

검색어가 이미 학명이므로 검색엔진의 순서가 가장 신뢰할 만한 관련도 신호다.

```
relevance_score = rank_score + text_bonus + domain_bonus
  rank_score   = max(0, 100 - 순위*4)    # 뼈대: 앞에 있을수록 높음
  text_bonus   = _score(...) * 2          # 학명이 파일명·제목에 있으면 가점 (없어도 버리지 않음)
  domain_bonus = _domain_priority() // 10 # 동점 처리용으로만 (40~100점이 신호를 덮지 않도록)
```

### 2. 동점 시 제목 가나다순 → 검색 순위순

무작위 정렬의 직접적 원인을 제거.

### 3. 쿼리별 결과를 라운드로빈으로 인터리브 (`_interleave`)

`[A1,A2,A3] [B1,B2] [C1,C2,C3]` → `A1,B1,C1,A2,B2,C2,A3,C3`
각 쿼리의 1위끼리 먼저 배치되도록.

### 4. 사진이 될 수 없는 후보 제외 (`_is_usable_photo`)

- `.svg` / `.gif` / `.ico` / `.bmp` (벡터 아이콘·로고)
- 가로 또는 세로 200px 미만 (아이콘·썸네일 조각)
- 가로세로 비율 3:1 초과 (배너)

## 검증 (동일 입력, 수정 전/후 비교)

| 순위 | 수정 전 (v22) | 수정 후 (v23) |
|---|---|---|
| 1 | Yucca filamentosa flower detail (130점) | **Yucca filamentosa in bloom (150점)** |
| 2 | Adam's needle plant (70점) | **Yucca filamentosa flower detail (148점)** |
| 3 | Agave americana desert (70점) | Adam's needle plant (100점) |
| 4 | **logo** 64×64 아이콘 (70점) | Zebra grass border ideas (92점) |
| 5 | **wide banner** 1200×200 (70점) | Agave americana desert (88점) |
| 6 | Yucca filamentosa in bloom ← 실제 목표 사진 (70점) | — (아이콘·배너는 제외됨) |

## 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/services/plant_research_service.py` | `_image_candidates()` 점수 체계 재설계, `_is_usable_photo()`·`_interleave()` 추가, `_crawled_image_candidates()`가 쿼리별 순위를 보존하도록 수정. `BUILD_VERSION`을 `v23-image-relevance-ranking`으로 갱신. |
| `.gitignore` (신규) | `.DS_Store`, `__pycache__`, `*.pyc`, `node_modules`, `.env` 추적 제외 |

## 배포 후 확인할 로그

```
[plant_research_service] role=... identity=... google_raw=N total_raw=N scored_candidates=N top=[(순위, 점수, 제목), ...]
```

`top=`에 학명이 포함된 제목이 상위에 오는지 확인한다.

## 남은 과제

- Google 크롤링이 `status=200`인데 후보 0개인 원인 (v22에서 이월). 현재는 Bing 폴백으로 동작.
- 학명 자체가 잘못 추출되면 검색어가 틀려 무관한 사진이 나온다. 위 로그의 `identity=` 값으로 확인 가능.
