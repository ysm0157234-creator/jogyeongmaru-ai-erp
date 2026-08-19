"""터미널에서 신고 자동 입력을 실행한다.

    python3 -m seednet.fill_report "<ERP가 만든 ZIP 경로>"

[종자원 접수요청] 버튼은 누르지 않는다. 확인 후 사람이 직접 누른다.
"""

from __future__ import annotations

import sys

from seednet.runner import run


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    result = run(sys.argv[1], interactive=True)

    print("\n" + "=" * 66)
    print(f"  {result['variety']}")
    print(f"  자동 처리 {len(result['done'])}건")
    for line in result["done"]:
        print("   +", line)
    print(f"\n  직접 처리할 항목 {len(result['todo'])}건")
    for line in result["todo"]:
        print("   !", line)
    print("=" * 66)
    print("\n  브라우저는 열어두었습니다. 확인 후 [종자원 접수요청]을 눌러 주세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
