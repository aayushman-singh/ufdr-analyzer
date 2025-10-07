@echo off
echo ========================================
echo Starting UFDR Analyzer (Local Setup)
echo ========================================
echo.

echo Checking PostgreSQL...
pg_ctl status -D "%USERPROFILE%\postgres_data" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] PostgreSQL is already running
) else (
    echo [STARTING] PostgreSQL...
    pg_ctl -D "%USERPROFILE%\postgres_data" -l "%USERPROFILE%\postgres_data\logfile" start
    echo [OK] PostgreSQL started
    timeout /t 2 >nul
)

echo.
echo Testing PostgreSQL connection...
psql -h localhost -p 5432 -U ufdr_user -d ufdr_analyzer -c "SELECT 'Connection successful!' as status;" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] PostgreSQL connection successful
) else (
    echo [ERROR] PostgreSQL connection failed
    echo Please check your PostgreSQL configuration
    pause
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

