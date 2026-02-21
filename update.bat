@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Guided Cursor - Update
cd /d "%~dp0"

echo.
echo ============================================
echo  Guided Cursor: Update Project
echo ============================================
echo.

:: Pick an available Docker Compose command.
set "COMPOSE_CMD="
docker compose version >nul 2>&1
if not errorlevel 1 set "COMPOSE_CMD=docker compose"
if not defined COMPOSE_CMD (
    docker-compose version >nul 2>&1
    if not errorlevel 1 set "COMPOSE_CMD=docker-compose"
)
if not defined COMPOSE_CMD (
    echo ERROR: Docker Compose not found.
    pause
    exit /b 1
)

:: Update local code to latest commit on current branch.
echo [1/5] Updating source code...
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo ERROR: This folder is not a Git repository.
    pause
    exit /b 1
)
git fetch --all --prune
if errorlevel 1 (
    echo ERROR: git fetch failed.
    pause
    exit /b 1
)
git pull --ff-only
if errorlevel 1 (
    echo ERROR: git pull failed. Resolve conflicts first.
    pause
    exit /b 1
)

:: Rebuild database from scratch (destructive: clears DB volume).
echo [2/5] Rebuilding database from scratch...
cmd /c "%COMPOSE_CMD% down -v"
if errorlevel 1 (
    echo ERROR: Failed to stop and remove existing containers/volumes.
    pause
    exit /b 1
)

:: Start fresh db + backend after rebuild.
echo [3/5] Starting backend and database...
cmd /c "%COMPOSE_CMD% up -d --build db backend"
if errorlevel 1 (
    echo ERROR: Failed to start rebuilt db/backend services.
    pause
    exit /b 1
)

:: Install/update frontend dependencies.
echo [4/5] Updating frontend dependencies...
pushd "%~dp0frontend" >nul
npm install
if errorlevel 1 (
    popd >nul
    echo ERROR: npm install failed.
    pause
    exit /b 1
)
popd >nul

:: Print quick status.
echo [5/5] Current service status:
cmd /c "%COMPOSE_CMD% ps"
echo.
echo Update completed successfully.
echo You can now run start.bat to launch the app.
echo.
pause
exit /b 0
