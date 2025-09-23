    def create_realistic_device_structure(self):
        """Create comprehensive realistic device file structure"""
        if self.device_type == 'android':
            self._create_android_structure()
        elif self.device_type == 'ios':
            self._create_ios_structure()
        elif self.device_type == 'windows':
            self._create_windows_structure()
    
    def _create_android_structure(self):
        """Create comprehensive Android device structure"""
        
        # System files
        self.add_mock_file("/system/build.prop")
        self.add_mock_file("/system/app/Browser/Browser.apk")
        self.add_mock_file("/system/app/Calculator/Calculator.apk")
        
        # Core Android databases
        self.add_mock_file("/data/data/com.android.providers.contacts/databases/contacts2.db")
        self.add_mock_file("/data/data/com.android.providers.telephony/databases/mmssms.db")
        self.add_mock_file("/data/data/com.android.providers.calendar/databases/calendar.db")
        self.add_mock_file("/data/data/com.android.providers.media/databases/external.db")
        
        # Popular messaging apps
        self.add_mock_file("/data/data/com.whatsapp/databases/msgstore.db")
        self.add_mock_file("/data/data/com.whatsapp/databases/wa.db")
        self.add_mock_file("/data/data/com.facebook.orca/databases/threads_db2")  # Messenger
        self.add_mock_file("/data/data/com.instagram.android/databases/direct.db")
        self.add_mock_file("/data/data/com.snapchat.android/databases/tcspahn.db")
        
        # Browser data
        self.add_mock_file("/data/data/com.android.chrome/app_chrome/Default/History")
        self.add_mock_file("/data/data/com.android.chrome/app_chrome/Default/Cookies")
        self.add_mock_file("/data/data/com.android.chrome/app_chrome/Default/Login Data")
        
        # Email clients
        self.add_mock_file("/data/data/com.google.android.gm/databases/gmail.db")
        self.add_mock_file("/data/data/com.microsoft.office.outlook/databases/outlook.db")
        
        # Social media
        self.add_mock_file("/data/data/com.facebook.katana/databases/threads_db2")
        self.add_mock_file("/data/data/com.twitter.android/databases/twitter.db")
        self.add_mock_file("/data/data/com.linkedin.android/databases/linkedin.db")
        
        # Maps and location
        self.add_mock_file("/data/data/com.google.android.apps.maps/databases/gmm_storage.db")
        self.add_mock_file("/data/data/com.google.android.apps.maps/cache/cache.db")
        
        # Media files
        for i in range(5):
            self.add_mock_file(f"/sdcard/DCIM/Camera/IMG_2023110{i}_{120000 + i*100}.jpg")
            self.add_mock_file(f"/sdcard/DCIM/Camera/VID_2023110{i}_{120000 + i*100}.mp4")
        
        # Downloads
        self.add_mock_file("/sdcard/Download/document.pdf")
        self.add_mock_file("/sdcard/Download/presentation.pptx")
        self.add_mock_file("/sdcard/Download/app-release.apk")
        
        # Music
        self.add_mock_file("/sdcard/Music/favorite_song.mp3")
        self.add_mock_file("/sdcard/Music/playlist.m3u")
        
        # Documents
        self.add_mock_file("/sdcard/Documents/notes.txt")
        self.add_mock_file("/sdcard/Documents/passwords.txt", deleted=True)  # Deleted file
        self.add_mock_file("/sdcard/Documents/budget.xlsx")
        
        # App caches and logs
        self.add_mock_file("/data/data/com.android.chrome/cache/webdata_cache")
        self.add_mock_file("/data/system/dropbox/system_app_crash@1634567890000.txt")
        
        # Some carved/recovered files
        self.add_mock_file("/unallocated_space/recovered_image_001.jpg", carved=True)
        self.add_mock_file("/unallocated_space/recovered_document_002.pdf", carved=True)
    
    def _create_ios_structure(self):
        """Create comprehensive iOS device structure"""
        
        # Core iOS databases
        self.add_mock_file("/private/var/mobile/Library/SMS/sms.db")
        self.add_mock_file("/private/var/mobile/Library/AddressBook/AddressBook.sqlitedb")
        self.add_mock_file("/private/var/mobile/Library/CallHistoryDB/CallHistory.storedata")
        self.add_mock_file("/private/var/mobile/Library/Calendar/Calendar.sqlitedb")
        
        # Safari
        self.add_mock_file("/private/var/mobile/Library/Safari/History.db")
        self.add_mock_file("/private/var/mobile/Library/Safari/Bookmarks.db")
        self.add_mock_file("/private/var/mobile/Library/Cookies/Cookies.binarycookies")
        
        # Photos
        for i in range(5):
            self.add_mock_file(f"/private/var/mobile/Media/DCIM/100APPLE/IMG_000{i+1}.JPG")
            self.add_mock_file(f"/private/var/mobile/Media/DCIM/100APPLE/IMG_000{i+1}.MOV")
        
        # Apps
        self.add_mock_file("/private/var/mobile/Containers/Data/Application/WhatsApp/Documents/ChatStorage.sqlite")
        self.add_mock_file("/private/var/mobile/Containers/Data/Application/Instagram/Documents/instagram.db")
        self.add_mock_file("/private/var/mobile/Containers/Data/Application/Facebook/Documents/facebook.sqlite")
        
        # System preferences
        self.add_mock_file("/private/var/mobile/Library/Preferences/com.apple.mobilephone.plist")
        self.add_mock_file("/private/var/mobile/Library/Preferences/com.apple.springboard.plist")
        
        # Logs
        self.add_mock_file("/private/var/log/asl/ASL.DB")
        self.add_mock_file("/private/var/mobile/Library/Logs/CrashReporter/crash.log")
        
        # Mail
        self.add_mock_file("/private/var/mobile/Library/Mail/Envelope Index")
        
        # Notes
        self.add_mock_file("/private/var/mobile/Library/Notes/notes.sqlite")
        
        # Location services
        self.add_mock_file("/private/var/root/Library/Caches/locationd/consolidated.db")
    
    def _create_windows_structure(self):
        """Create Windows device structure"""
        
        # Registry files
        self.add_mock_file("/Windows/System32/config/SOFTWARE")
        self.add_mock_file("/Windows/System32/config/SYSTEM")
        self.add_mock_file("/Users/User/NTUSER.DAT")
        
        # Browser data
        self.add_mock_file("/Users/User/AppData/Local/Microsoft/Edge/User Data/Default/History")
        self.add_mock_file("/Users/User/AppData/Local/Google/Chrome/User Data/Default/History")
        
        # Email
        self.add_mock_file("/Users/User/AppData/Local/Microsoft/Outlook/outlook.pst")
        
        # Documents
        self.add_mock_file("/Users/User/Documents/document.#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mock UFDR Generator - Creates realistic Cellebrite UFDR files for testing
Based on reverse engineering of ufdr2dir.py
"""

import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import hashlib
import random
import string
from datetime import datetime, timedelta

class MockUFDRGenerator:
    def __init__(self, output_path="mock_extraction.ufdr", device_type="android"):
        self.output_path = output_path
        self.files_data = []
        self.local_file_counter = 0
        self.device_type = device_type.lower()  # "android", "ios", "windows"
        self.filesystem_types = ["main", "userdata", "system", "cache", "boot"]
        self.extraction_metadata = {
            'case_number': f"CASE-{random.randint(1000, 9999)}",
            'examiner': random.choice(["Detective Smith", "Agent Johnson", "Analyst Brown"]),
            'device_model': self._get_device_model(),
            'os_version': self._get_os_version(),
            'extraction_type': random.choice(["Physical", "Logical", "File System"]),
            'extraction_method': random.choice(["UFED", "Cellebrite Premium", "Cellebrite Touch"]),
            'total_data_size': 0
        }
    def _get_device_model(self):
        """Get realistic device model based on device type"""
        models = {
            'android': ['Samsung Galaxy S21', 'Google Pixel 6', 'OnePlus 9', 'Huawei P40', 'Xiaomi Mi 11'],
            'ios': ['iPhone 13 Pro', 'iPhone 12', 'iPhone 11', 'iPad Pro 12.9', 'iPhone SE (2nd gen)'],
            'windows': ['Surface Pro 8', 'Dell Latitude 7420', 'HP EliteBook 840', 'Lenovo ThinkPad X1']
        }
        return random.choice(models.get(self.device_type, models['android']))
    
    def _get_os_version(self):
        """Get realistic OS version"""
        versions = {
            'android': ['Android 12', 'Android 11', 'Android 10', 'Android 9'],
            'ios': ['iOS 15.6', 'iOS 14.8', 'iOS 13.7', 'iPadOS 15.6'],
            'windows': ['Windows 11 Pro', 'Windows 10 Pro', 'Windows 10 Home']
        }
        return random.choice(versions.get(self.device_type, versions['android']))
    
    def _get_filesystem_for_path(self, path):
        """Determine realistic filesystem type based on path"""
        if self.device_type == 'android':
            if path.startswith('/system'):
                return 'system'
            elif path.startswith('/data/data'):
                return 'userdata'
            elif path.startswith('/cache'):
                return 'cache'
            elif path.startswith('/boot'):
                return 'boot'
            else:
                return 'main'
        elif self.device_type == 'ios':
            if path.startswith('/private/var'):
                return 'userdata'
            elif path.startswith('/System'):
                return 'system'
            else:
                return 'main'
        else:
            return 'main'
        """Add a mock file to the UFDR structure"""
        if content is None:
            content = self._generate_mock_content(original_path)
        
        # Generate local path (how it's stored in the archive)
        local_path = f"files/{self.local_file_counter:06d}"
        self.local_file_counter += 1
        
        # Generate file metadata
        file_info = {
            'original_path': original_path,
            'local_path': local_path,
            'content': content,
            'size': len(content) if isinstance(content, bytes) else len(content.encode('utf-8')),
            'file_type': file_type,
            'md5': hashlib.md5(content if isinstance(content, bytes) else content.encode('utf-8')).hexdigest(),
            'created_time': self._random_timestamp(),
            'modified_time': self._random_timestamp(),
            'accessed_time': self._random_timestamp()
        }
        
        self.files_data.append(file_info)
        return file_info
    
    def _generate_mock_content(self, path):
        """Generate realistic content based on file type and device context"""
        ext = Path(path).suffix.lower()
        filename = Path(path).name
        
        # Database files - very common in mobile forensics
        if ext in ['.db', '.sqlite', '.sqlite3'] or 'database' in filename.lower():
            return self._generate_sqlite_content(path)
        
        # Property/config files
        elif ext == '.prop' or filename == 'build.prop':
            return self._generate_build_prop_content()
        
        # Plist files (iOS)
        elif ext == '.plist':
            return self._generate_plist_content(path)
        
        # Log files
        elif ext in ['.log', '.txt'] and ('log' in filename.lower() or 'crash' in filename.lower()):
            return self._generate_log_content(path)
        
        # XML files (Android manifests, etc.)
        elif ext == '.xml':
            return self._generate_xml_content(path)
        
        # JSON files (app configs, etc.)
        elif ext == '.json':
            return self._generate_json_content(path)
        
        # APK files
        elif ext == '.apk':
            return self._generate_apk_content()
        
        # Images with EXIF-like data
        elif ext in ['.jpg', '.jpeg']:
            return self._generate_jpeg_content()
        
        # Other image formats
        elif ext in ['.png', '.gif', '.bmp']:
            return self._generate_generic_image_content(ext)
        
        # Video files
        elif ext in ['.mp4', '.avi', '.mov']:
            return self._generate_video_content()
        
        # Audio files
        elif ext in ['.mp3', '.wav', '.m4a']:
            return self._generate_audio_content()
        
        # PDF documents
        elif ext == '.pdf':
            return self._generate_pdf_content()
        
        # Contact/calendar files
        elif 'contact' in filename.lower() or 'address' in filename.lower():
            return self._generate_contact_content()
        
        # Default text content
        else:
            return f"Mock content for {path}\nGenerated at {datetime.now()}\n" + \
                   f"File type: {ext}\nDevice: {self.extraction_metadata['device_model']}\n" + \
                   "Sample data content\n"
    
    def _generate_sqlite_content(self, path):
        """Generate realistic SQLite database content"""
        # SQLite file header
        header = b'SQLite format 3\x00'
        
        # Add some mock SQL-like content
        mock_data = b"""
        CREATE TABLE messages (id INTEGER PRIMARY KEY, thread_id INTEGER, 
        address TEXT, person INTEGER, date INTEGER, body TEXT, read INTEGER);
        INSERT INTO messages VALUES(1,1,'555-0123',1,1634567890000,'Hello there!',1);
        INSERT INTO messages VALUES(2,1,'555-0123',1,1634567950000,'How are you?',1);
        """
        
        return header + mock_data + os.urandom(random.randint(100, 1000))
    
    def _generate_build_prop_content(self):
        """Generate Android build.prop file"""
        props = [
            f"ro.build.version.release={self.extraction_metadata['os_version'].split()[-1]}",
            f"ro.product.model={self.extraction_metadata['device_model']}",
            "ro.build.type=user",
            f"ro.build.date={datetime.now().strftime('%a %b %d %H:%M:%S UTC %Y')}",
            "ro.debuggable=0",
            "ro.secure=1",
            "ro.allow.mock.location=0",
            "ro.build.tags=release-keys"
        ]
        return '\n'.join(props) + '\n'
    
    def _generate_plist_content(self, path):
        """Generate iOS plist file"""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.apple.{Path(path).stem}</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LastAccessed</key>
    <date>{datetime.now().isoformat()}Z</date>
</dict>
</plist>"""
    
    def _generate_log_content(self, path):
        """Generate realistic log file content"""
        log_levels = ['INFO', 'DEBUG', 'WARN', 'ERROR']
        log_entries = []
        
        for i in range(random.randint(5, 20)):
            timestamp = self._random_timestamp()
            level = random.choice(log_levels)
            message = random.choice([
                "Application started successfully",
                "User authentication completed",
                "Database connection established",
                "Network request completed",
                "Cache updated",
                "Background task completed",
                "Memory usage: 45MB"
            ])
            log_entries.append(f"{timestamp} {level}: {message}")
        
        return '\n'.join(log_entries) + '\n'
    
    def _generate_xml_content(self, path):
        """Generate XML content"""
        if 'manifest' in Path(path).name.lower():
            return self._generate_android_manifest()
        else:
            return f"""<?xml version="1.0" encoding="UTF-8"?>
<root>
    <metadata>
        <created>{datetime.now().isoformat()}</created>
        <source>{path}</source>
    </metadata>
    <data>
        <item id="1">Sample data item</item>
        <item id="2">Another data item</item>
    </data>
</root>"""
    
    def _generate_android_manifest(self):
        """Generate Android manifest file"""
        return """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.app">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.READ_CONTACTS" />
    <application android:label="Sample App">
        <activity android:name=".MainActivity">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
            </intent-filter>
        </activity>
    </application>
</manifest>"""
    
    def _generate_json_content(self, path):
        """Generate JSON configuration content"""
        config = {
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "settings": {
                "notifications_enabled": True,
                "sync_enabled": False,
                "theme": "dark"
            },
            "user_data": {
                "last_login": self._random_timestamp(),
                "session_count": random.randint(1, 100)
            }
        }
        return json.dumps(config, indent=2)
    
    def _generate_apk_content(self):
        """Generate mock APK file (ZIP-based)"""
        # APK files are ZIP archives - mock the header
        return b'PK\x03\x04\x14\x00\x00\x00\x08\x00' + os.urandom(200)
    
    def _generate_jpeg_content(self):
        """Generate JPEG with mock EXIF data"""
        # JPEG header with basic EXIF
        header = b'\xff\xd8\xff\xe1\x00\x16Exif\x00\x00'
        exif_data = f"Camera: {self.extraction_metadata['device_model']}".encode()
        return header + exif_data + b'\xff\xd9' + os.urandom(500)
    
    def _generate_generic_image_content(self, ext):
        """Generate generic image content"""
        if ext == '.png':
            return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x01\x00' + os.urandom(200)
        elif ext == '.gif':
            return b'GIF89a\x01\x00\x01\x00' + os.urandom(100)
        else:
            return os.urandom(300)
    
    def _generate_video_content(self):
        """Generate mock video file"""
        # MP4 header
        return b'\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00mp42isom' + os.urandom(1000)
    
    def _generate_audio_content(self):
        """Generate mock audio file"""
        # MP3 header (ID3v2)
        return b'ID3\x03\x00\x00\x00' + os.urandom(500)
    
    def _generate_pdf_content(self):
        """Generate mock PDF with metadata"""
        return f"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
/Creator ({self.extraction_metadata['device_model']})
/CreationDate (D:{datetime.now().strftime('%Y%m%d%H%M%S')})
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
>>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000074 00000 n 
0000000120 00000 n 
trailer
<<
/Size 4
/Root 1 0 R
>>
startxref
173
%%EOF""".encode()
    
    def _generate_contact_content(self):
        """Generate contact/address book content"""
        contacts = []
        for i in range(random.randint(3, 10)):
            contact = {
                'name': f'Contact {i+1}',
                'phone': f'555-{random.randint(1000, 9999)}',
                'email': f'contact{i+1}@example.com',
                'last_contacted': self._random_timestamp()
            }
            contacts.append(contact)
        return json.dumps(contacts, indent=2)
    
    def _random_timestamp(self):
        """Generate a random timestamp in the past year"""
        start = datetime.now() - timedelta(days=365)
        end = datetime.now()
        random_date = start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))
        return random_date.strftime("%Y-%m-%dT%H:%M:%S")
    
    def _create_report_xml(self):
        """Create the report.xml file based on reverse engineered structure"""
        root = ET.Element("root")
        
        # Add some mock header info
        info = ET.SubElement(root, "extractionInfo")
        ET.SubElement(info, "version").text = "PA.7.64.0.35"
        ET.SubElement(info, "deviceInfo").text = "Mock Device"
        ET.SubElement(info, "extractionDate").text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ET.SubElement(info, "case").text = "Mock Case 001"
        ET.SubElement(info, "examiner").text = "Test Examiner"
        
        # Add file system structure
        filesystem = ET.SubElement(root, "filesystem")
        
        # Group files by directory to create directory entries
        directories = set()
        for file_info in self.files_data:
            path_parts = Path(file_info['original_path']).parts
            for i in range(1, len(path_parts)):
                dir_path = '/' + '/'.join(path_parts[1:i+1])
                if path_parts[i] != Path(file_info['original_path']).name:  # Not the file itself
                    directories.add(dir_path)
        
        # Add directory entries first
        for dir_path in sorted(directories):
            dir_elem = ET.SubElement(filesystem, "file")
            dir_elem.set("fs", "main")
            dir_elem.set("path", dir_path + " ")  # Space after path (from regex pattern)
            dir_elem.set("type", "directory")
            dir_elem.set("deleted", "false")
            dir_elem.set("inode", str(random.randint(1000, 9999)))
            
            # Add directory metadata
            dir_fields = ET.SubElement(dir_elem, "fields")
            
            created_field = ET.SubElement(dir_fields, "field")
            created_field.set("name", "Created")
            created_field.text = self._random_timestamp()
            
            modified_field = ET.SubElement(dir_fields, "field")
            modified_field.set("name", "Modified")
            modified_field.text = self._random_timestamp()
        
        # Add file entries
        for file_info in self.files_data:
            # Create file element with fs attribute and path (note space after path for regex)
            file_elem = ET.SubElement(filesystem, "file")
            file_elem.set("fs", "main")  # Could be "main", "userdata", "system" etc.
            file_elem.set("path", file_info['original_path'] + " ")  # Space is important for regex
            file_elem.set("type", file_info['file_type'])
            file_elem.set("deleted", "false")
            file_elem.set("inode", str(random.randint(1000, 9999)))
            
            # Add metadata fields
            fields = ET.SubElement(file_elem, "fields")
            
            # Local Path (critical for ufdr2dir.py)
            local_path_field = ET.SubElement(fields, "field")
            local_path_field.set("name", "Local Path")
            local_path_field.text = f"<![CDATA[{file_info['local_path']}]]>"
            
            # File size
            size_field = ET.SubElement(fields, "field")
            size_field.set("name", "Size")
            size_field.text = str(file_info['size'])
            
            # MD5 hash
            md5_field = ET.SubElement(fields, "field")
            md5_field.set("name", "MD5")
            md5_field.text = file_info['md5']
            
            # SHA1 hash (often present in forensic tools)
            sha1_field = ET.SubElement(fields, "field")
            sha1_field.set("name", "SHA1")
            sha1_hash = hashlib.sha1(file_info['content'] if isinstance(file_info['content'], bytes) 
                                   else file_info['content'].encode('utf-8')).hexdigest()
            sha1_field.text = sha1_hash
            
            # Timestamps
            created_field = ET.SubElement(fields, "field")
            created_field.set("name", "Created")
            created_field.text = file_info['created_time']
            
            modified_field = ET.SubElement(fields, "field")
            modified_field.set("name", "Modified")
            modified_field.text = file_info['modified_time']
            
            accessed_field = ET.SubElement(fields, "field")
            accessed_field.set("name", "Accessed")
            accessed_field.text = file_info['accessed_time']
            
            # File permissions (Unix-style)
            perms_field = ET.SubElement(fields, "field")
            perms_field.set("name", "Permissions")
            perms_field.text = random.choice(["644", "755", "600", "700"])
        
        # Format XML with proper CDATA handling
        xml_str = ET.tostring(root, encoding='unicode')
        # Fix CDATA sections (ElementTree doesn't handle them properly)
        xml_str = xml_str.replace("&lt;![CDATA[", "<![CDATA[").replace("]]&gt;", "]]>")
        
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
    
    def add_missing_file_reference(self, original_path):
        """Add a file reference in XML but don't include the actual file (tests KeyError handling)"""
        local_path = f"files/{self.local_file_counter:06d}"
        self.local_file_counter += 1
        
        # Add to files_data but don't create actual file content
        file_info = {
            'original_path': original_path,
            'local_path': local_path,
            'content': None,  # This will cause the file to be missing from ZIP
            'size': 0,
            'file_type': "file",
            'md5': "d41d8cd98f00b204e9800998ecf8427e",  # MD5 of empty string
            'created_time': self._random_timestamp(),
            'modified_time': self._random_timestamp(),
            'accessed_time': self._random_timestamp(),
            'missing': True  # Flag to skip adding to ZIP
        }
        
        self.files_data.append(file_info)
        return file_info
    
    def add_duplicate_files(self, original_path, content=None):
        """Add multiple files with the same original path (tests FileExistsError)"""
        files = []
        for i in range(2):
            if content is None:
                content = f"Duplicate content version {i+1} for {original_path}"
            files.append(self.add_mock_file(f"{original_path}.duplicate{i}", content))
        return files
    
    def add_long_path_file(self):
        """Add a file with an extremely long path (tests OSError)"""
        long_name = "very_long_filename_" + "x" * 200 + ".txt"
        long_path = "/data/data/com.example.app/files/deeply/nested/directory/structure/" + long_name
        return self.add_mock_file(long_path, "Content with very long path")
    
    def add_archive_structure_test(self):
        """Add files that will test the archive extraction logic"""
        # Add a directory that will conflict with an extracted archive
        self.add_mock_file("/sdcard/archive_test/existing_file.txt", "Existing file content")
        
        # Add what looks like an archive that would extract to the same location
        archive_content = b'PK\x03\x04' + b'Mock archive content that would extract files'
        self.add_mock_file("/sdcard/downloads/archive_test.zip", archive_content)
        
        return True
        """Add realistic mock files that would be found on a mobile device"""
        
        # Android-like structure
        android_files = [
            "/data/data/com.android.providers.contacts/databases/contacts2.db",
            "/data/data/com.android.providers.telephony/databases/mmssms.db",
            "/data/data/com.whatsapp/databases/msgstore.db",
            "/sdcard/DCIM/Camera/IMG_20231101_120000.jpg",
            "/sdcard/DCIM/Camera/IMG_20231101_120001.jpg",
            "/sdcard/Download/document.pdf",
            "/system/build.prop",
            "/data/system/packages.xml",
            "/data/data/com.android.chrome/app_chrome/Default/History",
            "/data/data/com.facebook.katana/databases/threads_db2",
        ]
        
        # iOS-like structure  
        ios_files = [
            "/private/var/mobile/Library/SMS/sms.db",
            "/private/var/mobile/Library/AddressBook/AddressBook.sqlitedb",
            "/private/var/mobile/Library/CallHistoryDB/CallHistory.storedata",
            "/private/var/mobile/Media/DCIM/100APPLE/IMG_0001.JPG",
            "/private/var/mobile/Media/DCIM/100APPLE/IMG_0002.JPG",
            "/private/var/mobile/Applications/WhatsApp/Documents/ChatStorage.sqlite",
            "/private/var/mobile/Library/Safari/History.db",
            "/private/var/mobile/Library/Preferences/com.apple.mobilephone.plist",
        ]
        
        # Choose a device type
        device_files = random.choice([android_files, ios_files])
        
        for file_path in device_files:
            self.add_mock_file(file_path)
        
        # Add some user files
        user_files = [
            "/sdcard/Documents/notes.txt",
            "/sdcard/Pictures/family_photo.jpg",
            "/sdcard/Downloads/report.pdf",
            "/storage/emulated/0/Android/data/com.instagram.android/cache/temp.jpg"
        ]
        
        for file_path in user_files:
            self.add_mock_file(file_path)
    
    def generate_ufdr(self):
        """Generate the complete UFDR file"""
        print(f"Creating mock UFDR file: {self.output_path}")
        
        # Add mock files if none exist
        if not self.files_data:
            self.create_mock_device_files()
        
        # Create the ZIP file
        with zipfile.ZipFile(self.output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add report.xml
            report_xml = self._create_report_xml()
            zf.writestr("report.xml", report_xml)
            
            # Add all the mock files (skip missing ones)
            for file_info in self.files_data:
                if file_info.get('missing', False):
                    continue  # Skip files marked as missing (for testing KeyError)
                    
                content = file_info['content']
                if content is None:
                    continue
                    
                if isinstance(content, str):
                    content = content.encode('utf-8')
                zf.writestr(file_info['local_path'], content)
        
        print(f"Mock UFDR created successfully!")
        print(f"- Contains {len(self.files_data)} files")
        print(f"- File size: {os.path.getsize(self.output_path)} bytes")
        return self.output_path

def main():
    """Example usage with comprehensive testing scenarios"""
    generator = MockUFDRGenerator("comprehensive_test.ufdr")
    
    # Option 1: Use auto-generated device files
    generator.create_mock_device_files()
    
    # Option 2: Add custom files
    generator.add_mock_file("/custom/path/my_document.txt", "Custom content here")
    generator.add_mock_file("/custom/path/image.png")  # Will auto-generate binary content
    
    # Test edge cases that the original script handles
    print("Adding edge case test files...")
    
    # Test missing file handling (KeyError)
    generator.add_missing_file_reference("/data/missing_file.db")
    
    # Test duplicate file handling (FileExistsError)
    generator.add_duplicate_files("/sdcard/duplicate_test.txt")
    
    # Test long path handling (OSError)
    generator.add_long_path_file()
    
    # Test archive structure conflicts
    generator.add_archive_structure_test()
    
    # Add files with different filesystem types
    generator.add_mock_file("/system/build.prop", "# Build properties\nro.build.version.release=11\n")
    
    # Generate the UFDR file
    ufdr_path = generator.generate_ufdr()
    
    print(f"\nComprehensive test UFDR created!")
    print(f"This UFDR tests various edge cases in ufdr2dir.py:")
    print(f"- Missing file references (KeyError handling)")
    print(f"- Duplicate files (FileExistsError handling)") 
    print(f"- Long file paths (OSError handling)")
    print(f"- Directory conflicts (IsADirectoryError handling)")
    print(f"- Different filesystem types")
    print(f"- Proper CDATA and XML structure")
    print(f"\nTo test with ufdr2dir.py:")
    print(f"python ufdr2dir.py {ufdr_path}")
    
    return ufdr_path

if __name__ == "__main__":
    main()