# v24 이미지 소스 전면 교체 (Google 크롤링 포기 → iNaturalist + DuckDuckGo)

## 1. "Google로 크롤링할 수 없나?" — 불가능한 것으로 확인됨

v22부터 Google 이미지 크롤링이 `status=200`인데 후보 0개인 원인을 계속 추적해 왔다.
이번에 **집(주거용) IP에서 직접 요청해서** 원인을 확정했다.

```
html_bytes: 92610
consent page?: False          ← 쿠키 동의 페이지 아님
captcha?:     False           ← 캡차 아님
.jpg 등장 횟수:      0
encrypted-tbn 등장:  0
<img 태그 수:        0        ← 이미지가 HTML에 아예 없음
<script 태그 수:     5
HTML 앞부분: <noscript>... <meta content="0;url=/httpservice/retry/enablejs" ...
```

- **Render의 서버 IP 차단 문제가 아니다.** 일반 가정용 IP에서도 결과가 0개다.
- Google 이미지 검색은 **결과를 JavaScript로만 렌더링한다.** HTML에는 `<img>` 태그도,
  이미지 URL도 하나도 없고 `enablejs`로 리다이렉트하는 `<noscript>`만 들어 있다.
- 즉 **헤드리스 브라우저(Playwright/Selenium) 없이는 원리적으로 불가능**하다.
  Render에서 Chromium을 띄우면 메모리·빌드시간·비용이 크게 늘어나므로 채택하지 않았다.

→ `google_image_crawler.py`는 **파이프라인에서 제외**한다(파일은 향후 브라우저 렌더링을
붙일 경우를 대비해 남겨둠).

## 2. "계속 상관없는 이미지만 뜬다" — 진짜 원인

Bing 결과를 실제로 뽑아 보니 상위가 이런 식이었다.

```
1. thatkrazykeith.blogspot.com   (개인 블로그)
2. alamy.com                     (워터마크 박힌 스톡사진)
3. vecteezy.com                  (스톡사진)
4. desertcart.ec                 (씨앗 5알 판매 상품 사진)
5. plants.ces.ncsu.edu           (제대로 된 식물 전문 사이트)
```

일반 이미지 검색은 **"검색어와 비슷해 보이는" 사진**을 줄 뿐이라, 학명이 정확해도
스톡사진·상품 사진·다른 식물이 섞인다. 정렬만 고쳐서 해결될 문제가 아니었다.

## 3. 해결: 학명으로 사진이 보장되는 소스를 1순위로

### iNaturalist API 도입 (`inaturalist_service.py`, 신규)

iNaturalist는 사진이 **분류군 ID(taxon id)에 직접 묶여 있고** 커뮤니티 검증을 거친다.
학명만 맞으면 **종이 틀린 사진이 나올 수 없다.** 무료, API 키 불필요.

- 1순위: `taxon_photos` — iNaturalist가 그 분류군 대표로 큐레이션한 사진
- 2순위: 연구등급(research grade) 관찰 사진 — 커뮤니티가 종 동정에 합의한 것
- 라이선스 코드(CC BY, CC BY-NC 등)를 한국어 문구로 변환해 출처에 함께 표기

한계: **품종(cultivar)은 구분하지 못한다.** 종 단위까지만 보장된다. → 아래 5번으로 보완.

### DuckDuckGo 이미지 검색 도입 (`duckduckgo_image_service.py`, 신규)

Google이 빠진 자리를 대신한다. vqd 토큰을 받은 뒤 JSON 엔드포인트를 호출하는 2단계 방식이고,
**원본 해상도(width/height)를 함께 주기 때문에** 아이콘·배너를 크기로 걸러낼 수 있다.
(Bing의 `iusc` JSON에는 `ow`/`oh` 키가 없어서 크기 필터가 동작하지 않았다.)

### 최종 우선순위

```
1순위: iNaturalist    — 종이 보장됨 (품종은 구분 못 함)
2순위: DuckDuckGo     — 품종명까지 반영된 웹 사진
3순위: Bing           — 위 둘로 부족할 때만 보강
※ Google, Wikimedia Commons는 사용하지 않음
```

## 4. 스톡사진·쇼핑몰 감점 (-55점)

워터마크가 박혀 있거나 씨앗 봉투·상품 사진이라 보고서에 쓸 수 없다.

`alamy` `shutterstock` `gettyimages` `istockphoto` `dreamstime` `123rf` `depositphotos`
`vecteezy` `freepik` `stock.adobe` `amazon` `ebay` `aliexpress` `etsy` `desertcart`
`walmart` `bigcommerce` `myshopify` `coupang` `11st` `gmarket` 등

## 5. 품종명 일치 가점 (+60점)

iNaturalist가 종 단위 사진을 워낙 강하게 밀어올려서, 품종이 지정된 경우
**품종 특성이 사진에 안 나오는 문제**가 생겼다.

> `Acer palmatum 'Bloodgood'`는 잎이 붉은 품종인데, 종 단위 `Acer palmatum` 사진은 녹색이다.

→ 제목·URL에 품종명이 실제로 들어 있는 후보에 가점을 줘서 종 단위 사진보다 위로 올린다.

## 6. 소스별 기준점 + 소스별 순위

점수를 전역 순위로 매기면 뒤에 붙은 소스가 부당하게 손해를 본다. 순위는 **소스 안에서** 센다.

```
relevance_score = 소스기준점 + 순위점수 + 텍스트가점 + 도메인조정 + 품종가점
  소스기준점  = iNaturalist 120/90(전체/근접), DuckDuckGo 80/85, Bing 70/75
                (근접사진에서 iNaturalist를 낮춘 이유: 꽃 클로즈업이라는 보장이 없음)
  순위점수    = max(0, 60 - 소스내순위*5)
  텍스트가점  = _score(...) * 2
  도메인조정  = _domain_priority()//10, 스톡/쇼핑몰이면 -55
  품종가점    = 품종명 일치 시 +60
```

## 검증 결과 (실제 API 호출)

### 품종이 지정된 경우 — 품종 사진이 상위

```
Acer palmatum 'Bloodgood' (전체사진)
  1. 268점 품종O [duckduckgo ] Acer Palmatum Bloodgood Japanese Maple
  2. 263점 품종O [duckduckgo ] Acer palmatum 'Bloodgood' ~ Japanese Maple
  3. 258점 품종O [duckduckgo ] Acer palmatum 'Bloodgood' - Boething Treeland
  4. 253점 품종O [duckduckgo ] Acer palmatum 'Bloodgood' - Blerick Tree Farm
  5. 233점 품종O [duckduckgo ] Acer palmatum 'Bloodgood' - Urban Jungle
  6. 230점       [inaturalist] Acer palmatum (종 단위)
```

### 품종이 없는 경우 — 검증된 iNaturalist 사진이 상위

```
Buxus sempervirens (전체사진)
  1~6위 전부 [inaturalist] Buxus sempervirens — 연구등급 검증 사진
```

### 근접사진 — 꽃 사진을 겨냥한 검색 결과가 상위

```
Hydrangea macrophylla 'Endless Summer' (근접사진)
  1. 231점 [duckduckgo ] kiefernursery.com
  2. 216점 [duckduckgo ] siteone.com
  3. 211점 [duckduckgo ] whiteflowerfarm.com
  4. 208점 [duckduckgo ] platthillnursery.com (Endless-Summer-Hydrangea-Closeup)
  → alamy, vecteezy, desertcart 등 스톡·쇼핑몰은 전부 하위로 밀림
```

## 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/services/inaturalist_service.py` (신규) | 학명 → 분류군 조회 → 큐레이션 사진 + 연구등급 관찰 사진. 라이선스 한국어 표기. |
| `backend/app/services/duckduckgo_image_service.py` (신규) | vqd 토큰 + JSON 엔드포인트 2단계 크롤링. 원본 해상도 제공. |
| `backend/app/services/plant_research_service.py` | 소스 체인 교체(Google 제외), 소스별 기준점·소스별 순위, 스톡/쇼핑몰 감점, 품종명 가점. `BUILD_VERSION` → `v24-inaturalist-duckduckgo-images`. |
| `backend/app/services/google_image_crawler.py` | 파이프라인에서 제외(파일은 유지). |

## 의존성

새 패키지 없음. 전부 표준 라이브러리(`urllib`, `json`)로 구현했다.

## 배포 후 확인할 로그

```
[inaturalist_service] name=... matched=... taxon_id=... photos=N
[duckduckgo_image_service] query=... raw=N candidates=N
[plant_research_service] role=... identity=... inat=N ddg=N total_raw=N scored=N top=[(소스, 점수, 제목), ...]
```

- `matched=`가 실제 품종의 학명과 같은지 → 다르면 학명 추출 단계 문제
- `top=`에 `inaturalist` 또는 품종명이 들어간 제목이 오는지

## 남은 과제

- 학명 추출 자체가 틀리면 여전히 엉뚱한 사진이 나온다. 위 로그 `identity=` / `matched=`로 확인.
- iNaturalist는 품종을 구분하지 못하므로, 품종 사진은 여전히 웹 검색 결과에 의존한다.
