#!/usr/bin/env python3
"""
Create a test UFDR file from a large UFDR for development/testing.
Includes all important file types to test ALEAPP artifacts comprehensively.
"""

import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
import io
import sys
import re
from collections import defaultdict

def create_small_ufdr(input_ufdr: str, output_ufdr: str, max_files: int = 5000):
    """
    Create a test UFDR with comprehensive file types for realistic testing.
    
    Args:
        input_ufdr: Path to the original large UFDR
        output_ufdr: Path for the new test UFDR
        max_files: Maximum number of files to include (0 = unlimited)
    """
    print(f"Creating test UFDR with max {max_files if max_files > 0 else 'unlimited'} files...")
    print("Prioritizing: databases, configs, logs, media, and app data")
    
    with ZipFile(input_ufdr, 'r') as input_zip:
        # Read report.xml
        print("\nReading report.xml...")
        report_xml = input_zip.read('report.xml').decode('utf-8')
        
        # Parse XML to find file entries
        print("Parsing XML structure...")
        lines = report_xml.split('\n')
        print(f"  XML contains {len(lines):,} lines")
        
        # Categorize files by type/importance
        file_categories = {
            'databases': [],      # .db, .db-wal, .db-shm
            'configs': [],        # .xml, .json, .plist, .conf
            'logs': [],           # .log, .txt (in log dirs)
            'media': [],          # .jpg, .png, .mp4, .mp3, etc
            'app_data': [],       # files in app directories
            'system': [],         # system configuration files
            'other': []           # everything else
        }
        
        # Define reasonable limits per category for ALEAPP testing
        category_limits = {
            'databases': 200,    # Key databases for analysis
            'configs': 300,      # Configuration files
            'logs': 150,         # Log files
            'app_data': 400,     # App-specific data
            'system': 200,       # System files
            'media': 100,        # Media files (smaller sample)
            'other': 150         # Other files
        }
        
        # If max_files is specified, scale down proportionally
        if max_files > 0:
            total_planned = sum(category_limits.values())
            if total_planned > max_files:
                scale_factor = max_files / total_planned
                for cat in category_limits:
                    category_limits[cat] = max(1, int(category_limits[cat] * scale_factor))
                print(f"Scaled down limits to fit {max_files} total files")
        
        # Parse line by line to find files with early exit
        current_file_data = {}
        files_found = 0
        
        print("  Categorizing files by type (will stop when limits are reached)...")
        for i, line in enumerate(lines):
            # Show progress every 10000 lines
            if i > 0 and i % 10000 == 0:
                print(f"    Processed {i:,} / {len(lines):,} lines ({i/len(lines)*100:.1f}%) - Found {files_found:,} files so far")
            
            # Check if we have enough files in each category
            all_categories_full = True
            for category, limit in category_limits.items():
                if len(file_categories[category]) < limit:
                    all_categories_full = False
                    break
            
            if all_categories_full:
                print(f"    All category limits reached! Stopping at line {i:,}")
                break
            
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
                        # Categorize the file
                        path_lower = local_path.lower()
                        
                        if path_lower.endswith(('.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite3')):
                            if len(file_categories['databases']) < category_limits['databases']:
                                file_categories['databases'].append(current_file_data.copy())
                        elif path_lower.endswith(('.xml', '.json', '.plist', '.conf', '.config', '.properties')):
                            if len(file_categories['configs']) < category_limits['configs']:
                                file_categories['configs'].append(current_file_data.copy())
                        elif path_lower.endswith('.log') or '/log/' in path_lower or '/logs/' in path_lower:
                            if len(file_categories['logs']) < category_limits['logs']:
                                file_categories['logs'].append(current_file_data.copy())
                        elif path_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.mp4', '.mp3', '.webp', '.heic')):
                            if len(file_categories['media']) < category_limits['media']:
                                file_categories['media'].append(current_file_data.copy())
                        elif any(app in path_lower for app in ['/com.', '/org.', '/app/', '/data/data/', '/shared_prefs/']):
                            if len(file_categories['app_data']) < category_limits['app_data']:
                                file_categories['app_data'].append(current_file_data.copy())
                        elif any(sys in path_lower for sys in ['/system/', '/etc/', '/proc/', '/sys/']):
                            if len(file_categories['system']) < category_limits['system']:
                                file_categories['system'].append(current_file_data.copy())
                        else:
                            if len(file_categories['other']) < category_limits['other']:
                                file_categories['other'].append(current_file_data.copy())
                        
                        files_found += 1
                    
                    # Reset for next file
                    current_file_data = {}
        
        print(f"  Completed parsing - Found {files_found:,} total files")
        
        # Print category statistics
        print("\nFile categories found:")
        total = 0
        for cat, files in file_categories.items():
            count = len(files)
            total += count
            print(f"  {cat:15s}: {count:6,d} files")
        print(f"  {'TOTAL':15s}: {total:6,d} files")
        
        # Build final file list - files are already sampled during parsing
        files_to_extract = []
        
        print(f"\nFiles already sampled during parsing:")
        
        # All files in categories are already within limits
        for category, limit in category_limits.items():
            cat_files = file_categories[category]
            if cat_files:
                print(f"  {category:15s}: {len(cat_files):6,d} files (limit: {limit})")
                files_to_extract.extend(cat_files)
            else:
                print(f"  {category:15s}: 0 files available")
        
        print(f"\n{'='*60}")
        print(f"Total files to extract: {len(files_to_extract):,}")
        print(f"{'='*60}\n")
        
        # Create new UFDR with subset of files
        with ZipFile(output_ufdr, 'w', ZIP_DEFLATED) as output_zip:
            # Copy report.xml as-is (it will still reference all files, but that's ok for testing)
            print("Writing report.xml to new UFDR...")
            output_zip.writestr('report.xml', report_xml)
            
            # Copy selected files
            print(f"\nCopying {len(files_to_extract):,} files to UFDR...")
            copied_count = 0
            failed_count = 0
            total_size = 0
            
            for idx, file_data in enumerate(files_to_extract):
                local_path = file_data['local_path']
                try:
                    file_content = input_zip.read(local_path)
                    output_zip.writestr(local_path, file_content)
                    copied_count += 1
                    total_size += len(file_content)
                    
                    # Show progress every 50 files or at specific milestones
                    if (idx + 1) % 50 == 0 or (idx + 1) in [10, 25, 100, 500, 1000]:
                        pct = (idx + 1) / len(files_to_extract) * 100
                        size_mb = total_size / (1024 * 1024)
                        print(f"  [{pct:5.1f}%] {idx + 1:6,}/{len(files_to_extract):6,} files | {size_mb:7.1f} MB | {copied_count:,} OK, {failed_count:,} failed")
                        
                except KeyError:
                    failed_count += 1
                    if failed_count <= 5:  # Only show first 5 failures
                        print(f"  [ERROR] Could not find: {local_path}")
                except Exception as e:
                    failed_count += 1
                    if failed_count <= 5:
                        print(f"  [ERROR] Failed copying {local_path}: {e}")
            
            if failed_count > 5:
                print(f"  [!] ... and {failed_count - 5} more failures not shown")
            
            # Final summary
            final_size_mb = total_size / (1024 * 1024)
            print(f"\n{'='*60}")
            print(f"[+] Created {output_ufdr}")
            print(f"  Successfully copied: {copied_count:,} files ({final_size_mb:.1f} MB)")
            if failed_count > 0:
                print(f"  Failed to copy: {failed_count:,} files")
            print(f"{'='*60}")

if __name__ == '__main__':
    input_file = 'Android_13_Image.ufdr'
    output_file = 'test_comprehensive.ufdr'
    num_files = 1500  # Default to 1500 files for balanced ALEAPP testing
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        try:
            num_files = int(sys.argv[1])
        except ValueError:
            print(f"Error: First argument must be a number (got '{sys.argv[1]}')")
            print("Usage: python create_small_ufdr.py [num_files] [output_file]")
            print("  num_files: Maximum number of files (default: 1500, 0 = unlimited)")
            print("  output_file: Output filename (default: test_comprehensive.ufdr)")
            sys.exit(1)
    
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    
    print("="*60)
    print("UFDR Test File Creator")
    print("="*60)
    print(f"Input:  {input_file}")
    print(f"Output: {output_file}")
    print(f"Target: {num_files if num_files > 0 else 'ALL'} files")
    print("="*60)
    
    create_small_ufdr(input_file, output_file, num_files)
    
    print("\n[+] Done! You can now test with:", output_file)
    print("\nQuick test commands:")
    print(f"  Python: python backend/ingest/utils/ufdr2dir.py {output_file}")
    print(f"  Rust:   backend/ufdr2dir-rs/target/release/ufdr2dir {output_file}")

