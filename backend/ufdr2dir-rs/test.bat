@echo off
REM Test script for ufdr2dir-rs (Windows)

echo Testing UFDR2DIR (Rust Edition)
echo.

REM Check if binary exists
if not exist "target\release\ufdr2dir.exe" (
    echo Binary not found. Building first...
    cargo build --release
)

REM Check if test file exists
set TEST_FILE=..\..\test_small.ufdr
if not exist "%TEST_FILE%" (
    echo Test file not found: %TEST_FILE%
    echo Please run create_small_ufdr.py first from the repo root
    exit /b 1
)

REM Clean previous test output
echo Cleaning previous test output...
if exist test_output rmdir /s /q test_output

REM Run extraction
echo.
echo Extracting test_small.ufdr...
echo.

target\release\ufdr2dir.exe "%TEST_FILE%" -o test_output --debug

REM Check results
if exist test_output (
    echo.
    echo Test successful!
    echo   Output directory: test_output\
    dir /s /b test_output\* | find /c "\" > nul
    
    if exist test_output\path_mapping.json (
        echo   Path mapping file created
    )
) else (
    echo.
    echo Test failed! Output directory not created
    exit /b 1
)

