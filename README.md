# 조경마루 AI ERP v3.0 통합본

# 조경마루 AI ERP v2.0 - Drive·Invoice 자동화

React + FastAPI + PostgreSQL 기반의 조경마루 업무관리 시스템입니다.

## v0.2.1 기능

- 토스 스타일 UI 개편
- JWT 로그인
- 대시보드
- 생산·판매 신고 등록
- 신고 내역 조회
- 신고 수정 및 삭제
- 기관/구분/상태별 필터
- PostgreSQL 저장
- Render 자동 배포
- 이후 메뉴 확장이 가능한 사이드바 구조

## 기본 관리자 계정

Render 환경변수에서 아래 값을 설정합니다.

- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`

설정하지 않으면 개발용 기본값이 사용됩니다.

- 이메일: `admin@jogyeongmaru.co.kr`
- 비밀번호: `ChangeMe123!`

배포 후 반드시 비밀번호를 변경하세요.

## 프로젝트 구조

```text
backend/      FastAPI API 서버
frontend/     React + Vite 웹 화면
automation/   향후 국립종자원/산림청 자동화 모듈
render.yaml   Render 웹서비스/DB 배포 설정
```

## GitHub 업로드

압축을 푼 뒤 모든 파일을 `jogyeongmaru-ai-erp` 저장소 폴더에 복사하고
GitHub Desktop에서 Commit → Push 합니다.

## Render 배포

1. Render 대시보드에서 New → Blueprint
2. `jogyeongmaru-ai-erp` 저장소 연결
3. Blueprint Path는 `render.yaml`
4. Apply
5. 배포 후 프론트엔드 서비스의 `VITE_API_URL` 값이 백엔드 주소로 연결됩니다.

## 로컬 개발

### 백엔드

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

### 프론트엔드

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## v0.2.1 변경사항

- 전체 UI를 토스 스타일로 개편
- 로그인 화면 전면 개편
- 대시보드 카드 디자인 개선
- 신고 목록 검색/필터 UX 개선
- 신고 등록을 3단계 입력 방식으로 변경
- 로딩/오류 상태 추가
- passlib/bcrypt 제거
- pwdlib + Argon2 비밀번호 해시 적용


## v0.2.1 긴급 수정

- 흰 화면 문제 대응
- React 18.3.1 안정 버전 고정
- React Router 6.28.1 안정 버전 고정
- Vite React 플러그인 및 설정 파일 추가
- 중첩 라우팅 구조를 Outlet 방식으로 수정
- 화면 오류 표시용 ErrorBoundary 추가
- Render Node.js 버전 고정


## v1.2 Sunlover AI 신고

- `Tulipa spp. Sunlover` 품종명 입력 지원
- AI 신고 생성 화면 추가
- Google Drive 완료사례 및 관련 수입자료 링크 표시
- RHS·공급사 기반 품종 특성 자동 작성
- Wikimedia Commons 사진 후보 2장 표시 및 선택
- 품종의 특성 설명/육성과정 초안 자동 생성
- 필요한 첨부서류와 확인사항 표시
- AI 신고 초안을 PostgreSQL에 저장
- 다음 단계: Google Drive API 실시간 검색 및 정부 사이트 자동입력


## v2.0 실제 파일 자동생성 흐름

1. `Tulipa spp. Sunlover` 입력
2. 지정된 Shipment Overview XLSX에서 품종 행 검색
3. 오른쪽 `Shipment` 열에서 컨테이너/선적 번호 추출
4. `무역서류/2026 수입` 폴더를 하위 폴더까지 검색
5. 같은 Shipment 번호의 Invoice 후보 검색
6. XLSX Invoice이면 해당 품종 행만 남긴 신고용 사본 생성
7. PDF Invoice이면 품종명이 들어간 페이지를 추출
8. 직접 수정이 불가능하면 Shipment Overview 기반 인보이스 발췌 XLSX 생성
9. 오렌지썬라이즈 검토안 항목을 기준으로 신고서 검토안 DOCX 생성
10. 처리요약 PDF, manifest.json과 함께 ZIP 다운로드

### Render 필수 환경변수

`jogyeongmaru-ai-erp-api → Environment`에 다음을 추가합니다.

- `GOOGLE_SERVICE_ACCOUNT_JSON`: Google Cloud 서비스 계정 JSON 전체
- `SHIPMENT_OVERVIEW_FILE_ID`: 기본값 포함
- `IMPORT_2026_FOLDER_ID`: 기본값 포함

서비스 계정 이메일에 아래 파일/폴더를 **뷰어 권한으로 공유**해야 합니다.

- Shipment Overview 파일
- `2026 수입` 폴더

### HWP 관련

Render는 Linux 서버이므로 한컴 HWP 파일을 완전하게 직접 편집하는 기능은 안정적으로 제공되지 않습니다.
v2.0은 업로드한 검토안의 항목과 구성에 맞춘 DOCX와 PDF를 생성합니다.
HWP 원본 자동편집이 반드시 필요하면 Windows PC 또는 Windows 서버에 한컴오피스 자동화 모듈을 연결하는 별도 단계가 필요합니다.


## v2.2 빠른 Google Drive 검색

- 2026 수입 폴더 전체 재귀 순회·전체 다운로드 제거
- Google Drive `fullText`와 파일명 검색으로 후보를 먼저 제한
- Shipment 번호가 포함된 Invoice 후보만 다운로드
- 최대 후보 검사 수 제한
- ERP 화면에 경과시간 표시
- 120초 시간초과 처리

## v2.3
- 초안 수정 및 DB 저장
- 전체 모습 사진 1장, 꽃 근접 사진 1장 분리 선택
- 선택 사진 DOCX 삽입 및 ZIP 포함
- ZIP 생성 시 저장된 최종 초안 사용


## v3.0 확정 업무 흐름

### Shipment Overview에 품종이 있는 경우
1. Shipment Overview 전체 시트에서 품종 검색
2. 검색된 행의 H열 값을 Shipment 식별값으로 사용
3. `IMPORT_2026_FOLDER_ID` 바로 아래에서 동일·유사 이름의 폴더 검색
4. 해당 폴더 안의 Invoice 파일 사용
5. 해당 품종 행만 남기는 신고용 인보이스 생성

### Shipment Overview에 품종이 없는 경우
1. `2026수입` 하위 폴더를 제한적으로 검색
2. 내용에 `Tulipa`가 포함된 아무 Invoice를 양식으로 사용
3. 신고용 인보이스 발췌본 생성

### 신고 초안과 사진
- 초안 수정 및 DB 저장
- 전체 모습 1장 + 꽃 근접 1장 분리 선택
- 저장한 초안 내용을 DOCX에 반영
- 사진을 DOCX와 ZIP에 포함

## 충돌 없이 적용하는 권장 방법

기존 폴더 위에서 Pull과 덮어쓰기를 반복하지 말고:

1. GitHub Desktop에서 현재 충돌 창의 `Abort Merge` 선택
2. 이 ZIP을 새 폴더에 압축 해제
3. 기존 프로젝트의 `.git` 폴더만 새 폴더로 복사
4. GitHub Desktop에서 새 폴더를 Repository로 선택
5. 모든 변경을 한 번에 Commit 후 Push

환경변수는 기존 Render 값을 그대로 유지합니다.
