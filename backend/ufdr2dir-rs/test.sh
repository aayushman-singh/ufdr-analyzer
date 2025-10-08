#!/bin/bash
# Test script for ufdr2dir-rs

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Testing UFDR2DIR (Rust Edition)${NC}"
echo ""

# Check if binary exists
if [ ! -f "target/release/ufdr2dir" ]; then
    echo "Binary not found. Building first..."
    cargo build --release
fi

# Check if test file exists
TEST_FILE="../../test_small.ufdr"
if [ ! -f "$TEST_FILE" ]; then
    echo "Test file not found: $TEST_FILE"
    echo "Please run create_small_ufdr.py first from the repo root"
    exit 1
fi

# Clean previous test output
echo "Cleaning previous test output..."
rm -rf test_output

# Run extraction with timing
echo ""
echo -e "${GREEN}Extracting test_small.ufdr...${NC}"
echo ""

time ./target/release/ufdr2dir "$TEST_FILE" -o test_output --debug

# Check results
if [ -d "test_output" ]; then
    FILE_COUNT=$(find test_output -type f | wc -l)
    echo ""
    echo -e "${GREEN}✓ Test successful!${NC}"
    echo "  Files extracted: $FILE_COUNT"
    echo "  Output directory: test_output/"
    
    # Check if path_mapping.json was created
    if [ -f "test_output/path_mapping.json" ]; then
        MAPPING_COUNT=$(cat test_output/path_mapping.json | grep -c '"' || true)
        echo "  Path mappings: $MAPPING_COUNT"
    fi
else
    echo ""
    echo "✗ Test failed! Output directory not created"
    exit 1
fi

