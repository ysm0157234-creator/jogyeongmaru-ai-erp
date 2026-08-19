"""국립종자원 종자민원서비스(seednet) 자동화 설정."""

from __future__ import annotations

from pathlib import Path

# 이 파일 위치 기준으로 automation 폴더를 잡는다. 어느 디렉터리에서 실행하든 동일하게 동작한다.
AUTOMATION_DIR = Path(__file__).resolve().parent.parent

BASE_URL = "https://www.seednet.go.kr"
LOGIN_URL = f"{BASE_URL}/member/login.do"

# 품종 생산·수입 판매 신고 목록. 여기서 '신규 신청'으로 들어간다.
REPORT_LIST_URL = f"{BASE_URL}/report/cvw/cvwAppMstList.do?appl_knd=30&appl_st_cd=30"

# 로그인 완료를 판정하는 신호. 로그인 후에는 로그아웃 링크가 나타난다.
LOGGED_IN_HINTS = ("로그아웃", "나의 민원")

# 사람이 로그인할 때까지 기다리는 시간(초). 인증서 로그인은 시간이 더 걸린다.
LOGIN_WAIT_SECONDS = 600

# 브라우저 세션을 저장해 두면 다음 실행 때 로그인을 건너뛸 수 있다.
STORAGE_STATE = AUTOMATION_DIR / ".seednet-session.json"

# 1단계 결과와 입력 매핑 파일
FORM_DUMP = AUTOMATION_DIR / "form_dump.json"
FIELD_MAP = AUTOMATION_DIR / "field_map.json"
