import xmltodict
import json
import csv
import os
import subprocess
import platform
from pathlib import Path
from typing import Dict, Any, List
from ingest.utils.logger import get_logger
from ingest.utils.ufdr2dir import extract_ufdr_to_directory, get_extracted_files_info

logger = get_logger(__name__)


class UFDRParser:
    @staticmethod
    def parse_file(file_path: str, output_dir: str = None) -> Dict[str, Any]:
        file_path = Path(file_path)
        logger.info(f"Parsing UFDR file: {file_path}")

        if file_path.suffix.lower() == ".ufdr":
            # Handle UFDR files by extracting them first
            extracted_dir = extract_ufdr_to_directory(str(file_path), output_dir)
            logger.info(f"UFDR extracted to: {extracted_dir}")
            
            # Look for report.xml in the extracted directory
            report_xml_path = Path(extracted_dir) / "report.xml"
            if report_xml_path.exists():
                raw_data = UFDRParser._parse_xml(report_xml_path)
                # Add extraction info to the data
                raw_data["_extraction_info"] = {
                    "extracted_dir": extracted_dir,
                    "files_info": get_extracted_files_info(extracted_dir)
                }
            else:
                logger.error("No report.xml found in extracted UFDR")
                raise ValueError("Invalid UFDR file - no report.xml found")
                
        elif file_path.suffix.lower() == ".xml":
            raw_data = UFDRParser._parse_xml(file_path)
        elif file_path.suffix.lower() == ".json":
            raw_data = UFDRParser._parse_json(file_path)
        elif file_path.suffix.lower() == ".csv":
            raw_data = UFDRParser._parse_csv(file_path)
        else:
            logger.error(f"Unsupported UFDR file type: {file_path.suffix}")
            raise ValueError("Unsupported UFDR file type")

        # Extract file slug for consistent naming
        file_slug = Path(output_dir).name if output_dir else file_path.stem.lower().replace(' ', '_')

        normalized_data = UFDRParser._normalize(raw_data, file_path.name)

        # Run ALEAPP if we have android extraction
        if "_extraction_info" in raw_data:
            extracted_dir = raw_data["_extraction_info"]["extracted_dir"]
            aleapp_output = UFDRParser._run_aleapp(extracted_dir, file_slug)
            if aleapp_output:
                normalized_data["aleapp_data"] = aleapp_output

        return normalized_data

    @staticmethod
    def _parse_xml(file_path: Path) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            return xmltodict.parse(f.read())

    @staticmethod
    def _parse_json(file_path: Path) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _parse_csv(file_path: Path) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return {"csv_rows": list(reader)}

    @staticmethod
    def _normalize(raw_data: Dict[str, Any], filename: str) -> Dict[str, Any]:
        """
        Normalizes raw UFDR data into a consistent, structured format.
        Handles both standard XML/JSON/CSV files and UFDR-specific data.
        """
        messages: List[Dict[str, Any]] = []
        contacts: List[Dict[str, Any]] = []
        calls: List[Dict[str, Any]] = []
        media: List[Dict[str, Any]] = []

        # Store extraction info for later use
        extraction_info = None
        if "_extraction_info" in raw_data:
            extraction_info = raw_data["_extraction_info"]
            # This is from a UFDR file extraction
            extracted_dir = extraction_info["extracted_dir"]
            files_info = extraction_info["files_info"]

            # Add media files from the extraction
            for file_info in files_info["files"]:
                file_path = Path(extracted_dir) / file_info["path"]
                if file_path.exists():
                    # Determine media type based on extension
                    media_type = "unknown"
                    if file_info["extension"] in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"]:
                        media_type = "image"
                    elif file_info["extension"] in [".mp4", ".avi", ".mov", ".wmv", ".flv"]:
                        media_type = "video"
                    elif file_info["extension"] in [".mp3", ".wav", ".aac", ".m4a", ".ogg"]:
                        media_type = "audio"
                    elif file_info["extension"] in [".pdf", ".doc", ".docx", ".txt", ".rtf"]:
                        media_type = "document"

                    media.append({
                        "file_path": str(file_path),
                        "original_path": file_info["path"],
                        "type": media_type,
                        "size": file_info["size"],
                        "extension": file_info["extension"]
                    })

            # Remove extraction info from raw_data for XML parsing
            raw_data = {k: v for k, v in raw_data.items() if k != "_extraction_info"}

        # Parse XML structure for UFDR report.xml
        if "report" in raw_data:
            report_data = raw_data["report"]
            
            # Extract messages from UFDR XML structure
            if "messages" in report_data:
                messages_data = report_data["messages"]
                if isinstance(messages_data, dict) and "message" in messages_data:
                    msg_list = messages_data["message"]
                    if not isinstance(msg_list, list):
                        msg_list = [msg_list]
                    
                    for msg in msg_list:
                        messages.append({
                            "content": msg.get("content", ""),
                            "sender": msg.get("from", ""),
                            "receiver": msg.get("to", ""),
                            "timestamp": msg.get("timestamp", ""),
                        })
            
            # Extract contacts from UFDR XML structure
            if "contacts" in report_data:
                contacts_data = report_data["contacts"]
                if isinstance(contacts_data, dict) and "contact" in contacts_data:
                    contact_list = contacts_data["contact"]
                    if not isinstance(contact_list, list):
                        contact_list = [contact_list]
                    
                    for contact in contact_list:
                        contacts.append({
                            "name": contact.get("name", ""),
                            "number": contact.get("number", ""),
                        })
            
            # Extract calls from UFDR XML structure
            if "calls" in report_data:
                calls_data = report_data["calls"]
                if isinstance(calls_data, dict) and "call" in calls_data:
                    call_list = calls_data["call"]
                    if not isinstance(call_list, list):
                        call_list = [call_list]
                    
                    for call in call_list:
                        calls.append({
                            "caller": call.get("caller", ""),
                            "receiver": call.get("receiver", ""),
                            "timestamp": call.get("timestamp", ""),
                            "duration": call.get("duration", ""),
                        })

        # Fallback for generic XML/JSON/CSV structures
        if "ufdr" in raw_data and "messages" in raw_data["ufdr"]:
            for msg in raw_data["ufdr"]["messages"].get("message", []):
                messages.append({
                    "content": msg.get("content", ""),
                    "sender": msg.get("from", ""),
                    "receiver": msg.get("to", ""),
                    "timestamp": msg.get("timestamp", ""),
                })

        # Handle CSV data
        if "csv_rows" in raw_data:
            for row in raw_data["csv_rows"]:
                # Assuming the CSV is for messages
                if "from" in row and "content" in row:
                    messages.append({
                        "content": row.get("content"),
                        "sender": row.get("from"),
                        "receiver": row.get("to"),
                        "timestamp": row.get("timestamp"),
                    })

        # Build final normalized data
        normalized_data = {
            "ufdr_id": "placeholder-uuid",  # or extract from raw data
            "filename": filename,
            "messages": messages,
            "contacts": contacts,
            "calls": calls,
            "media": media
        }

        # Re-add extraction info to normalized data for later use
        if extraction_info:
            normalized_data["_extraction_info"] = extraction_info

        return normalized_data

    @staticmethod
    def _get_files_info_from_cache(cache_dir: str) -> dict:
        """Get file info from cached extraction directory"""
        try:
            from ingest.utils.ufdr2dir import get_extracted_files_info
            return get_extracted_files_info(cache_dir)
        except Exception as e:
            logger.warning(f"Could not get files info from cache: {e}")
            return {"total_files": 0, "file_types": {}, "directories": [], "files": []}

    @staticmethod
    def _run_os_specific_utils():
        """Run OS-specific utility scripts before ALEAPP"""
        try:
            current_os = platform.system().lower()
            # Navigate to project root from backend/ingest/services/parser_service.py
            current_file = Path(__file__)  # backend/ingest/services/parser_service.py
            backend_dir = current_file.parent.parent.parent  # backend/
            root_dir = backend_dir.parent  # project root

            if current_os == "windows":
                util_script = root_dir / "fix_repo_permissions.bat"
                if util_script.exists():
                    logger.info("Running Windows permission fix script...")
                    subprocess.run([str(util_script)], shell=True, check=True, cwd=str(root_dir))
            else:
                util_script = root_dir / "fix_repo_permissions.sh"
                if util_script.exists():
                    logger.info("Running Unix permission fix script...")
                    subprocess.run(["bash", str(util_script)], check=True, cwd=str(root_dir))

            logger.info("OS-specific utils completed successfully")
        except Exception as e:
            logger.warning(f"Failed to run OS-specific utils: {e}")

    @staticmethod
    def _run_aleapp(android_extraction_path: str, file_slug: str = None) -> Dict[str, Any]:
        """Run ALEAPP on Android extraction and return parsed output"""
        try:
            logger.info(f"Starting ALEAPP analysis on: {android_extraction_path}")

            # Run OS-specific utils first
            UFDRParser._run_os_specific_utils()

            # Setup paths - navigate to project root from backend/ingest/services/parser_service.py
            current_file = Path(__file__)  # backend/ingest/services/parser_service.py
            backend_dir = current_file.parent.parent.parent  # backend/
            root_dir = backend_dir.parent  # project root
            aleapp_dir = root_dir / "ALEAPP"
            aleapp_script = aleapp_dir / "aleapp.py"

            # Create output directory for ALEAPP with consistent slug naming
            if file_slug:
                # Use slug-based naming in ALEAPP/output/ directory
                aleapp_output_base = aleapp_dir / "output" / file_slug
                aleapp_output_base.mkdir(parents=True, exist_ok=True)
                output_dir = aleapp_output_base
            else:
                # Fallback to old method if no slug provided
                output_dir = Path(android_extraction_path).parent / "aleapp_output"
                output_dir.mkdir(exist_ok=True)

            if not aleapp_script.exists():
                logger.error(f"ALEAPP script not found at: {aleapp_script}")
                return None

            # Run ALEAPP command
            cmd = [
                "python",
                str(aleapp_script),
                "-t", "fs",
                "-i", str(android_extraction_path),
                "-o", str(output_dir)
            ]

            logger.info(f"Running ALEAPP command: {' '.join(cmd)}")

            # Change to ALEAPP directory before running
            result = subprocess.run(
                cmd,
                cwd=str(aleapp_dir),
                capture_output=True,
                text=True,
                timeout=1800  # 30 minute timeout
            )

            if result.returncode != 0:
                logger.error(f"ALEAPP failed with return code {result.returncode}")
                logger.error(f"ALEAPP stderr: {result.stderr}")
                return None

            logger.info("ALEAPP completed successfully")
            logger.info(f"ALEAPP stdout: {result.stdout}")

            # Parse ALEAPP output
            return UFDRParser._parse_aleapp_output(str(output_dir))

        except subprocess.TimeoutExpired:
            logger.error("ALEAPP timed out after 30 minutes")
            return None
        except Exception as e:
            logger.error(f"Failed to run ALEAPP: {e}")
            return None

    @staticmethod
    def _parse_aleapp_output(aleapp_output_dir: str) -> Dict[str, Any]:
        """Parse ALEAPP output directory and extract relevant data"""
        try:
            output_path = Path(aleapp_output_dir)

            # Look for common ALEAPP output files
            aleapp_data = {
                "output_directory": str(output_path),
                "artifacts": [],
                "reports": [],
                "timeline": []
            }

            # Parse HTML reports if they exist
            html_reports = list(output_path.glob("*.html"))
            for html_file in html_reports:
                aleapp_data["reports"].append({
                    "type": "html",
                    "filename": html_file.name,
                    "path": str(html_file)
                })

            # Parse CSV artifacts
            csv_files = list(output_path.rglob("*.csv"))
            for csv_file in csv_files:
                try:
                    with open(csv_file, 'r', encoding='utf-8', errors='ignore') as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                        if rows:  # Only include non-empty CSV files
                            aleapp_data["artifacts"].append({
                                "type": "csv",
                                "filename": csv_file.name,
                                "path": str(csv_file),
                                "category": csv_file.parent.name,
                                "row_count": len(rows),
                                "sample_data": rows[:5]  # First 5 rows as sample
                            })
                except Exception as csv_error:
                    logger.warning(f"Failed to parse CSV {csv_file}: {csv_error}")

            # Parse JSON files if they exist
            json_files = list(output_path.rglob("*.json"))
            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                        aleapp_data["artifacts"].append({
                            "type": "json",
                            "filename": json_file.name,
                            "path": str(json_file),
                            "category": json_file.parent.name,
                            "data": json_data
                        })
                except Exception as json_error:
                    logger.warning(f"Failed to parse JSON {json_file}: {json_error}")

            # Look for timeline data
            timeline_files = list(output_path.glob("*timeline*"))
            for timeline_file in timeline_files:
                aleapp_data["timeline"].append({
                    "filename": timeline_file.name,
                    "path": str(timeline_file)
                })

            logger.info(f"Parsed ALEAPP output: {len(aleapp_data['artifacts'])} artifacts, {len(aleapp_data['reports'])} reports")

            return aleapp_data

        except Exception as e:
            logger.error(f"Failed to parse ALEAPP output: {e}")
            return None
