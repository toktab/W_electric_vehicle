@echo off
setlocal enabledelayedexpansion

echo ================================================
echo   EV Charging System - Startup Script
echo ================================================
echo.

echo [92mStep 0: Stopping existing containers...[0m
docker-compose down
echo.

REM Step 1: Build all Docker images (one by one)
echo [92mStep 1: Building Docker images...[0m
echo.

echo    Building central...
docker-compose build central
if errorlevel 1 (
    echo [91mFailed to build central[0m
    pause
    exit /b 1
)

echo    Building registry...
docker-compose build registry
if errorlevel 1 (
    echo [91mFailed to build registry[0m
    pause
    exit /b 1
)

echo    Building driver...
docker-compose build driver_1
if errorlevel 1 (
    echo [91mFailed to build driver[0m
    pause
    exit /b 1
)

echo    Building weather...
docker-compose build weather
if errorlevel 1 (
    echo [91mFailed to build weather[0m
    pause
    exit /b 1
)

echo    Building front...
docker-compose build front
if errorlevel 1 (
    echo [91mFailed to build front[0m
    pause
    exit /b 1
)

echo    Building CP manager...
docker-compose build cp_manager
if errorlevel 1 (
    echo [91mFailed to build cp_manager[0m
    pause
    exit /b 1
)

echo.
echo [92mAll images built successfully![0m
echo.

REM Step 2: Start core infrastructure
echo [92mStep 2: Starting core infrastructure...[0m
echo.

docker-compose up -d
if errorlevel 1 (
    echo [91mFailed to start containers[0m
    pause
    exit /b 1
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
) else (
    echo [92mAll CPs auto-started![0m
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

echo ================================================
echo   System Started Successfully!
echo ================================================
echo.
echo [92mAccess Points:[0m
echo   Dashboard:  http://localhost:8081
echo   Central API: http://localhost:8080/api/status
echo   Registry:    http://localhost:5001/list
echo.
echo [92mUseful Commands:[0m
echo   docker-compose logs -f
echo   docker attach evcharging_cp_manager
echo   docker attach evcharging_driver_1
echo.
echo [92mTo stop: docker-compose down[0m
echo.
echo ================================================
echo   Press any key to view live logs...
echo ================================================
pause >nul

docker-compose logs -f

endlocal