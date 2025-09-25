#!/usr/bin/env python3
"""
Backend startup script for UFDR Analyzer
"""
import uvicorn
from main import app

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
        # Configure for large uploads (30GB+)
        limit_max_requests=1000,
        timeout_keep_alive=30,
        limit_concurrency=10
    )
