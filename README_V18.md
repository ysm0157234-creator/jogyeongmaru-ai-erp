# v18.0 — 2023·2024·2025 수입 폴더 제한 검색

## 변경 사항

- Google Drive 전체 검색을 사용하지 않습니다.
- 아래 지정 폴더만 최신 연도부터 순서대로 검사합니다.
  1. `IMPORT_2025_FOLDER_ID`
  2. `IMPORT_2024_FOLDER_ID`
  3. `IMPORT_2023_FOLDER_ID`
- 각 연도 폴더 바로 아래의 업체 폴더만 검사합니다.
- 업체명은 공백, 밑줄, 대소문자, 국가명, BV/Ltd 등의 차이를 정규화하여 비교합니다.
- 업체를 찾은 연도는 최종 ZIP의 `manifest.json`에 `import_year_folder`로 기록됩니다.
- 세 폴더에 모두 없을 때만 오류를 반환합니다.

## Render 환경변수

```text
IMPORT_2025_FOLDER_ID
IMPORT_2024_FOLDER_ID
IMPORT_2023_FOLDER_ID
```

세 값은 각각 다른 Google Drive 폴더 ID여야 합니다.

## 버전 표시

`v18.0-three-import-folders`
