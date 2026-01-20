@echo off
setlocal enabledelayedexpansion

set /p MSG="Commit message: "
if "%MSG%"=="" (
    echo Error: Commit message cannot be empty
    exit /b 1
)

echo.
echo === shared_libs ===
cd /d "%~dp0..\shared_libs"
git diff --quiet --cached && git diff --quiet || (
    git add -A
    git commit -m "%MSG%"
    git push origin main
) && echo No changes - skipped

echo.
echo === services ===
cd /d "%~dp0"
git diff --quiet --cached && git diff --quiet || (
    git add -A
    git commit -m "%MSG%"
    git push origin main
) && echo No changes - skipped

echo.
echo Done
pause