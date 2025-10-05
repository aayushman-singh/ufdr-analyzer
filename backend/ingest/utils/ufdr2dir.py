# -*- coding: utf-8 -*-

"""
Convert a Cellebrite Reader UFDR file to it's original directory structure.
MIT License.
"""

# Imports
import argparse
import logging
import re, io, os
import signal
import platform
import shutil
import hashlib
import json

from pathlib import Path
from pathlib import PurePath
from zipfile import ZipFile

__software__ = 'UFDR2DIR'
__author__ = 'Joshua James'
__copyright__ = 'Copyright 2022, UFDR2DIR'
__credits__ = []
__license__ = 'MIT'
__version__ = '0.1.10'
__maintainer__ = 'Joshua James'
__email__ = 'joshua+github@dfirscience.org'
__status__ = 'active'

PROGRESSLIB = True

# Windows MAX_PATH limit - being conservative to account for full path
MAX_PATH_LENGTH = 240
PATH_MAPPING_FILE = "path_mapping.json"
path_mapping = {}

# Some users had trouble importing alive_progress on Windows
try:from alive_progress import alive_it
except ImportError:
    print('[E] Could not find alive_progress library. Will not show progress.')
    PROGRESSLIB = False

# Set logging level and format
def setLogging(debug):
    fmt = "[%(levelname)s] %(asctime)s %(message)s"
    LOGLEVEL = logging.INFO if debug is False else logging.DEBUG
    logging.basicConfig(level=LOGLEVEL, format=fmt, datefmt='%Y-%M-%dT%H:%M:%S')

# Argparser config and argument setup
def setArgs():
    parser = argparse.ArgumentParser(description=__copyright__)
    parser.add_argument('ufdr', help="Celebrite Reader UFDR file")
    parser.add_argument('-o', '--out', required=False, action='store', dest="out", help='Output directory path')
    parser.add_argument('--debug', required=False, action='store_true', help='Set the log level to DEBUG')
    return(parser.parse_args())

def getZipReportXML(ufdr, OUTD):
    logging.info("Extracting report.xml...")
    with ZipFile(ufdr, 'r') as zip:
        # First, extract report.xml to the output directory
        report_xml_path = Path(OUTD) / "report.xml"
        with open(report_xml_path, 'wb') as report_file:
            report_file.write(zip.read("report.xml"))
        logging.info(f"report.xml extracted to: {report_xml_path}")

        # Now process the report.xml for directory structure extraction
        with io.TextIOWrapper(zip.open("report.xml"), encoding="utf-8") as f:
            logging.info("Creating original directory structure...")
            if PROGRESSLIB: extractProgress(zip, OUTD, f)
            else: extractNoProgress(zip, OUTD, f)

# Function to show progress if lib exists
# Optimize with progress functions instead of alive_it
def extractProgress(zip, OUTD, f):
    ORIGF = ""
    LOCALF = ""
    for l in alive_it(f): # Run though each line... is lxml faster?
        if l.__contains__('<file fs'):
            result = re.search('path="(.*?)" ', l) # This gets original path / FN
            if result:
                ORIGF = result.group(1)
                if platform.system() == "Windows": ORIGF = re.sub('[:*?"<>|]', '-', ORIGF)
                # Apply safe path shortening
                ORIGF, _ = safe_path(ORIGF, OUTD)
                logging.debug(f'Original: {ORIGF}')
                # Create the original file directory structure
                makeDirStructure(ORIGF, OUTD)
        elif l.__contains__('name="Local Path"'):
            result = re.search('CDATA\[(.*?)\]\]', l) # This gets local path / FN
            if result:
                LOCALF = result.group(1).replace("\\", "/")
                logging.debug(f'Local: {LOCALF}')
                extractToDir(zip, LOCALF, ORIGF, OUTD)

def extractNoProgress(zip, OUTD, f):
    ORIGF = ""
    LOCALF = ""
    for l in f: # Run though each line... is lxml faster?
        if l.__contains__('<file fs'):
            result = re.search('path="(.*?)" ', l) # This gets original path / FN
            if result:
                ORIGF = result.group(1)
                if platform.system() == "Windows": ORIGF = re.sub('[:*?"<>|]', '-', ORIGF)
                # Apply safe path shortening
                ORIGF, _ = safe_path(ORIGF, OUTD)
                logging.debug(f'Original: {ORIGF}')
                # Create the original file directory structure
                makeDirStructure(ORIGF, OUTD)
        elif l.__contains__('name="Local Path"'):
            result = re.search('CDATA\[(.*?)\]\]', l) # This gets local path / FN
            if result:
                LOCALF = result.group(1).replace("\\", "/")
                logging.debug(f'Local: {LOCALF}')
                extractToDir(zip, LOCALF, ORIGF, OUTD)
    Path('files').rename(f'{OUTD}/UFDR-Files') # Move remaining archive structure to output
    # Save path mapping at the end
    save_path_mapping(OUTD)

def extractToDir(zip, LOCALP, ORIGP, OUTD):
    if ORIGP[:1] == "/": # Sometimes the first slash is missing in report.xml
        ORIGP = ORIGP[1:len(ORIGP)]
    #OUTPATH = PurePath(Path(OUTD), Path(ORIGP).parent)
    OUTPATH = PurePath(Path(OUTD), Path(ORIGP))
    logging.debug(f'Extracting {LOCALP} to {OUTPATH}')
    try:
        zip.extract(LOCALP)
    except KeyError as e:
        logging.debug(e)
    except NotADirectoryError as e:
        logging.debug(f'Error writing to directory: {e}')
    except PermissionError as e:
        print(f'Cannot write to the out directory. Check permissions: {e}')
        exit(0)
    except FileNotFoundError as e:
        # Path too long error manifests as FileNotFoundError on Windows
        logging.warning(f'Path too long error during extraction: {e}')
        logging.warning(f'This should have been prevented by safe_path(). Please check the implementation.')
    except:
        logging.debug(f'General error extracting file to path.')
    else:
        try:
            Path(LOCALP).rename(OUTPATH) # Move from CWD to original path + FN
        except IsADirectoryError: # If an archive is found but the dir already exists
            logging.debug('An original archive was found. Renaming the directory...')
            Path(OUTPATH).rename(f'{OUTPATH}.extract')
            Path(LOCALP).rename(OUTPATH)
        except NotADirectoryError: # If an archive file already exists and extraction is found
            logging.debug('Archive extraction found but archive already exists. Skipping...')
        except FileExistsError:
            logging.debug('File already exists. Skipping...')
        except OSError as e:
            # This catches the Windows ERROR_PATH_TOO_LONG (206)
            if 'too long' in str(e).lower() or e.winerror == 206:
                logging.error(f'Path length error: {OUTPATH}')
                logging.error(f'Length: {len(str(OUTPATH))} chars')
            else:
                logging.debug(f'Error writing file: {e}')

# This might not be necessary if we can extract directly.                    
def makeDirStructure(FP, OUTD): # FP is a string
    OUTPATH = PurePath(Path(OUTD), Path(FP[1:len(FP)]).parent)
    logging.debug(f'Outpath set to: {OUTPATH}')
    try:
        Path(OUTPATH).mkdir(parents=True, exist_ok=True)
    except NotADirectoryError as e:
        logging.debug(f'Error creating directory: {e}')
    except PermissionError as e:
        print(f'Cannot write to the out directory. Check permissions: {e}')
        exit(1)
    except FileExistsError:
        logging.debug(f"The file {OUTPATH} already exists. Skipping...")
    #except:
    #    logging.debug(f'General error creating file path.')

def shorten_path_component(component: str, max_length: int = 80) -> str:
    """
    Shorten a path component if it exceeds max_length.
    Uses first chars + hash to maintain uniqueness and some readability.
    """
    if len(component) <= max_length:
        return component

    # Take first part of the name to keep it readable, then add hash
    hash_suffix = hashlib.md5(component.encode('utf-8')).hexdigest()[:8]
    prefix_length = max_length - len(hash_suffix) - 1  # -1 for underscore
    prefix = component[:prefix_length]
    shortened = f"{prefix}_{hash_suffix}"

    logging.debug(f"Shortened path component: {component} -> {shortened}")
    return shortened

def safe_path(original_path: str, base_output_dir: str):
    """
    Ensure path length is within Windows limits by intelligently shortening components.
    Returns tuple of (safe_path, was_modified)
    """
    # Remove leading slash if present for processing
    clean_path = original_path[1:] if original_path.startswith('/') else original_path
    path_obj = Path(clean_path)
    parts = list(path_obj.parts)

    # Calculate the full path length including base output directory
    test_full_path = str(Path(base_output_dir) / clean_path)

    # If path is within limits, return as-is
    if len(test_full_path) < MAX_PATH_LENGTH:
        return original_path, False

    # Path is too long - need to shorten components
    modified = False
    new_parts = []

    for i, part in enumerate(parts):
        # Calculate remaining path budget
        current_path = str(Path(base_output_dir) / Path(*new_parts) if new_parts else Path(base_output_dir))
        remaining_parts = parts[i:]
        avg_length_needed = (MAX_PATH_LENGTH - len(current_path)) // max(len(remaining_parts), 1)

        # Shorten this component if needed
        if len(part) > avg_length_needed - 5:  # -5 for separators buffer
            part = shorten_path_component(part, max(20, avg_length_needed - 5))
            modified = True

        new_parts.append(part)

    # Reconstruct path, preserving leading slash if it was present
    safe_path_str = str(Path(*new_parts))
    if original_path.startswith('/'):
        safe_path_str = '/' + safe_path_str

    # Store mapping if path was modified
    if modified:
        path_mapping[safe_path_str] = original_path
        logging.info(f"Path shortened: {original_path} -> {safe_path_str}")

    return safe_path_str, modified

def save_path_mapping(output_dir: str):
    """Save the path mapping to a JSON file in the output directory."""
    if path_mapping:
        mapping_file = Path(output_dir) / PATH_MAPPING_FILE
        try:
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(path_mapping, f, indent=2, ensure_ascii=False)
            logging.info(f"Path mapping saved to {mapping_file} ({len(path_mapping)} entries)")
        except Exception as e:
            logging.warning(f"Could not save path mapping: {e}")

def windowsWarning():
    print("Note: Windows paths are not POSIX compliant.")
    print("      Illegal original-path chracters will be replaced with \"-\".")
    print("      Long paths will be automatically shortened with hash identifiers.")

def exitHandler(sig, frame):
    logging.info('Process terminated by user.')
    cleanWorking()
    if platform.system == "Windows": os._exit()
    else: os.kill(os.getpid(), signal.SIGINT)

def cleanWorking():
    try: shutil.rmtree('files')
    except: logging.debug('Files working directory not found')

def main():
    signal.signal(signal.SIGINT, exitHandler)
    args = setArgs()
    UFDR = Path(args.ufdr)
    OUTD = Path.cwd().joinpath("UFDRConvert")
    setLogging(args.debug)
    print(f"{__software__} v{__version__} - Use ctrl+c to exit")
    if platform.system() == "Windows":
        windowsWarning()
    if Path.is_file(UFDR):
        logging.debug(f'UDFR set to {args.ufdr}')
    if args.out and Path.is_dir(Path(args.out)):
        logging.debug(f'Output directory set to {args.out}')
        OUTD = args.out + "UFDRConvert"
    cleanWorking()
    getZipReportXML(UFDR, OUTD)

if __name__ == '__main__':
    main()


# Integration functions for the UFDR analyzer
def extract_ufdr_to_directory(ufdr_file_path: str, output_dir: str = None) -> str:
    """
    Extract a UFDR file to a directory structure.
    
    Args:
        ufdr_file_path: Path to the UFDR file
        output_dir: Output directory (optional, defaults to UFDRConvert in current dir)
    
    Returns:
        Path to the extracted directory
    """
    ufdr_path = Path(ufdr_file_path)
    if not ufdr_path.exists():
        raise FileNotFoundError(f"UFDR file not found: {ufdr_file_path}")
    
    if output_dir is None:
        output_dir = Path.cwd().joinpath("UFDRConvert")
    else:
        output_dir = Path(output_dir)
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Set up logging
    setLogging(False)  # Use INFO level for integration
    
    # Extract the UFDR file
    getZipReportXML(ufdr_path, str(output_dir))
    
    return str(output_dir)

def get_extracted_files_info(extracted_dir: str) -> dict:
    """
    Get information about extracted files from a UFDR extraction.
    
    Args:
        extracted_dir: Path to the extracted directory
    
    Returns:
        Dictionary with file information
    """
    extracted_path = Path(extracted_dir)
    if not extracted_path.exists():
        raise FileNotFoundError(f"Extracted directory not found: {extracted_dir}")
    
    files_info = {
        "total_files": 0,
        "file_types": {},
        "directories": [],
        "files": []
    }
    
    for item in extracted_path.rglob("*"):
        if item.is_file():
            files_info["total_files"] += 1
            file_ext = item.suffix.lower()
            files_info["file_types"][file_ext] = files_info["file_types"].get(file_ext, 0) + 1
            files_info["files"].append({
                "path": str(item.relative_to(extracted_path)),
                "size": item.stat().st_size,
                "extension": file_ext
            })
        elif item.is_dir():
            files_info["directories"].append(str(item.relative_to(extracted_path)))
    
    return files_info