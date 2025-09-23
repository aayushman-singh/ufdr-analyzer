import xmltodict
import json
import csv
from pathlib import Path
from typing import Dict, Any, List
from ingest.utils.logger import get_logger
from ingest.utils.ufdr2dir import extract_ufdr_to_directory, get_extracted_files_info

logger = get_logger(__name__)


class UFDRParser:
    @staticmethod
    def parse_file(file_path: str) -> Dict[str, Any]:
        file_path = Path(file_path)
        logger.info(f"Parsing UFDR file: {file_path}")

        if file_path.suffix.lower() == ".ufdr":
            # Handle UFDR files by extracting them first
            extracted_dir = extract_ufdr_to_directory(str(file_path))
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

        normalized_data = UFDRParser._normalize(raw_data, file_path.name)
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

        # Handle UFDR-specific data structure
        if "_extraction_info" in raw_data:
            # This is from a UFDR file extraction
            extracted_dir = raw_data["_extraction_info"]["extracted_dir"]
            files_info = raw_data["_extraction_info"]["files_info"]
            
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

        return {
            "ufdr_id": "placeholder-uuid",  # or extract from raw data
            "filename": filename,
            "messages": messages,
            "contacts": contacts,
            "calls": calls,
            "media": media
        }
