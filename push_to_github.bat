@echo off
cd /d "%~dp0"
echo ==================================================
echo [Word Filter Bot] Saving changes...
echo ==================================================
git add .
git commit -m "Update bot files" > nul 2>&1

echo.
echo ==================================================
echo [Word Filter Bot] Pushing to GitHub...
echo If a browser window opens, please sign in to GitHub.
echo ==================================================
git push -u origin main

echo.
echo ==================================================
echo [Word Filter Bot] Completed!
echo ==================================================
pause
