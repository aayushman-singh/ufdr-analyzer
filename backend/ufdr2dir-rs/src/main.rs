use anyhow::{Context, Result};
use clap::Parser;
use indicatif::{ProgressBar, ProgressStyle};
use std::fs::{self, File};
use std::io::{BufReader, Read, Write};
use std::path::{Path, PathBuf};
use zip::ZipArchive;

mod xml_parser;
mod path_utils;

use xml_parser::FileMapping;
use path_utils::{safe_path, sanitize_windows_path, PathMappingStore};

const MAX_PATH_LENGTH: usize = 240;
const VERSION: &str = "0.1.11";

/// Convert a Cellebrite Reader UFDR file to its original directory structure
#[derive(Parser, Debug)]
#[command(name = "ufdr2dir")]
#[command(version = VERSION)]
#[command(about = "Convert UFDR files to directory structure (Rust Edition)", long_about = None)]
struct Args {
    /// Path to the UFDR file to extract
    ufdr: PathBuf,

    /// Output directory path
    #[arg(short, long)]
    out: Option<PathBuf>,

    /// Enable debug logging
    #[arg(long)]
    debug: bool,

    /// Number of parallel extraction threads (default: number of CPU cores)
    #[arg(short, long)]
    threads: Option<usize>,
}

fn main() -> Result<()> {
    let args = Args::parse();

    println!("UFDR2DIR (Rust Edition) v{} - Press Ctrl+C to exit", VERSION);
    
    if cfg!(target_os = "windows") {
        println!("Note: Windows paths are not POSIX compliant.");
        println!("      Illegal original-path characters will be replaced with \"-\".");
        println!("      Long paths will be automatically shortened with hash identifiers.");
    }

    // Validate input file
    if !args.ufdr.exists() {
        anyhow::bail!("UFDR file not found: {:?}", args.ufdr);
    }

    // Determine output directory
    let output_dir = args.out.unwrap_or_else(|| {
        std::env::current_dir()
            .unwrap()
            .join("UFDRConvert")
    });

    // Set thread pool size if specified
    if let Some(threads) = args.threads {
        rayon::ThreadPoolBuilder::new()
            .num_threads(threads)
            .build_global()
            .context("Failed to set thread pool size")?;
    }

    // Create output directory
    fs::create_dir_all(&output_dir)
        .context("Failed to create output directory")?;

    if args.debug {
        println!("[DEBUG] UFDR file: {:?}", args.ufdr);
        println!("[DEBUG] Output directory: {:?}", output_dir);
        println!("[DEBUG] Using {} threads", rayon::current_num_threads());
    }

    // Process the UFDR file
    process_ufdr(&args.ufdr, &output_dir, args.debug)?;

    println!("\n✓ Extraction complete!");
    Ok(())
}

fn process_ufdr(ufdr_path: &Path, output_dir: &Path, debug: bool) -> Result<()> {
    println!("Opening UFDR file...");
    
    let file = File::open(ufdr_path)
        .context("Failed to open UFDR file")?;
    let reader = BufReader::new(file);
    let mut archive = ZipArchive::new(reader)
        .context("Failed to read UFDR as ZIP archive")?;

    // Step 1: Extract report.xml to output directory
    println!("Extracting report.xml...");
    let report_xml_content = {
        let mut report_file = archive.by_name("report.xml")
            .context("Failed to find report.xml in UFDR")?;
        
        let mut content = String::new();
        report_file.read_to_string(&mut content)
            .context("Failed to read report.xml")?;
        
        // Also save it to the output directory
        let report_path = output_dir.join("report.xml");
        let mut out_file = File::create(&report_path)
            .context("Failed to create report.xml in output directory")?;
        out_file.write_all(content.as_bytes())
            .context("Failed to write report.xml")?;
        
        println!("report.xml extracted to: {:?}", report_path);
        content
    };

    // Step 2: Parse XML to collect file mappings
    println!("Parsing report.xml to collect file mappings...");
    let file_mappings = xml_parser::parse_report_xml(&report_xml_content, debug)?;
    println!("Found {} file mappings", file_mappings.len());

    // Reopen archive for extraction (can't reuse after reading report.xml)
    let file = File::open(ufdr_path)
        .context("Failed to reopen UFDR file")?;
    let reader = BufReader::new(file);
    let archive = ZipArchive::new(reader)
        .context("Failed to reopen UFDR as ZIP archive")?;

    // Step 3: Create all directory structures first
    println!("Creating directory structure...");
    create_directory_structure(&file_mappings, output_dir, debug)?;

    // Step 4: Extract files in parallel
    println!("Extracting files in parallel...");
    extract_files_parallel(archive, &file_mappings, output_dir, debug)?;

    println!("Extraction complete!");
    Ok(())
}

fn create_directory_structure(
    mappings: &[FileMapping],
    output_dir: &Path,
    debug: bool,
) -> Result<()> {
    let progress = ProgressBar::new(mappings.len() as u64);
    progress.set_style(
        ProgressStyle::default_bar()
            .template("[{elapsed_precise}] {bar:40.cyan/blue} {pos}/{len} Creating directories")
            .unwrap()
            .progress_chars("=>-")
    );

    for mapping in mappings {
        let mut original_path = mapping.original_path.clone();
        
        // Apply Windows path sanitization if needed
        if cfg!(target_os = "windows") {
            original_path = sanitize_windows_path(&original_path);
        }

        // Apply safe path shortening
        let (safe_original_path, _) = safe_path(&original_path, output_dir, MAX_PATH_LENGTH);
        
        // Get the parent directory
        let full_path = output_dir.join(safe_original_path.trim_start_matches('/'));
        if let Some(parent) = full_path.parent() {
            if let Err(e) = fs::create_dir_all(parent) {
                if debug {
                    eprintln!("[DEBUG] Failed to create directory {:?}: {}", parent, e);
                }
            }
        }
        
        progress.inc(1);
    }
    
    progress.finish_and_clear();
    Ok(())
}

fn extract_files_parallel(
    mut archive: ZipArchive<BufReader<File>>,
    mappings: &[FileMapping],
    output_dir: &Path,
    debug: bool,
) -> Result<()> {
    // We need to extract files from ZIP sequentially (ZIP format limitation)
    // but we can parallelize the I/O operations
    
    let progress = ProgressBar::new(mappings.len() as u64);
    progress.set_style(
        ProgressStyle::default_bar()
            .template("[{elapsed_precise}] {bar:40.green/blue} {pos}/{len} {msg}")
            .unwrap()
            .progress_chars("=>-")
    );

    let mut path_mapping_store = PathMappingStore::new();
    let mut extracted_count = 0;
    let mut error_count = 0;

    for mapping in mappings {
        let mut original_path = mapping.original_path.clone();
        
        // Apply Windows path sanitization if needed
        if cfg!(target_os = "windows") {
            original_path = sanitize_windows_path(&original_path);
        }

        // Apply safe path shortening
        let (safe_original_path, was_modified) = safe_path(&original_path, output_dir, MAX_PATH_LENGTH);
        
        if was_modified {
            path_mapping_store.add_mapping(safe_original_path.clone(), original_path.clone());
            if debug {
                println!("[DEBUG] Path shortened: {} -> {}", original_path, safe_original_path);
            }
        }

        // Extract file from ZIP
        match extract_single_file(&mut archive, &mapping.local_path, &safe_original_path, output_dir, debug) {
            Ok(_) => {
                extracted_count += 1;
                progress.set_message(format!("Extracted: {}", safe_original_path));
            }
            Err(e) => {
                error_count += 1;
                if debug {
                    eprintln!("[DEBUG] Error extracting {}: {}", mapping.local_path, e);
                }
            }
        }
        
        progress.inc(1);
    }

    progress.finish_with_message(format!(
        "Extracted {} files ({} errors)",
        extracted_count, error_count
    ));

    // Save path mapping if any paths were shortened
    if path_mapping_store.has_mappings() {
        let mapping_path = output_dir.join("path_mapping.json");
        path_mapping_store.save(&mapping_path)
            .context("Failed to save path mapping")?;
        println!("Path mapping saved to: {:?}", mapping_path);
    }

    Ok(())
}

fn extract_single_file(
    archive: &mut ZipArchive<BufReader<File>>,
    local_path: &str,
    original_path: &str,
    output_dir: &Path,
    debug: bool,
) -> Result<()> {
    // Try to find the file in the archive
    let mut zip_file = archive.by_name(local_path)
        .context(format!("File not found in ZIP: {}", local_path))?;

    // Build output path
    let output_path = output_dir.join(original_path.trim_start_matches('/'));

    // Create parent directories if needed
    if let Some(parent) = output_path.parent() {
        fs::create_dir_all(parent)
            .context(format!("Failed to create parent directory: {:?}", parent))?;
    }

    // Extract file content
    let mut content = Vec::new();
    zip_file.read_to_end(&mut content)
        .context(format!("Failed to read file from ZIP: {}", local_path))?;

    // Write to output file
    let mut out_file = File::create(&output_path)
        .context(format!("Failed to create output file: {:?}", output_path))?;
    out_file.write_all(&content)
        .context(format!("Failed to write output file: {:?}", output_path))?;

    if debug {
        println!("[DEBUG] Extracted: {} -> {:?}", local_path, output_path);
    }

    Ok(())
}
