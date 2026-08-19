@echo off
chcp 65001 >nul
title 조경마루 국립종자원 신고 도우미 - 설치
cd /d "%~dp0.."

echo ============================================================
echo   국립종자원 신고 도우미 설치
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] 파이썬이 설치되어 있지 않습니다.
    echo.
    echo   https://www.python.org/downloads/ 에서 파이썬을 먼저 설치하세요.
    echo   설치할 때 "Add Python to PATH" 를 반드시 체크하세요.
    echo.
    pause
    exit /b 1
)

echo [1/3] 필요한 프로그램을 내려받는 중...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 goto fail

echo [2/3] 브라우저를 내려받는 중... (처음 한 번, 몇 분 걸립니다)
python -m playwright install chromium
if errorlevel 1 goto fail

echo [3/3] 바탕화면에 실행 아이콘을 만드는 중...
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\신고 도우미.lnk');" ^
  "$s.TargetPath='%~dp0도우미 켜기.bat'; $s.WorkingDirectory='%~dp0'; $s.Save()"

echo.
echo ============================================================
echo   설치가 끝났습니다.
echo   바탕화면의 [신고 도우미] 를 실행한 뒤 ERP에서 버튼을 누르세요.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [오류] 설치 중 문제가 발생했습니다. 위 메시지를 관리자에게 보여주세요.
pause
exit /b 1
