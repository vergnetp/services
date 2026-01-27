@echo off
REM ================================
REM Dev startup script (Windows)
REM ================================
REM
REM Structure:
REM   Projects/
REM   ├── shared_libs/
REM   │   └── backend/
REM   │       ├── infra/
REM   │       └── app_kernel/
REM   └── services/
REM       ├── launch.bat     (this file)
REM       ├── deploy_api/
REM       └── ai_agents/
REM
REM Usage:
REM   1. Double-click: Launches ai_agents
REM   2. Drag manifest onto this: Launches that service
REM
REM Imports work because we run from Projects/:
REM   from shared_libs.backend.app_kernel import ...
REM   from shared_libs.backend.infra.deploy import ...
REM ================================

echo.
echo ================================
echo Agent Service Launcher (DEV)
echo ================================
echo.

REM ---- SET PATHS ----
REM services/ folder (where this script lives)
set "SERVICES_DIR=%~dp0"
if "%SERVICES_DIR:~-1%"=="\" set "SERVICES_DIR=%SERVICES_DIR:~0,-1%"

REM Projects/ folder (parent of services/ - this is our PYTHONPATH root)
for %%i in ("%SERVICES_DIR%") do set "PROJECTS_ROOT=%%~dpi"
if "%PROJECTS_ROOT:~-1%"=="\" set "PROJECTS_ROOT=%PROJECTS_ROOT:~0,-1%"

REM ---- DETECT SERVICE ----
set "SERVICE_NAME=deploy_api"

if "%~1" NEQ "" (
    echo Manifest provided: %~1
    if /i "%~nx1"=="manifest.yaml" (
        for %%i in ("%~dp1.") do set "SERVICE_NAME=%%~ni"
    ) else (
        for /f "tokens=1 delims=." %%a in ("%~n1") do set "SERVICE_NAME=%%a"
    )
)

echo Manifest provided: %PROJECTS_ROOT%\services\%SERVICE_NAME%\manifest.yaml
echo Service: %SERVICE_NAME%
echo Shared libs: %PROJECTS_ROOT%\shared_libs
echo.

REM ---- ENV VARS ----



set "JWT_SECRET=dev-secret-change-in-prod"
set "PYTHONUNBUFFERED=1"

echo REDIS_URL=%REDIS_URL%
echo.

REM ---- START REDIS (Docker) ----
echo Checking Redis...

REM docker ps --filter "name=redis" --format "{{.Names}}" 2>nul | findstr redis >nul
REM if %ERRORLEVEL% NEQ 0 (
REM     docker ps -a --filter "name=redis" --format "{{.Names}}" 2>nul | findstr redis >nul
REM     if %ERRORLEVEL% EQU 0 (
REM         docker start redis
REM     ) else (
REM         docker run -d --name redis -p 6379:6379 redis:7
REM     )
REM ) else (
REM     echo Redis running.
REM )

REM echo.
REM timeout /t 2 >nul

REM ---- START API ----
echo Starting API...
start "%SERVICE_NAME%_api" cmd /k "cd /d %PROJECTS_ROOT% && python -m uvicorn services.%SERVICE_NAME%.main:app --reload --host 0.0.0.0 --port 8000"

timeout /t 2 >nul

REM ---- START WORKER ----
echo Starting Worker...
echo start "%SERVICE_NAME%_worker" cmd /k "cd /d %PROJECTS_ROOT% && python -m services.%SERVICE_NAME%.worker"

echo.
echo ================================
echo Started: %SERVICE_NAME%
echo ================================
echo API:   http://localhost:8000
echo Docs:  http://localhost:8000/docs
echo.

pause
