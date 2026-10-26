@echo off
cd /d "%~dp0"
echo ==================================================
echo [Word Filter Bot] Pushing to GitHub...
echo If a browser window opens, please sign in to GitHub.
echo ==================================================
git push -u origin main
echo.
echo ==================================================
echo Finished!
echo ==================================================
pause
