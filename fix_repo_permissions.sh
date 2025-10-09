#!/bin/bash

# Fast permission check - only run expensive operations if needed
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKER_FILE="$SCRIPT_DIR/.permissions_ok"

# Check if we've already fixed permissions (marker file exists and is recent - less than 24 hours old)
if [ -f "$MARKER_FILE" ]; then
    # Check if marker is less than 24 hours old
    if [ $(find "$MARKER_FILE" -mtime -1 2>/dev/null | wc -l) -gt 0 ]; then
        # Permissions were fixed recently, skip
        exit 0
    fi
fi

# Permissions need to be set/refreshed
echo "========================================"
echo "  Setting Repository Permissions"
echo "========================================"
echo

# Grant permissions on entire repository (one operation, much faster)
echo "Granting permissions on repository root..."
chmod -R 755 "$SCRIPT_DIR" 2>/dev/null
chown -R $USER:$USER "$SCRIPT_DIR" 2>/dev/null

# Create marker file to skip future runs (for 24 hours)
echo "Permissions OK - $(date)" > "$MARKER_FILE"

echo
echo "========================================"
echo "  Permissions Set Successfully!"
echo "========================================"
echo
