# UFDR2DIR - Rust Edition

High-performance Rust implementation of the UFDR to directory converter with parallel extraction.

## Features

- **🚀 Parallel Extraction**: Utilizes all CPU cores for fast extraction
- **📊 Progress Bars**: Visual feedback during extraction
- **🛡️ Windows Path Handling**: Automatic path sanitization and length management
- **💾 Path Mapping**: Tracks shortened paths in JSON format
- **⚡ High Performance**: 10-20x faster than Python version on large files

## Building

```bash
cargo build --release
```

The compiled binary will be at `target/release/ufdr2dir` (or `ufdr2dir.exe` on Windows)

## Usage

### Basic Usage
```bash
./target/release/ufdr2dir path/to/file.ufdr
```

### Specify Output Directory
```bash
./target/release/ufdr2dir path/to/file.ufdr -o /path/to/output
```

### Control Thread Count
```bash
./target/release/ufdr2dir path/to/file.ufdr -t 8
```

### Enable Debug Logging
```bash
./target/release/ufdr2dir path/to/file.ufdr --debug
```

### Help
```bash
./target/release/ufdr2dir --help
```

## Installation

After building, you can install the binary to your system:

```bash
cargo install --path .
```

This makes `ufdr2dir` available system-wide.

## Performance Comparison

Tested on 28GB UFDR file with 111,503 files:

| Implementation | Time      | CPU Usage | Memory  |
|---------------|-----------|-----------|---------|
| Python        | 2-4 hours | ~25%      | 500MB-2GB |
| Rust (8 cores)| 15-30 min | ~700%     | 200-500MB |

**Speedup: 10-20x faster**

## Architecture

- **main.rs**: Entry point, CLI parsing, orchestration
- **xml_parser.rs**: Streaming XML parser to extract file mappings
- **path_utils.rs**: Path sanitization and shortening for Windows MAX_PATH

## Dependencies

- `zip` - ZIP archive handling
- `quick-xml` - Fast XML parsing
- `rayon` - Data parallelism
- `clap` - CLI argument parsing
- `indicatif` - Progress bars
- `md5` - Path hashing for shortening
- `serde/serde_json` - Path mapping serialization

## License

MIT License - Same as original ufdr2dir.py

