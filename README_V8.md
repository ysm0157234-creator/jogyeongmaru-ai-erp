# 조경마루 AI ERP v8.0

## 핵심 변경

- Sunlover 하드코딩 완전 제거
- 입력한 품종마다 Gemini Google Search Grounding으로 새 조사
- Google Custom Search 결과를 추가 근거로 사용
- Google 이미지 검색 + Wikimedia Commons 보조 사진 후보
- 전체 모습 / 꽃 근접 사진을 사람이 선택
- Shipment Overview의 같은 행 H열 Shipment 사용
- 2025 수입 → 업체_네덜란드 → shipping document → container 번호
- Invoice 및 Phyto 자동 선택
- 실제 오류를 사이트와 Render 로그에 표시

## Render API 환경변수

```text
GOOGLE_SERVICE_ACCOUNT_JSON
SHIPMENT_OVERVIEW_FILE_ID
IMPORT_2025_FOLDER_ID
GOOGLE_SEARCH_API_KEY
GOOGLE_SEARCH_ENGINE_ID
GEMINI_API_KEY
GEMINI_MODEL=gemini-2.5-flash
```

## 적용 순서

1. GitHub 저장소를 새 폴더에 Clone
2. ZIP 내용을 Clone 폴더에 덮어쓰기
3. `.git` 폴더는 유지
4. Commit: `Upgrade to v8 dynamic Google Gemini research`
5. Push origin
6. Render API와 WEB 배포 완료 확인
7. 브라우저 강력 새로고침

## 주의

- 사진은 검색 결과이므로 제출 전 품종 일치와 이용 조건을 확인해야 합니다.
- Shipment Overview에 입력 품종이 실제로 존재하고 H열 Shipment 값이 있어야 ZIP을 생성합니다.
