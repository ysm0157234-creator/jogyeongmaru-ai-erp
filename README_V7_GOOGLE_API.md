# 조경마루 AI ERP v7.0 — Google 동적 품종 조사

## 변경 사항

Sunlover 고정 자료를 삭제했습니다.

입력한 품종마다 다음 흐름으로 새 자료를 만듭니다.

1. Google Programmable Search JSON API로 품종 웹자료 검색
2. Google 이미지 검색으로 전체 모습과 꽃 근접 사진 후보 검색
3. Gemini API가 검색 제목·요약·URL만 근거로 신고용 특성·육성과정 초안 작성
4. 사용자가 사진과 초안을 검토·수정
5. Google Drive에서 Shipment, Invoice, Phyto 검색
6. 최종 ZIP 생성

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

## Google Programmable Search 설정

- 검색엔진에서 전체 웹 검색을 허용합니다.
- Search Engine ID(cx)를 `GOOGLE_SEARCH_ENGINE_ID`에 넣습니다.
- Custom Search JSON API용 키를 `GOOGLE_SEARCH_API_KEY`에 넣습니다.
- 이미지 검색이 허용되도록 검색엔진 설정을 확인합니다.

## 주의

Google은 2026년 기준 Custom Search JSON API를 신규 고객에게 제공하지 않을 수 있습니다.
기존 사용자는 2027-01-01 전까지 대체 서비스로 전환해야 한다는 공식 안내가 있습니다.
계정에서 API 활성화가 안 되면 Vertex AI Search 또는 다른 검색 API로 교체해야 합니다.

사진은 검색 결과이므로 제출 전에 품종 일치와 저작권·이용 조건을 사람이 확인해야 합니다.
