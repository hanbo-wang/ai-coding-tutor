@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Guided Cursor - Startup
cd /d "%~dp0"

set "SLEEP_SECONDS=2"
set "MAX_ATTEMPTS=60"
set "FRONTEND_MAX_ATTEMPTS=240"
set /a BACKEND_TIMEOUT_SECONDS=%MAX_ATTEMPTS%*%SLEEP_SECONDS%
set /a FRONTEND_TIMEOUT_SECONDS=%FRONTEND_MAX_ATTEMPTS%*%SLEEP_SECONDS%
set "DOCKER_CHECK_SECONDS=15"
set "DOCKER_CHECK_STEP=3"
set /a DOCKER_MAX_ATTEMPTS=%DOCKER_CHECK_SECONDS%/%DOCKER_CHECK_STEP%
set "VERIFY_MAX_ATTEMPTS=3"

:: Pick an available Docker Compose command.
set "COMPOSE_CMD="
docker compose version >nul 2>&1
if not errorlevel 1 (
    set "COMPOSE_CMD=docker compose"
)
if not defined COMPOSE_CMD (
    docker-compose version >nul 2>&1
    if not errorlevel 1 (
        set "COMPOSE_CMD=docker-compose"
    )
)
if not defined COMPOSE_CMD (
    echo.
    echo  ERROR: Docker Compose was not found.
    echo  Install Docker Desktop and make sure compose works in this terminal.
    pause
    exit /b 1
)

:: Fail fast when Docker engine is unreachable.
echo  [0/5] Checking Docker engine...
set "DOCKER_ATTEMPTS=0"
:docker_check_loop
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
set /a DOCKER_ATTEMPTS+=1
if !DOCKER_ATTEMPTS! geq %DOCKER_MAX_ATTEMPTS% (
    echo.
    echo  ERROR: Docker engine did not respond within %DOCKER_CHECK_SECONDS% seconds.
    echo  Docker diagnostics:
    docker version
    docker context ls
    cmd /c "%COMPOSE_CMD% ps"
    cmd /c "%COMPOSE_CMD% logs --tail 80 backend"
    cmd /c "%COMPOSE_CMD% logs --tail 80 db"
    pause
    exit /b 1
)
timeout /t %DOCKER_CHECK_STEP% /nobreak >nul
goto docker_check_loop

:docker_ready
echo.
echo  ============================================
echo   Guided Cursor: AI Coding Tutor
echo  ============================================
echo.

:: Start database and backend detached, then stream logs in a separate window.
echo  [1/5] Starting database and backend...
cmd /c "%COMPOSE_CMD% up --build -d db backend"
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to start database/backend containers.
    cmd /c "%COMPOSE_CMD% ps"
    echo.
    echo  Last backend logs:
    cmd /c "%COMPOSE_CMD% logs --tail 120 backend"
    echo.
    echo  Last database logs:
    cmd /c "%COMPOSE_CMD% logs --tail 120 db"
    pause
    exit /b 1
)
start "Guided Cursor - Backend Logs" cmd /k "%COMPOSE_CMD% logs -f backend db"

:: Wait for backend health endpoint.
echo  [2/5] Waiting for backend to be ready...
set ATTEMPTS=0

:health_loop
set /a ATTEMPTS+=1
if %ATTEMPTS% gtr %MAX_ATTEMPTS% (
    echo.
    echo  ERROR: Backend did not start within %BACKEND_TIMEOUT_SECONDS% seconds.
    echo  Backend status:
    cmd /c "%COMPOSE_CMD% ps"
    echo.
    echo  Last backend logs:
    cmd /c "%COMPOSE_CMD% logs --tail 120 backend"
    echo.
    echo  Last database logs:
    cmd /c "%COMPOSE_CMD% logs --tail 120 db"
    pause
    exit /b 1
)
timeout /t %SLEEP_SECONDS% /nobreak >nul
call :check_http_200 "http://localhost:8000/health"
if errorlevel 1 (
    <nul set /p "=."
    goto health_loop
)

echo.
echo  Backend is ready!
echo.

:: Verify provider connectivity through the backend health API.
echo  [3/5] Verifying LLM and embedding APIs...
set "VERIFY_ATTEMPT=0"
:verify_loop
set /a VERIFY_ATTEMPT+=1
call :check_ai_health
set "VERIFY_EXIT_CODE=!errorlevel!"
if !VERIFY_EXIT_CODE! equ 0 goto verify_ok
if !VERIFY_ATTEMPT! lss %VERIFY_MAX_ATTEMPTS% (
    echo  API verification did not pass ^(attempt !VERIFY_ATTEMPT!/%VERIFY_MAX_ATTEMPTS%^). Retrying...
    timeout /t 3 /nobreak >nul
    goto verify_loop
)
echo.
if !VERIFY_EXIT_CODE! equ 2 (
    echo  ERROR: No LLM API passed verification. Web app will not start.
) else (
    if !VERIFY_EXIT_CODE! equ 3 (
        echo  ERROR: Could not query /api/health/ai for API verification.
    ) else (
        echo  ERROR: API verification failed with exit code !VERIFY_EXIT_CODE!.
	)
)
echo  Backend status:
cmd /c "%COMPOSE_CMD% ps backend"
call :print_backend_exit_hint
echo  Last backend logs:
cmd /c "%COMPOSE_CMD% logs --tail 120 backend"
pause
exit /b 1
:verify_ok
echo  API verification passed.
echo.

:: Start frontend dev server.
echo  [4/5] Starting frontend...
start "Guided Cursor - Frontend" /d "%~dp0frontend" cmd /c "npm install && npm run dev"

:: Wait for Vite to serve HTTP 200.
echo  [5/5] Waiting for frontend to start...
set FATTEMPTS=0

:frontend_loop
set /a FATTEMPTS+=1
if %FATTEMPTS% gtr %FRONTEND_MAX_ATTEMPTS% (
    echo.
    echo  ERROR: Frontend did not start within %FRONTEND_TIMEOUT_SECONDS% seconds.
    echo  Check the Frontend window for errors.
    pause
    exit /b 1
)
timeout /t %SLEEP_SECONDS% /nobreak >nul
call :check_http_200 "http://localhost:5173"
if errorlevel 1 (
    <nul set /p "=."
    goto frontend_loop
)
echo.
echo  Frontend is ready!
start http://localhost:5173

echo.
echo  ============================================
echo   All services running!
echo  --------------------------------------------
echo   Frontend : http://localhost:5173
echo   Backend  : http://localhost:8000
echo  --------------------------------------------
echo   To stop: close the Backend and Frontend
echo            command windows.
echo   This startup window stays open for logs.
echo  ============================================
echo.
pause
exit /b 0

:check_http_200
set "URL=%~1"

:: Use curl if available, otherwise use PowerShell.
where curl >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '!URL!' -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    exit /b !errorlevel!
)

curl -s -o nul -w "%%{http_code}" "!URL!" | findstr "200" >nul 2>&1
exit /b !errorlevel!

:check_ai_health
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -UseBasicParsing -Uri 'http://localhost:8000/api/health/ai' -TimeoutSec 30; if ($r.anthropic -or $r.openai -or $r.google) { exit 0 } else { exit 2 } } catch { exit 3 }" >nul 2>&1
exit /b !errorlevel!

:print_backend_exit_hint
set "BACKEND_CONTAINER="
set "BACKEND_EXIT_CODE="
for /f %%i in ('cmd /c "%COMPOSE_CMD% ps -q backend"') do set "BACKEND_CONTAINER=%%i"
if not defined BACKEND_CONTAINER exit /b 0
for /f %%i in ('docker inspect -f "{{.State.ExitCode}}" !BACKEND_CONTAINER! 2^>nul') do set "BACKEND_EXIT_CODE=%%i"
if "!BACKEND_EXIT_CODE!"=="137" (
    echo  HINT: Backend container exit code 137 usually means it was killed due to low Docker memory.
    echo  HINT: Keep BACKEND_RELOAD=false in .env or increase Docker memory for Docker Desktop.
)
exit /b 0
