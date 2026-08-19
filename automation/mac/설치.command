#!/bin/bash
cd "$(dirname "$0")/.."
echo "============================================================"
echo "  국립종자원 신고 도우미 설치"
echo "============================================================"
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -r requirements.txt || { echo "[오류] 설치 실패"; read -n1; exit 1; }
echo "브라우저를 내려받는 중... (처음 한 번, 몇 분 걸립니다)"
python3 -m playwright install chromium || { echo "[오류] 브라우저 설치 실패"; read -n1; exit 1; }
echo ""
echo "설치가 끝났습니다. [도우미 켜기] 를 실행하세요."
read -n1 -p "아무 키나 누르면 닫힙니다."
