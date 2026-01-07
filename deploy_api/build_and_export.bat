@echo off
REM Build deploy-api Docker image and export as tar
REM Run from projects/ folder

echo Building deploy-api image...
docker build -f services/deploy_api/Dockerfile -t deploy-api:latest .

if %ERRORLEVEL% NEQ 0 (
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo Exporting to deploy-api.tar...
docker save deploy-api:latest -o deploy-api.tar

if %ERRORLEVEL% NEQ 0 (
    echo Export failed!
    pause
    exit /b 1
)

echo.
echo Done! Created deploy-api.tar
echo Size:
for %%A in (deploy-api.tar) do echo   %%~zA bytes (%%~zA / 1048576 MB approx)
pause
