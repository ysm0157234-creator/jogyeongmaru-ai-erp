# 조경마루 AI ERP v11.0 — Search First

## 핵심 변경

- Gemini Google Search Grounding 제거
- Google Custom Search가 웹자료와 사진을 직접 검색
- Gemini 호출은 검색결과 JSON 구조화 1회만 수행
- Gemini 429, 키 누락, 모델 오류가 발생해도 서비스 중단 없음
- Gemini 사용 불가 시 검색 결과 기반 안전 초안 자동 생성
- 확인되지 않은 꽃색·높이·개화기는 임의 작성하지 않고 확인 필요 표시
- Google Drive의 Shipment → 업체 → shipping document → Container → Invoice/Phyto 유지
- ZIP 안에 backend와 frontend가 바로 위치하여 Render Root Directory 문제 방지

## Render Root Directory

API:
`backend`

WEB:
`frontend`

## 필수 환경변수

- GOOGLE_SERVICE_ACCOUNT_JSON
- SHIPMENT_OVERVIEW_FILE_ID
- IMPORT_2025_FOLDER_ID
- GOOGLE_SEARCH_API_KEY
- GOOGLE_SEARCH_ENGINE_ID

## 선택 환경변수

- GEMINI_API_KEY
- GEMINI_MODEL

GEMINI_MODEL은 비워두는 것을 권장합니다.
Gemini 무료 할당량이 초과돼도 Google 검색 기반 초안으로 계속 진행됩니다.

## 배포 확인 문구

`v11.0-search-first`
