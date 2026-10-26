@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ==================================================
echo Discord Botを起動しています...
echo ※この黒い画面を開いたままにしておくと、Botがオンラインになります。
echo ==================================================
set PYTHONUNBUFFERED=1
.\.venv\Scripts\python -u main.py
pause

