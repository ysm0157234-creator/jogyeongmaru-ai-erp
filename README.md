# 조경마루 AI ERP v1.2 - Sunlover AI 신고

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
