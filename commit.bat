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
for /f %%i in ('git status --porcelain') do (
    git add -A
    git commit -m "%MSG%"
    git push origin main
    goto :shared_done
)
echo No changes - skipped
:shared_done

echo.
echo === services ===
cd /d "%~dp0"
for /f %%i in ('git status --porcelain') do (
    git add -A
    git commit -m "%MSG%"
    git push origin main
    goto :services_done
)
echo No changes - skipped
:services_done

echo.
echo Done
pause