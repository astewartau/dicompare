#!/usr/bin/env python3
"""
Siemens .pro Protocol File Parser with DICOM Mapping

Uses twixtools to parse Siemens MRI protocol files (.pro) and extract
comprehensive protocol information in both raw and DICOM-compatible formats.

Usage:
    python parse_siemens_pro.py aspire_bipolar.pro

This script is now a lightweight CLI wrapper around the dicompare.pro_parser module.
"""

import argparse
import json
from pathlib import Path
from twixtools.twixprot import parse_buffer
from dicompare.pro_parser import apply_pro_to_dicom_mapping


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Parse Siemens .pro protocol files with optional DICOM mapping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('protocol_file', help='Path to .pro protocol file')
    args = parser.parse_args()

    # Parse the protocol file
    with open(Path(args.protocol_file), 'r', encoding='latin1') as f:
        content = f.read()
    parsed_data = parse_buffer(content)
    
    output_data = {
        "protocol_file": str(args.protocol_file),
        "raw_data": parsed_data,
        "dicom_fields": apply_pro_to_dicom_mapping(parsed_data)
    }
    
    # Display the data in a structured format
    print(json.dumps(output_data, indent=2))


if __name__ == '__main__':
    main()