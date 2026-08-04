# 조경마루 AI ERP v10.0

## 핵심 변경

- 구형 `v1beta` 직접 HTTP 호출 제거
- Google 공식 `google-genai` Python SDK 적용
- `models.list()`로 현재 API 키에서 사용 가능한 모델 조회
- Render의 `GEMINI_MODEL`이 잘못되거나 폐기돼도 다른 사용 가능 모델 자동 시도
- Flash 계열 모델 우선 선택
- Gemini Google Search Grounding 최신 SDK 방식 적용
- 입력 품종별 동적 특성·육성과정 생성
- 입력 품종과 다른 결과 또는 Sunlover 잔여 데이터 차단
- Google 이미지/Wikimedia 후보를 입력 품종 핵심어로 검증
- WebP, PNG, AVIF 등을 JPEG로 정규화한 후 DOCX 삽입
- Shipment Overview H열 → 2025 수입 → 업체 → shipping document → container → Invoice/Phyto 흐름 유지

## Render 환경변수

```text
GOOGLE_SERVICE_ACCOUNT_JSON
SHIPMENT_OVERVIEW_FILE_ID
IMPORT_2025_FOLDER_ID
GOOGLE_SEARCH_API_KEY
GOOGLE_SEARCH_ENGINE_ID
GEMINI_API_KEY
GEMINI_MODEL
```

`GEMINI_MODEL`은 비워두는 것을 권장합니다. 비워두면 현재 API 키에서 사용할 수 있는 모델을 자동 선택합니다.
특정 모델을 쓰고 싶을 때만 AI Studio 또는 API 모델 목록에 실제로 표시되는 이름을 넣으세요.

## 배포 확인

사이트의 연결 상태 또는 AI 초안에 다음 버전이 보여야 합니다.

```text
v10.0-google-genai-auto-model
```

## 커밋 문구

```text
Upgrade to v10 Google GenAI auto model selection
```
