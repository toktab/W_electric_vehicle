@echo off
setlocal enabledelayedexpansion

echo ================================================
echo   EV Charging System - Startup Script
echo ================================================
echo.

echo [92mStep 0: Stopping existing containers...[0m
docker-compose down 2>nul
echo.

REM Step 1: Build all Docker images (with better error handling)
echo [92mStep 1: Building Docker images...[0m
echo.

REM Central
echo    Building central...
docker-compose build central --no-cache 2>nul
if errorlevel 1 (
    echo [93m   Warning: Build had issues, trying alternative method...[0m
    docker build -t evcharging-central -f Dockerfile.central . 2>nul
    if errorlevel 1 (
        echo [91m   Failed to build central[0m
        pause
        exit /b 1
    )
)
echo [92m   ✓ Central built[0m

REM Registry
echo    Building registry...
docker-compose build registry --no-cache 2>nul
if errorlevel 1 (
    echo [93m   Warning: Build had issues, trying alternative method...[0m
    docker build -t evcharging-registry -f Dockerfile.registry . 2>nul
    if errorlevel 1 (
        echo [91m   Failed to build registry[0m
        pause
        exit /b 1
    )
)
echo [92m   ✓ Registry built[0m

REM CP Image (CRITICAL for auto-start!)
echo    Building CP (for auto-start)...
docker build -t evcharging-cp -f Dockerfile.cp . 2>nul
if errorlevel 1 (
    echo [91m   Failed to build CP image - auto-start will fail![0m
    pause
    exit /b 1
)
echo [92m   ✓ CP image built[0m

REM Driver
echo    Building driver...
docker-compose build driver_1 --no-cache 2>nul
if errorlevel 1 (
    echo [93m   Warning: Build had issues, trying alternative method...[0m
    docker build -t evcharging-driver -f Dockerfile.driver . 2>nul
)
echo [92m   ✓ Driver built[0m

REM Weather
echo    Building weather...
docker-compose build weather --no-cache 2>nul
if errorlevel 1 (
    echo [93m   Warning: Build had issues, trying alternative method...[0m
    docker build -t evcharging-weather -f Dockerfile.weather . 2>nul
)
echo [92m   ✓ Weather built[0m

REM Front
echo    Building front...
docker-compose build front --no-cache 2>nul
if errorlevel 1 (
    echo [93m   Warning: Build had issues, trying alternative method...[0m
    docker build -t evcharging-front -f Dockerfile.front . 2>nul
)
echo [92m   ✓ Front built[0m

REM CP Manager
echo    Building CP manager...
docker-compose build cp_manager --no-cache 2>nul
if errorlevel 1 (
    echo [93m   Warning: Build had issues, trying alternative method...[0m
    docker build -t evcharging-manager -f Dockerfile.manager . 2>nul
)
echo [92m   ✓ CP Manager built[0m

echo.
echo [92mAll images built successfully![0m
echo.

REM Step 2: Start core infrastructure
echo [92mStep 2: Starting core infrastructure...[0m
echo.

docker-compose up -d 2>nul
if errorlevel 1 (
    echo [91mFailed to start containers[0m
    echo [93mTrying to restart Docker network...[0m
    docker network prune -f 2>nul
    timeout /t 3 /nobreak >nul
    docker-compose up -d 2>nul
    if errorlevel 1 (
        echo [91mStill failed. Check docker-compose.yml[0m
        pause
        exit /b 1
    )
)

echo.
echo [92mCore infrastructure started![0m
echo.

REM Step 3: Wait for Kafka and Central
echo [93mStep 3: Waiting for core services (30 seconds)...[0m
timeout /t 30 /nobreak >nul
echo.

REM Step 4: AUTO-START CPs
echo [92mStep 4: Auto-starting CPs from registry...[0m
echo.

python auto_start_cps.py
set CP_RESULT=!errorlevel!
echo.

if !CP_RESULT! neq 0 (
    echo [93mSome CPs failed to auto-start[0m
    echo [93mThis is OK if registry.txt is empty (no CPs created yet)[0m
    echo [93mYou can create CPs via CP Manager after startup[0m
) else (
    echo [92mAll CPs auto-started from registry![0m
)
echo.

REM Step 5: Wait for CPs
echo [93mStep 5: Waiting for CPs to connect (15 seconds)...[0m
timeout /t 15 /nobreak >nul
echo.

REM Step 6: Status
echo [92mStep 6: System Status[0m
echo.
docker ps --format "table {{.Names}}\t{{.Status}}" --filter "name=evcharging_"
echo.

REM Check if CP containers exist
set CP_COUNT=0
for /f %%i in ('docker ps --filter "name=evcharging_cp_" --format "{{.Names}}" 2^>nul ^| find /c /v ""') do set CP_COUNT=%%i

echo [92mCP Containers Running: %CP_COUNT%[0m
echo.

if %CP_COUNT% EQU 0 (
    echo [93m⚠️  No CP containers found![0m
    echo [93m   Either:[0m
    echo [93m   1. Registry.txt is empty (create CPs via CP Manager^)[0m
    echo [93m   2. Auto-start failed (check auto_start_cps.py output above^)[0m
    echo.
)

echo ================================================
echo   System Started Successfully!
echo ================================================
echo.
echo [92mAccess Points:[0m
echo   Dashboard:  http://localhost:8081
echo   Central API: http://localhost:8080/api/status
echo   Registry:    http://localhost:5001/list
echo   CP Manager:  docker attach evcharging_cp_manager
echo.
echo [92mQuick Test:[0m
echo   1. Open Dashboard: http://localhost:8081
echo   2. Should see auto-started CPs as ACTIVATED (green)
echo   3. If no CPs, open: docker attach evcharging_cp_manager
echo      Then create CPs from the menu
echo.
echo [92mUseful Commands:[0m
echo   docker-compose logs -f central (view Central logs)
echo   docker logs evcharging_cp_engine_1 (view CP logs)
echo   docker attach evcharging_cp_manager (create/delete CPs)
echo   docker attach evcharging_driver_1 (manual driver)
echo   docker ps (show all containers)
echo.
echo [92mTo stop: docker-compose down[0m
echo.
echo ================================================
echo   Current Status: %CP_COUNT% CP(s) running
echo ================================================
echo.

REM Keep showing logs and CMD open indefinitely
:show_logs
docker-compose logs -f
REM If logs exit, just loop again
goto show_logs