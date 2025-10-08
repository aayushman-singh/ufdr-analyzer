#!/usr/bin/env python3
"""
Create a smaller test UFDR file from a large UFDR for development/testing.
"""

import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
import io
import sys
import re

def create_small_ufdr(input_ufdr: str, output_ufdr: str, max_files: int = 200):
    """
    Create a smaller UFDR with only first N files for testing.
    
    Args:
        input_ufdr: Path to the original large UFDR
        output_ufdr: Path for the new small UFDR
        max_files: Maximum number of files to include
    """
    print(f"Creating small UFDR with max {max_files} files...")
    
    with ZipFile(input_ufdr, 'r') as input_zip:
        # Read report.xml
        print("Reading report.xml...")
        report_xml = input_zip.read('report.xml').decode('utf-8')
        
        # Parse XML to find file entries
        print("Parsing XML structure...")
        files_to_extract = []
        file_count = 0
        
        # Parse line by line to find files (similar to the original script)
        lines = report_xml.split('\n')
        current_file_data = {}
        
        for i, line in enumerate(lines):
            # Match exactly as original ufdr2dir.py does
            if line.__contains__('<file fs'):
                # Note: original regex has space after closing quote
                match = re.search('path="(.*?)" ', line)
                if match:
                    current_file_data['original_path'] = match.group(1)
                    current_file_data['xml_line'] = i
            
            elif line.__contains__('name="Local Path"') and current_file_data:
                # Extract local path from CDATA, exactly as original
                match = re.search(r'CDATA\[(.*?)\]\]', line)
                if match:
                    local_path = match.group(1).replace("\\", "/")
                    current_file_data['local_path'] = local_path
                    
                    # Check if file exists in ZIP
                    if local_path in input_zip.namelist():
                        files_to_extract.append(current_file_data.copy())
                        file_count += 1
                        
                        if file_count >= max_files:
                            print(f"Reached {max_files} files, stopping collection...")
                            break
                    else:
                        print(f"  Warning: {local_path} not in ZIP, skipping...")
                    
                    # Reset for next file
                    current_file_data = {}
        
        print(f"Found {len(files_to_extract)} files to extract")
        
        # Create new UFDR with subset of files
        with ZipFile(output_ufdr, 'w', ZIP_DEFLATED) as output_zip:
            # Copy report.xml as-is (it will still reference all files, but that's ok for testing)
            print("Writing report.xml to new UFDR...")
            output_zip.writestr('report.xml', report_xml)
            
            # Copy selected files
            print(f"Copying {len(files_to_extract)} files...")
            for idx, file_data in enumerate(files_to_extract):
                local_path = file_data['local_path']
                try:
                    file_content = input_zip.read(local_path)
                    output_zip.writestr(local_path, file_content)
                    if (idx + 1) % 50 == 0:
                        print(f"  Copied {idx + 1}/{len(files_to_extract)} files...")
                except KeyError:
                    print(f"  Warning: Could not find {local_path} in ZIP")
                except Exception as e:
                    print(f"  Error copying {local_path}: {e}")
            
            print(f"✓ Created {output_ufdr} with {len(files_to_extract)} files")

if __name__ == '__main__':
    input_file = 'Android_13_Image.ufdr'
    output_file = 'test_small.ufdr'
    num_files = 200
    
    if len(sys.argv) > 1:
        num_files = int(sys.argv[1])
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print(f"Target files: {num_files}")
    print("-" * 50)
    
    create_small_ufdr(input_file, output_file, num_files)
    print("\nDone! You can now test with:", output_file)

