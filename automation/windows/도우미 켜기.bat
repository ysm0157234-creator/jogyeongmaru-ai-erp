@echo off
chcp 65001 >nul
title 국립종자원 신고 도우미 - 켜짐 (이 창을 닫지 마세요)
cd /d "%~dp0.."
python -m seednet.local_server
pause
