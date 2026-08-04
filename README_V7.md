# 조경마루 AI ERP v7.0 — 모든 품종 허용

## 핵심 변경

- `Tulipa spp. Sunlover` 전용 제한 제거
- 입력한 모든 품종명 허용
- `Tulipa` 고정 보조검색 제거
- Shipment Overview에서 입력 품종 검색
- 검색 성공 시 H열 Shipment → 2025 수입 → 업체 폴더 → shipping document → container
- Shipment Overview에 없으면 입력 품종명, 속명, 종명, 품종명 후보로 2025 수입 인보이스 검색
- `IMPORT_2025_FOLDER_ID`만 사용

## 주의

사진 후보는 아직 Sunlover 예시 사진이 기본으로 남아 있습니다.
다른 품종 시험 시 초안과 사진을 최종 확인해야 합니다.

## Render 환경변수

GOOGLE_SERVICE_ACCOUNT_JSON
SHIPMENT_OVERVIEW_FILE_ID
IMPORT_2025_FOLDER_ID
