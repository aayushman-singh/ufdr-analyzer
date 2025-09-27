#!/bin/bash

echo "========================================"
echo "  Fixing Permissions for UFDR Analyzer"
echo "========================================"
echo

echo "This script fixes file permissions for the entire repository"
echo "so you can run ALEAPP without admin privileges."
echo

echo "Fixing permissions for Android extractions..."
chmod -R 755 backend/UFDRConvert
chown -R $USER:$USER backend/UFDRConvert

echo
echo "Fixing permissions for ALEAPP directory..."
chmod -R 755 ALEAPP
chown -R $USER:$USER ALEAPP

echo
echo "Fixing permissions for backend storage..."
if [ -d "backend/storage" ]; then
    chmod -R 755 backend/storage
    chown -R $USER:$USER backend/storage
fi

echo
echo "========================================"
echo "  Permission Fix Complete!"
echo "========================================"
echo
echo "You can now run ALEAPP without admin privileges:"
echo "  cd ALEAPP"
echo "  python aleapp.py -t fs -i ../backend/UFDRConvert/android_13_image -o ../backend/storage/reports"
echo
