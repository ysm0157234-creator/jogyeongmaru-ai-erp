# v20.0 Modular Stable

- `workflow.py`는 전체 흐름만 담당합니다.
- Google Drive 자료 수집은 `drive_manager.py`로 분리했습니다.
- 사진 다운로드/변환/자리표시자는 `image_manager.py`로 분리했습니다.
- HWPX/DOCX/PDF 생성은 `document_manager.py`로 분리했습니다.
- ZIP과 manifest 생성은 `package_manager.py`로 분리했습니다.
- 누락됐던 `download_image()`와 이미지 JPEG 정규화 기능을 실제 구현했습니다.
- 2025 → 2024 → 2023 지정 폴더 검색만 유지합니다.
- 사진이나 Drive 첨부문서가 없어도 DOCX 초안과 ZIP 생성은 계속됩니다.

배포 후 버전: `v20.0-modular-stable`
