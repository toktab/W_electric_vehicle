@echo off
setlocal enabledelayedexpansion

echo ================================================
echo   EV Charging System - START
echo ================================================
echo.

set /p REBUILD="Rebuild images? (y/N): "
if /i "%REBUILD%"=="" set REBUILD=n

echo.
echo Stopping old containers...
docker-compose down
echo.

if /i "%REBUILD%"=="y" (
    echo Building images...
    docker-compose build
    docker build -t evcharging-cp -f Dockerfile.cp .
    echo.
)

echo Starting containers...
docker-compose up -d
if errorlevel 1 (
    echo ERROR: Failed to start!
    echo Checking logs...
    docker-compose logs --tail=50
    pause
    exit /b 1
)

echo.
echo Waiting 25 seconds for services to initialize...
timeout /t 25 /nobreak

echo.
echo Auto-starting CPs...
python auto_start_cps.py

echo.
echo Waiting 10 seconds for CPs...
timeout /t 10 /nobreak

echo.
echo ================================================
echo   System Status
echo ================================================
docker ps --format "table {{.Names}}\t{{.Status}}" --filter "name=evcharging_"

echo.
echo ================================================
echo   Ready! http://localhost:8081
echo ================================================
echo.
pause