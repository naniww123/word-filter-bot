@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ==================================================
echo [Word Filter Bot] 変更を保存してGitHubへ送信中...
echo ==================================================

git add .
git commit -m "Update bot features and settings"

echo.
echo ==================================================
echo [Word Filter Bot] Pushing to GitHub...
echo If a browser window opens, please sign in to GitHub.
echo ==================================================
git push -u origin main
echo.
echo ==================================================
echo アップロード完了！ Render等の自動デプロイをお待ちください。
echo ==================================================
pause

