# 조경마루 AI ERP v5.0

Google Drive 설정 오류까지 반영한 전체 통합본입니다.

## Render API 환경변수

아래 세 항목을 모두 등록해야 합니다.

```text
GOOGLE_SERVICE_ACCOUNT_JSON
SHIPMENT_OVERVIEW_FILE_ID
IMPORT_2026_FOLDER_ID
```

`GOOGLE_SERVICE_ACCOUNT_JSON`에는 내려받은 서비스계정 JSON 파일 내용을 통째로 붙여 넣습니다.

## 적용 순서

1. 기존 Merge가 진행 중이면 GitHub Desktop에서 `Abort Merge`
2. 저장소를 새 폴더에 Clone
3. 이 압축파일 내부 내용을 새 Clone 폴더에 덮어쓰기
4. 새 Clone 폴더의 `.git`은 그대로 유지
5. Commit: `Replace project with v5 drive-fixed build`
6. Push origin
7. Render API와 WEB 배포 완료 확인
8. 브라우저 강력 새로고침

## 정상 생성 파일

```text
01_생산수입판매신고서_검토안.docx
02_품종특성설명.docx
03_품종육성과정.docx
04_시료제출확약서.docx
05_검역합격증
06_신고용_invoice
07_품종전체사진.jpg
08_꽃근접사진.jpg
09_처리요약.pdf
manifest.json
```
