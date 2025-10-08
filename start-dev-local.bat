@echo off
echo ========================================
echo Starting UFDR Analyzer (Local Setup)
echo ========================================
echo.

echo Checking PostgreSQL installation...
where pg_ctl >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PostgreSQL not found in PATH
    echo Please install PostgreSQL or use Docker setup instead.
    echo See DEVELOPMENT.md for instructions.
    echo.
    pause
    exit /b 1
)

echo Checking if PostgreSQL data directory exists...
if not exist "%USERPROFILE%\postgres_data" (
    echo [ERROR] PostgreSQL not initialized
    echo.
    echo Please initialize PostgreSQL first:
    echo   initdb -D "%USERPROFILE%\postgres_data"
    echo.
    echo Or use Docker setup instead:
    echo   ./start-dev-services.bat
    echo.
    pause
    exit /b 1
)

echo Checking PostgreSQL status...
pg_ctl status -D "%USERPROFILE%\postgres_data" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] PostgreSQL is already running
) else (
    echo [STARTING] PostgreSQL...
    pg_ctl -D "%USERPROFILE%\postgres_data" -l "%USERPROFILE%\postgres_data\logfile" start
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to start PostgreSQL
        echo Check the log file: %USERPROFILE%\postgres_data\logfile
        echo.
        pause
        exit /b 1
    )
    echo [OK] PostgreSQL started
    timeout /t 3 >nul
)

echo.
echo Testing PostgreSQL connection...
psql -h localhost -p 5432 -U ufdr_user -d ufdr_analyzer -c "SELECT 'Connection successful!' as status;" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] PostgreSQL connection successful
) else (
    echo [ERROR] PostgreSQL connection failed
    echo Please check your PostgreSQL configuration
    echo See DEVELOPMENT.md for setup instructions
    exit /b 1
)

echo.
echo ========================================
echo Development Environment Ready!
echo ========================================
echo PostgreSQL: localhost:5432
echo   - Database: ufdr_analyzer
echo   - User: ufdr_user
echo   - Password: ufdr_password
echo.
echo Starting backend server...
echo Press Ctrl+C to stop
echo.
cd backend
python server.py

