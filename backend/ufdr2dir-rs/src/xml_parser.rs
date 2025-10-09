use anyhow::{Context, Result};
use regex::Regex;

#[derive(Debug, Clone)]
pub struct FileMapping {
    pub original_path: String,
    pub local_path: String,
}

pub fn parse_report_xml(xml_content: &str, debug: bool) -> Result<Vec<FileMapping>> {
    let mut mappings = Vec::new();
    let mut current_original_path: Option<String> = None;
    
    // Compile regex patterns (same as Python version)
    let path_regex = Regex::new(r#"path="(.*?)" "#)
        .context("Failed to compile path regex")?;
    let cdata_regex = Regex::new(r#"CDATA\[(.*?)\]\]"#)
        .context("Failed to compile CDATA regex")?;

    // Process line by line (same as Python version)
    for line in xml_content.lines() {
        // Check for <file fs tag with path attribute
        if line.contains("<file fs") {
            // Skip embedded files (SQLite BLOB extractions)
            if line.contains("embedded=\"true\"") {
                current_original_path = None;
                if debug {
                    println!("[DEBUG] Skipping embedded file");
                }
                continue;
            }
            
            if let Some(captures) = path_regex.captures(line) {
                if let Some(path_match) = captures.get(1) {
                    current_original_path = Some(path_match.as_str().to_string());
                    if debug {
                        println!("[DEBUG] Found original path: {}", path_match.as_str());
                    }
                }
            }
        }
        // Check for Local Path in metadata
        else if line.contains("name=\"Local Path\"") {
            if let Some(ref orig_path) = current_original_path {
                if let Some(captures) = cdata_regex.captures(line) {
                    if let Some(local_match) = captures.get(1) {
                        let local_path = local_match.as_str().replace("\\", "/");
                        
                        if debug {
                            println!("[DEBUG] Found local path: {}", local_path);
                        }
                        
                        mappings.push(FileMapping {
                            original_path: orig_path.clone(),
                            local_path,
                        });
                        
                        // Reset for next file
                        current_original_path = None;
                    }
                }
            }
        }
    }

    Ok(mappings)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_simple_file_entry() {
        let xml = r#"
<file fs="TarArchive" fsid="test" path="/data/test/file.txt" >
  <metadata section="File">
    <item name="Local Path" systemtype="System.String"><![CDATA[files\Application\test.txt]]></item>
  </metadata>
</file>
"#;
        
        let result = parse_report_xml(xml, false).unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].original_path, "/data/test/file.txt");
        assert_eq!(result[0].local_path, "files/Application/test.txt");
    }

    #[test]
    fn test_windows_path_conversion() {
        let xml = r#"
<file fs="TarArchive" path="/some/path.apk" >
  <metadata>
    <item name="Local Path"><![CDATA[files\App\test.apk]]></item>
  </metadata>
</file>
"#;
        
        let result = parse_report_xml(xml, false).unwrap();
        assert_eq!(result[0].local_path, "files/App/test.apk");
    }
}

