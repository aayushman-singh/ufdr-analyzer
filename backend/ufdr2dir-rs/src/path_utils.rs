use anyhow::{Context, Result};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::Write;
use std::path::Path;

#[derive(Debug, Serialize, Deserialize)]
pub struct PathMappingStore {
    mappings: HashMap<String, String>,
}

impl PathMappingStore {
    pub fn new() -> Self {
        Self {
            mappings: HashMap::new(),
        }
    }

    pub fn add_mapping(&mut self, shortened_path: String, original_path: String) {
        self.mappings.insert(shortened_path, original_path);
    }

    pub fn has_mappings(&self) -> bool {
        !self.mappings.is_empty()
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        let json = serde_json::to_string_pretty(&self.mappings)
            .context("Failed to serialize path mappings")?;
        
        let mut file = File::create(path)
            .context("Failed to create path mapping file")?;
        
        file.write_all(json.as_bytes())
            .context("Failed to write path mapping file")?;
        
        Ok(())
    }
}

/// Sanitize path for Windows (replace illegal characters)
pub fn sanitize_windows_path(path: &str) -> String {
    let illegal_chars = Regex::new(r#"[:*?"<>|]"#).unwrap();
    illegal_chars.replace_all(path, "-").to_string()
}

/// Shorten a path component if it exceeds max_length
/// Uses first chars + MD5 hash to maintain uniqueness
pub fn shorten_path_component(component: &str, max_length: usize) -> String {
    if component.len() <= max_length {
        return component.to_string();
    }

    // Take first part of the name to keep it readable, then add hash
    let hash = format!("{:x}", md5::compute(component.as_bytes()));
    let hash_suffix = &hash[..8]; // Take first 8 chars of hash
    
    let prefix_length = max_length.saturating_sub(hash_suffix.len() + 1); // -1 for underscore
    let prefix = if component.len() > prefix_length {
        &component[..prefix_length]
    } else {
        component
    };
    
    format!("{}_{}", prefix, hash_suffix)
}

/// Ensure path length is within Windows limits by intelligently shortening components
/// Returns tuple of (safe_path, was_modified)
pub fn safe_path(original_path: &str, base_output_dir: &Path, max_path_length: usize) -> (String, bool) {
    // Remove leading slash if present for processing
    let clean_path = original_path.trim_start_matches('/');
    
    // Split path into components
    let parts: Vec<&str> = clean_path.split('/').collect();
    
    // Calculate the full path length including base output directory
    let base_str = base_output_dir.to_string_lossy();
    let test_full_path = format!("{}/{}", base_str, clean_path);
    
    // If path is within limits, return as-is
    if test_full_path.len() < max_path_length {
        return (original_path.to_string(), false);
    }

    // Path is too long - need to shorten components
    let mut new_parts: Vec<String> = Vec::new();
    let mut modified = false;

    for (i, part) in parts.iter().enumerate() {
        // Calculate remaining path budget
        let current_path_len = if new_parts.is_empty() {
            base_str.len()
        } else {
            base_str.len() + new_parts.iter().map(|p| p.len() + 1).sum::<usize>()
        };
        
        let remaining_parts = parts.len() - i;
        let avg_length_needed = if remaining_parts > 0 {
            (max_path_length.saturating_sub(current_path_len)) / remaining_parts
        } else {
            80
        };

        // Shorten this component if needed
        let new_part = if part.len() > avg_length_needed.saturating_sub(5) {
            // -5 for separators buffer
            modified = true;
            shorten_path_component(part, avg_length_needed.saturating_sub(5).max(20))
        } else {
            part.to_string()
        };

        new_parts.push(new_part);
    }

    // Reconstruct path, preserving leading slash if it was present
    let safe_path_str = if original_path.starts_with('/') {
        format!("/{}", new_parts.join("/"))
    } else {
        new_parts.join("/")
    };

    (safe_path_str, modified)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn test_sanitize_windows_path() {
        let path = r#"/data/test:file*name?.txt"#;
        let sanitized = sanitize_windows_path(path);
        assert_eq!(sanitized, "/data/test-file-name-.txt");
    }

    #[test]
    fn test_shorten_path_component() {
        let long_name = "this_is_a_very_long_filename_that_exceeds_the_maximum_length_allowed_by_the_filesystem";
        let shortened = shorten_path_component(long_name, 30);
        assert!(shortened.len() <= 30);
        assert!(shortened.contains('_'));
    }

    #[test]
    fn test_safe_path_short_path() {
        let path = "/data/test.txt";
        let base = PathBuf::from("/tmp/output");
        let (result, modified) = safe_path(path, &base, 240);
        assert_eq!(result, path);
        assert!(!modified);
    }

    #[test]
    fn test_safe_path_long_path() {
        let long_component = "a".repeat(200);
        let path = format!("/data/{}/test.txt", long_component);
        let base = PathBuf::from("/tmp/output");
        let (result, modified) = safe_path(&path, &base, 240);
        assert!(modified);
        assert!(result.len() < path.len());
    }

    #[test]
    fn test_path_mapping_store() {
        let mut store = PathMappingStore::new();
        assert!(!store.has_mappings());
        
        store.add_mapping("/short/path".to_string(), "/very/long/original/path".to_string());
        assert!(store.has_mappings());
    }
}

