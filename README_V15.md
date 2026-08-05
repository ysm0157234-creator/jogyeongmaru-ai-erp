# 조경마루 AI ERP v15.0 HWPX Complete

## 연결된 전체 흐름

1. Serper 웹·이미지 검색
2. Gemini가 풀 학명, 꽃색, 개화기, 초장, 특성 설명, 육성과정 생성
3. Google Drive Shipment Overview에서 품종 및 Shipment 검색
4. 2025 수입 폴더에서 공급사 / shipping document / container 검색
5. Invoice 및 Phyto 자동 수집
6. 기존 일본매자나무 신고서 HWPX 양식에 내용과 사진 자동 반영
7. 신고서 HWPX, 검역서류, Invoice, 사진, 요약 PDF를 ZIP으로 생성

## 필수 Render 환경변수

- GOOGLE_SERVICE_ACCOUNT_JSON
- SHIPMENT_OVERVIEW_FILE_ID
- IMPORT_2025_FOLDER_ID
- SERPER_API_KEY
- GEMINI_API_KEY

선택:
- GEMINI_MODEL (비워두면 사용 가능한 모델 자동 선택)

## Render 설정

API Root Directory: backend
WEB Root Directory: frontend

## 배포 확인

화면에 `v16.0-single-gemini-fallback`가 표시되어야 합니다.
