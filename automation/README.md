# 국립종자원 생산·수입판매 신고 자동입력

ERP가 만든 ZIP을 그대로 써서 [국립종자원 종자민원서비스](https://www.seednet.go.kr)의
품종 생산·수입판매 신고 화면을 자동으로 채운다. **신고(제출) 버튼은 누르지 않는다.**
내용을 확인한 뒤 사람이 직접 누른다.

## 자동화하지 않는 것 (의도적으로)

| | 이유 |
|---|---|
| **로그인** (아이디·비밀번호, 공동인증서) | 자격증명은 자동화가 대신 입력하지 않는다. 브라우저 창에서 직접 로그인한다. |
| **신고(제출) 버튼** | 되돌릴 수 없는 행정 행위다. 사람이 확인하고 누른다. |

로그인은 한 번 하면 세션이 `automation/.seednet-session.json`에 저장되어 다음 실행 때는 생략된다.
(이 파일에는 로그인 쿠키가 들어 있으므로 git에 올리지 않는다.)

## 설치

```bash
cd ~/Documents/GitHub/jogyeongmaru-ai-erp/automation
pip3 install -r requirements.txt
python3 -m playwright install chromium
```

> 아래 명령은 모두 **`automation` 폴더 안에서** 실행한다.
> (저장소 루트에서 실행하면 `No module named 'seednet'` 오류가 난다.)

## 1단계 — 신고 화면 구조 뽑기 (최초 1회)

신고 작성 폼은 로그인 안쪽이라 미리 볼 수 없다. 추측으로 선택자를 짜면 틀리므로
실제 화면 구조부터 뽑는다.

```bash
python3 -m seednet.dump_form
```

브라우저가 열리면 → 로그인 → 신청서 목록에서 **`신고서작성하기`** 클릭.

신고 화면은 여러 단계로 나뉘어 있을 수 있으므로, **화면이 바뀔 때마다** 터미널에서
Enter를 눌러 캡처한다. 다 끝나면 `q`를 입력한다.
`automation/form_dump.json`에 화면별 입력 항목이 저장된다.

## 2단계 — 입력 매핑 작성 (최초 1회)

`form_dump.json`을 보고 `automation/field_map.example.json`을 복사해
`automation/field_map.json`을 만든다. 각 항목의 `selector`를 실제 값으로 채운다.

화면이 바뀌면 1·2단계를 다시 하면 된다.

## 3단계 — 자동 입력 (매번)

```bash
python3 -m seednet.fill_report "~/Downloads/수국_ENDLESS_SUMMER_complete.zip"
```

- ZIP의 `manifest.json > report_fields`에서 신고 값을 읽는다
- 신고서 `.hwp`, 검역합격증명서, 인보이스를 첨부한다
- 채운 항목과 **직접 입력해야 하는 항목**을 터미널에 정리해 보여준다
- 브라우저를 열어둔 채 끝난다 → 확인 후 직접 신고 버튼을 누른다

## 주의

- 값이 비어 있는 항목은 건너뛰고 목록으로 알려준다. 특히 **검역합격 발급번호**는
  Drive에서 검역합격증을 못 찾으면 빈 값이 된다.
- 자동 입력 결과를 그대로 믿지 말고 제출 전에 화면을 확인한다.
