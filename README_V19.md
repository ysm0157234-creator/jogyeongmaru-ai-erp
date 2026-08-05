# v19.0 Background Research

- POST /api/ai-reports/generate는 초안 ID를 즉시 201로 반환합니다.
- Serper/Gemini/사진 조사는 FastAPI BackgroundTasks에서 실행합니다.
- 프론트엔드는 2초마다 GET /api/ai-reports/{draft_id}로 상태를 확인합니다.
- 조사 실패 시 상태가 `생성 실패`로 저장되고 오류 메시지를 화면에 표시합니다.
- Render 프록시가 긴 generate 요청을 502/timeout으로 끊는 문제를 방지합니다.
- Google Drive는 기존대로 2025 → 2024 → 2023 지정 폴더만 검사합니다.
