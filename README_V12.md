# 조경마루 AI ERP v12.0 — Serper Search

## 변경 사항

Google Custom Search JSON API는 신규 프로젝트 접근이 거부될 수 있어 완전히 제거했습니다.

v12 검색 흐름:

1. Serper API로 웹 검색
2. Serper API로 이미지 검색
3. Gemini가 사용 가능하면 검색 결과를 한 번만 구조화
4. Gemini 오류·할당량 초과 시 Serper 검색결과 기반 안전 초안
5. Google Drive에서 Shipment, Invoice, Phyto 검색
6. 신고용 문서와 ZIP 생성

## Render 필수 환경변수

- GOOGLE_SERVICE_ACCOUNT_JSON
- SHIPMENT_OVERVIEW_FILE_ID
- IMPORT_2025_FOLDER_ID
- SERPER_API_KEY

## 선택 환경변수

- GEMINI_API_KEY
- GEMINI_MODEL

`GOOGLE_SEARCH_API_KEY`와 `GOOGLE_SEARCH_ENGINE_ID`는 v12에서 사용하지 않습니다.

## Serper API 키 발급

1. serper.dev 가입
2. Dashboard 또는 API Key 메뉴에서 키 복사
3. Render API 서비스 Environment에 등록

Key:
SERPER_API_KEY

Value:
Serper에서 발급한 실제 키

## Render 설정

API Root Directory:
backend

WEB Root Directory:
frontend

## 배포 확인 문구

v12.0-serper
