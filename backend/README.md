# CiteSpan Backend

This is the backend API for CiteSpan. It analyzes UFDR (Universal Forensic Data Report) evidence.

## Project Structure

```
backend/
├── main.py                 # Main FastAPI application entry point
├── server.py               # Development server startup script (recommended)
├── config.py              # Application configuration
├── database.py             # Database connection and session management
├── db_setup.py             # Database models and schema
├── requirements.txt        # Python dependencies
├── ingest/                 # Core ingestion functionality
│   ├── routers/           # API route handlers
│   │   ├── health.py      # Health check endpoints
│   │   ├── upload.py      # File upload endpoints
│   │   └── report.py      # Report generation endpoints
│   ├── services/          # Business logic services
│   │   ├── ingest_service.py    # Data ingestion service
│   │   ├── parser_service.py    # UFDR file parsing
│   │   ├── report_service.py    # PDF report generation
│   │   └── storage_service.py   # File storage management
│   ├── utils/             # Utility functions
│   │   ├── logger.py      # Logging configuration
│   │   ├── file_utils.py  # File handling utilities
│   │   ├── json_utils.py  # JSON processing utilities
│   │   └── pdf_utils.py   # PDF processing utilities
│   └── tests/             # Test files
└── storage/               # File storage directories
    ├── json/              # JSON file storage
    ├── reports/           # Generated PDF reports
    └── tmp/               # Temporary file storage
```

## Setup

1. **Activate Virtual Environment**:
   ```bash
   # From project root
   source venv/Scripts/activate  # Windows
   # or
   source venv/bin/activate      # Linux/Mac
   ```

2. **Install Dependencies**:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. **Run the Backend**:
   ```bash
   # Option 1: Direct Python execution
   python main.py
   
   # Option 2: Development server with auto-reload (recommended)
   python server.py
   ```

## Development Server

The `server.py` script provides a development server with:
- ✅ **Auto-reload**: Automatically restarts when code changes
- ✅ **Hot reloading**: No need to manually restart the server
- ✅ **Development logging**: Detailed logs for debugging
- ✅ **Port 8000**: Server runs on http://127.0.0.1:8000

### Usage:
```bash
cd backend
python server.py
```

The server will start and watch for file changes. Press `Ctrl+C` to stop.

## API Endpoints

- `GET /` - Root endpoint with application status
- `GET /health/` - Health check endpoint
- `POST /upload/` - Upload UFDR files for processing
- `POST /report/generate` - Generate PDF reports
- `GET /report/download/{filename}` - Download generated reports

## Configuration

The application uses environment variables for configuration:

- `DATABASE_URL` - Database connection string (default: SQLite `sqlite:///./database.db`)
- `MEILI_URL` - Meilisearch server URL (default: http://localhost:7700)
- `MEILI_KEY` - Meilisearch API key (optional)

### Database Options:
- **SQLite** (default): No setup required, works out of the box
- **PostgreSQL**: Set `DATABASE_URL=postgresql://user:password@localhost:5432/dbname`

## Troubleshooting

### Common Issues:

1. **Module Import Errors**: Make sure you're running from the `backend/` directory
2. **Database Connection Errors**: The app uses SQLite by default (no setup required)
3. **Meilisearch Connection**: The app will work even if Meilisearch is not running
4. **Port Already in Use**: Change the port in `server.py` if 8000 is occupied

### Quick Test:
```bash
# Test if the server is running
curl http://127.0.0.1:8000/
# Should return: {"message": "CiteSpan is running!"}
```

## Dependencies

- FastAPI - Web framework
- SQLModel - Database ORM
- Meilisearch - Search engine
- MinIO - Object storage
- ReportLab - PDF generation
- Uvicorn - ASGI server
