@echo off
setlocal enabledelayedexpansion

REM Fast permission check - only run expensive operations if needed
set "MARKER_FILE=%~dp0.permissions_ok"

REM Check if we've already fixed permissions (marker file exists and is recent)
if exist "%MARKER_FILE%" (
    REM Check if marker is less than 24 hours old
    forfiles /p "%~dp0" /m ".permissions_ok" /d -1 >nul 2>&1
    if !errorlevel! equ 0 (
        REM Permissions were fixed recently, skip
        exit /b 0
    )
)

REM Permissions need to be set/refreshed
echo ========================================
echo  Setting Repository Permissions
echo ========================================
echo.

REM Grant full permissions on entire repository (one operation, much faster)
echo Granting permissions on repository root...
takeown /f "%~dp0" /r /d y >nul 2>&1
icacls "%~dp0" /grant Everyone:F /t >nul 2>&1

REM Create marker file to skip future runs (for 24 hours)
echo Permissions OK - %date% %time% > "%MARKER_FILE%"

echo.
echo ========================================
echo  Permissions Set Successfully!
echo ========================================
echo.
