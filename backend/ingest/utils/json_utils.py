# backend/utils/json_utils.py
import json
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)


def save_json(data: dict, filepath: str) -> None:
    """
    Saves a dictionary to a JSON file.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info(f"JSON saved to {filepath}")


def load_json(filepath: str) -> dict:
    """
    Loads a JSON file and returns a dictionary.
    """
    path = Path(filepath)
    if not path.exists():
        logger.error(f"JSON file does not exist: {filepath}")
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info(f"JSON loaded from {filepath}")
    return data


def pretty_print_json(data: dict) -> None:
    """
    Prints JSON nicely for debugging.
    """
    print(json.dumps(data, indent=2, ensure_ascii=False))
