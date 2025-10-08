@echo off
echo ========================================
echo  Fixing Permissions for UFDR Analyzer
echo ========================================
echo.

echo This script fixes file permissions for the entire repository
echo so you can run ALEAPP without admin privileges.
echo.

echo Fixing permissions for Android extractions...
takeown /f "backend\UFDRConvert" /r /d y
icacls "backend\UFDRConvert" /grant Everyone:F /t

echo.
echo Fixing permissions for ALEAPP directory...
takeown /f "ALEAPP" /r /d y
icacls "ALEAPP" /grant Everyone:F /t

echo.
echo Fixing permissions for backend storage...
if exist "backend\storage" (
    takeown /f "backend\storage" /r /d y
    icacls "backend\storage" /grant Everyone:F /t
)

echo.
echo ========================================
echo  Permission Fix Complete!
echo ========================================
echo.
echo You can now run ALEAPP without admin privileges:
echo   cd ALEAPP
echo   python aleapp.py -t fs -i ../backend/UFDRConvert/android_13_image -o ../backend/storage/reports
echo.
