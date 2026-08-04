# v10.1 모델명 형식 수정

오류 `GenerateContentRequest.model: unexpected model name format`를 수정했습니다.

- `models.list()`가 반환한 `models/gemini-...` 정식 이름을 그대로 사용
- `base_model_id`가 있는 SDK 버전도 지원
- Vertex 형식이나 URL 전체가 환경변수에 들어가도 안전한 Gemini ID만 추출
- 잘못된 모델명은 호출 전에 정규식으로 차단
- 400/404 모델 오류 발생 시 다음 사용 가능 모델 자동 시도

Render의 `GEMINI_MODEL`은 비워두는 것을 권장합니다.
