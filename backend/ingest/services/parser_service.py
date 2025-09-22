import xmltodict
import json
import csv
from pathlib import Path
from typing import Dict, Any, List
from utils.logger import get_logger

logger = get_logger(__name__)


class UFDRParser:
    @staticmethod
    def parse_file(file_path: str) -> Dict[str, Any]:
        file_path = Path(file_path)
        logger.info(f"Parsing UFDR file: {file_path}")

        if file_path.suffix.lower() == ".xml":
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
        This is a placeholder and needs real-world logic.
        """
        messages: List[Dict[str, Any]] = []
        contacts: List[Dict[str, Any]] = []
        calls: List[Dict[str, Any]] = []
        media: List[Dict[str, Any]] = []

        # Example normalization logic for a generic XML/JSON structure
        if "ufdr" in raw_data and "messages" in raw_data["ufdr"]:
            for msg in raw_data["ufdr"]["messages"].get("message", []):
                messages.append({
                    "content": msg.get("content", ""),
                    "sender": msg.get("from", ""),
                    "receiver": msg.get("to", ""),
                    "timestamp": msg.get("timestamp", ""),
                })

        # Example for CSV data
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

        # TODO: Add logic for contacts, calls, and media based on UFDR spec

        return {
            "ufdr_id": "placeholder-uuid",  # or extract from raw data
            "filename": filename,
            "messages": messages,
            "contacts": contacts,
            "calls": calls,
            "media": media
        }
