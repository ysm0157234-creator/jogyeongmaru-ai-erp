# 조경마루 AI ERP v17.1

## 변경 사항

- Serper 일반 웹검색은 유지합니다.
- Serper `/images` API는 호출하지 않습니다.
- 무료 계정에서 거부될 수 있는 따옴표 기반 고급 검색 패턴을 제거했습니다.
- Gemini는 품종 조사당 최대 1회만 호출합니다.
- Gemini는 학명, 꽃색, 개화기, 초장, 번역·요약, 특성 설명, 육성과정을 한 번에 작성합니다.
- 사진은 다음 경로로 수집합니다.
  - Wikimedia Commons API
  - Serper 일반 웹검색으로 찾은 공식 페이지
  - `og:image`
  - Twitter image
  - JSON-LD `image`
  - HTML `img`, lazy-load 이미지
- 전체 모습과 근접 모습 후보를 별도로 점수화합니다.
- 로고, 아이콘, 배너, 작은 이미지, 중복 URL을 제외합니다.
- HWPX 및 Google Drive Invoice/Phyto 처리 구조는 유지합니다.

## 배포 확인 버전

`v17.2-commons-closeup-fallback`

## 필수 환경변수

- GOOGLE_SERVICE_ACCOUNT_JSON
- SHIPMENT_OVERVIEW_FILE_ID
- IMPORT_2025_FOLDER_ID
- SERPER_API_KEY

## 권장 환경변수

- GEMINI_API_KEY
- GEMINI_MODEL

Gemini 할당량 초과 시 Serper 검색결과 기반 자동 초안으로 계속 진행합니다.


## v17.1 수정
- 업체 폴더명 퍼지 매칭
- 학명 제목 문자열 제거 및 풀 학명 정제
- 크롤링 제거
- Wikimedia Commons에서 정제 학명과 정확히 일치하는 사진만 표시
