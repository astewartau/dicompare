# Release Notes - v0.1.34

- **BREAKING**: twixtools is now a required dependency for .pro file support
- **BREAKING**: Removed `async_load_pro_session()`, `parse_protocol_parameters()`, `extract_from_xprotocol()`
- Added `fieldType` classification to DICOM tag metadata ("standard" vs "derived")
- Added comprehensive test suite for .pro file functionality (266 lines)
- Added `SIEMENS_FIELDS.md` documentation analyzing Siemens DICOM field extraction
- Removed 27,047 lines of legacy code (22 example .pro files, docs/ web interface, unused utilities)
- Simplified imports by removing try/except blocks for optional dependencies
- Moved 3 .pro files to test fixtures in proper location
- All tests passing (100%)
