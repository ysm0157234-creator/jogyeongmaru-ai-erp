# v15.0 HWPX Complete - 배포

## GitHub Desktop
1. 이 ZIP의 내용 전체를 기존 `jogyeongmaru-ai-erp` 로컬 저장소에 덮어씁니다.
2. GitHub Desktop의 Changes에서 변경 파일을 확인합니다.
3. Commit summary: `Deploy v15 HWPX complete`
4. Commit to main → Push origin.

## Render 환경변수
백엔드 서비스에 아래 값을 확인합니다.
- GOOGLE_SERVICE_ACCOUNT_JSON
- SHIPMENT_OVERVIEW_FILE_ID
- IMPORT_2025_FOLDER_ID
- SERPER_API_KEY
- GEMINI_API_KEY
- GEMINI_MODEL (비워도 됨)

중요: 이전 `IMPORT_2026_FOLDER_ID`가 아니라 코드와 동일한 `IMPORT_2025_FOLDER_ID`를 사용합니다.

## 검증 결과
- backend Python compileall 통과
- HWPX 템플릿 실제 치환 및 사진 교체 테스트 통과
- frontend 소스는 기존 Vite 구성 유지
- 로컬 npm 검증은 작업 환경의 사설 npm 미러에 @vitejs/plugin-react가 없어 수행하지 못함
