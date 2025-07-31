# Dicompare API Documentation

This document describes the complete API specification for the Dicompare system, which provides DICOM analysis, validation template generation, and compliance checking functionality.

## Table of Contents

- [Core Data Types](#core-data-types)
- [DICOM Analysis Functions](#dicom-analysis-functions)  
- [Schema and Template Functions](#schema-and-template-functions)
- [Compliance Validation Functions](#compliance-validation-functions)
- [Field Dictionary Functions](#field-dictionary-functions)
- [Example and Demo Functions](#example-and-demo-functions)
- [Utility Functions](#utility-functions)

## Core Data Types

### AnalysisResult
The primary result returned by DICOM file analysis.

```typescript
interface AnalysisResult {
  acquisitions: Acquisition[];
  summary: {
    total_files: number;
    total_acquisitions: number;
    common_fields: string[];
    suggested_validation_fields: string[];
  };
}
```

### Acquisition
Represents a logical grouping of DICOM files (typically same protocol/sequence).

```typescript
interface Acquisition {
  id: string;
  protocol_name: string;
  series_description: string;
  total_files: number;
  acquisition_fields: FieldInfo[];
  series_fields: FieldInfo[];
  series: SeriesInfo[];
  metadata: Record<string, any>;
}
```

### FieldInfo  
Detailed information about a DICOM field found in the analysis.

```typescript
interface FieldInfo {
  tag: string;                    // DICOM tag (e.g., "0008,0060")
  name: string;                   // Human-readable name
  value?: any;                    // Single value (for constant fields)
  values?: any[];                 // Multiple values (for varying fields)
  vr: string;                     // Value Representation
  level: 'acquisition' | 'series';
  data_type: 'string' | 'number' | 'list_string' | 'list_number' | 'json';
  consistency: 'constant' | 'varying';
  validation_rule?: ValidationRule;
}
```

### ValidationRule
Defines how a field should be validated.

```typescript
interface ValidationRule {
  type: 'exact' | 'tolerance' | 'range' | 'contains';
  value?: any;           // For exact matches and tolerance expected value
  tolerance?: number;    // For tolerance validation (±range)
  min?: number;          // For range validation (minimum)
  max?: number;          // For range validation (maximum)
  contains?: string;     // For substring matching
}
```

## DICOM Analysis Functions

### analyzeFiles
Analyzes DICOM files to detect acquisitions and extract field metadata.

```python
def analyze_dicom_files(files: List[Dict[str, Any]]) -> AnalysisResult:
    """
    Analyze DICOM files to detect acquisitions and extract comprehensive metadata.
    
    Args:
        files: List of file objects with structure:
               [{"name": "file1.dcm", "content": bytes}, ...]
               where 'content' is the raw DICOM file bytes
        
    Returns:
        AnalysisResult containing acquisitions and summary statistics
        
    Raises:
        ValueError: If file data is invalid or cannot be parsed
        DicomError: If DICOM parsing fails
    """
```

**Browser Implementation Example:**
```typescript
// React/TypeScript - Convert File objects to bytes
const processFiles = async (fileList: FileList) => {
  const files = [];
  
  for (const file of Array.from(fileList)) {
    const content = await file.arrayBuffer();
    files.push({
      name: file.name,
      content: new Uint8Array(content)
    });
  }
  
  const result = await dicompareAPI.analyzeFiles(files);
  return result;
};
```

**Python API Call:**
```python
# Files passed as bytes with metadata
result = dicompare.analyze_dicom_files([
    {"name": "image001.dcm", "content": dicom_bytes_1},
    {"name": "image002.dcm", "content": dicom_bytes_2},
    {"name": "image003.dcm", "content": dicom_bytes_3}
])

print(f"Found {len(result['acquisitions'])} acquisitions")
print(f"Total files: {result['summary']['total_files']}")
```

**Expected Input:** List of file objects with name and binary content
**Expected Output:** Complete analysis with acquisitions grouped by protocol/series

## Schema and Template Functions

### generateTemplate
Creates a validation template from configured acquisitions.

```python
def generate_validation_template(
    acquisitions: List[dict], 
    metadata: dict
) -> ValidationTemplate:
    """
    Generate a validation template from acquisition configurations.
    
    Args:
        acquisitions: List of acquisition configurations with validation rules
        metadata: Template metadata (name, version, authors, etc.)
        
    Returns:
        ValidationTemplate with generated rules and statistics
        
    Raises:
        ValidationError: If acquisition configurations are invalid
    """
```

**Example:**
```python
acquisitions = [
    {
        "id": "t1_mprage",
        "name": "T1 MPRAGE",
        "acquisition_fields": [
            {
                "tag": "0008,0060",
                "validation_rule": {"type": "exact", "value": "MR"}
            }
        ]
    }
]

metadata = {
    "name": "Clinical Research Template",
    "version": "1.0",
    "description": "Standard clinical validation"
}

template = dicompare.generate_validation_template(acquisitions, metadata)
```

### parseSchema
Parse schema content and extract validation rules.

```python
def parse_schema(schema_content: str, format: str = "json") -> dict:
    """
    Parse schema content and extract detailed validation rules.
    
    Args:
        schema_content: Raw schema content as string (from uploaded file or repository)
        format: Schema format ("json" or "python")
        
    Returns:
        Dict with 'parsed_schema' containing ParsedSchema or 'error' message
        
    Raises:
        SchemaParseError: If schema format is invalid or cannot be parsed
    """
```

**Example:**
```python
# Schema content loaded from file or user upload
schema_json = '''
{
    "metadata": {
        "id": "brain_mri_basic",
        "name": "Brain MRI Basic Protocol",
        "version": "1.0"
    },
    "acquisitions": {
        "t1_mprage": {
            "fields": [
                {
                    "tag": "0008,0060",
                    "validation_rule": {"type": "exact", "value": "MR"}
                }
            ]
        }
    }
}
'''

result = dicompare.parse_schema(schema_json, "json")
if 'error' in result:
    print(f"Parse error: {result['error']}")
else:
    schema = result['parsed_schema']
    print(f"Parsed {len(schema['rules'])} validation rules")
```

## Compliance Validation Functions

### validateCompliance
Perform compliance checking using schema rules against DICOM data.

```python
def validate_compliance(
    dicom_data: dict, 
    schema_content: str, 
    format: str = "json"
) -> dict:
    """
    Validate DICOM data compliance against schema rules.
    
    Args:
        dicom_data: AnalysisResult from analyze_dicom_files
        schema_content: Schema content as string
        format: Schema format ("json" or "python")
        
    Returns:
        Dict with 'compliance_report' containing ComplianceReport or 'error' message
        
    Raises:
        ValidationError: If validation process fails
    """
```

**Example:**
```python
# Analyze DICOM files first
dicom_result = dicompare.analyze_dicom_files(file_data)

# Schema content from repository file or user upload
schema_content = '''
{
    "metadata": {"name": "Brain MRI Protocol"},
    "acquisitions": {
        "t1_weighted": {
            "fields": [
                {"tag": "0008,0060", "validation_rule": {"type": "exact", "value": "MR"}}
            ]
        }
    }
}
'''

# Validate compliance
result = dicompare.validate_compliance(dicom_result, schema_content, "json")

if 'error' in result:
    print(f"Validation error: {result['error']}")
else:
    report = result['compliance_report']
    print(f"Overall status: {report['overallStatus']}")
    print(f"Passed: {report['summary']['passed']}/{report['summary']['total']}")
```

## Field Dictionary Functions

### getFieldInfo
Get comprehensive information about a specific DICOM field.

```python
def get_field_info(tag: str) -> FieldDictionary:
    """
    Get comprehensive field information from DICOM dictionary.
    
    Args:
        tag: DICOM tag in format "0008,0060" or "00080060"
        
    Returns:
        FieldDictionary with complete field information
        
    Raises:
        TagNotFoundError: If DICOM tag is not found in dictionary
    """
```

**Example:**
```python
field_info = dicompare.get_field_info("0008,0060")
print(f"Field: {field_info['name']}")
print(f"VR: {field_info['vr']}")
print(f"Description: {field_info['description']}")
```

### searchFields
Search DICOM fields by name, tag, or keyword.

```python
def search_fields(query: str, limit: int = 20) -> List[FieldDictionary]:
    """
    Search DICOM fields by name, tag, or keyword.
    
    Args:
        query: Search term (partial names, tags, or keywords)
        limit: Maximum number of results to return
        
    Returns:
        List of matching FieldDictionary entries, ranked by relevance
        
    Raises:
        SearchError: If search query is invalid
    """
```

**Example:**
```python
# Search by name
results = dicompare.search_fields("modality", limit=10)
for field in results:
    print(f"{field['tag']}: {field['name']}")

# Search by tag
results = dicompare.search_fields("0008", limit=5)
```

## Repository Schema Loading

Validation schemas are stored as JSON files in the repository and loaded directly by the frontend:

**Repository Structure:**
```
/public/schemas/
  ├── index.json                 # List of available schemas
  ├── brain_mri_basic.json      # Individual schema files
  ├── cardiac_cine.json
  └── diffusion_tensor.json
```

**Schema File Format:**
```json
{
  "metadata": {
    "id": "brain_mri_basic",
    "name": "Brain MRI Basic Protocol",
    "description": "Standard brain MRI validation",
    "version": "1.0",
    "authors": ["Neuroimaging Working Group"],
    "category": "Neuroimaging"
  },
  "acquisitions": {
    "t1_weighted": {
      "name": "T1 Weighted",
      "fields": [
        {
          "tag": "0008,0060",
          "name": "Modality",
          "required": true,
          "validation_rule": {"type": "exact", "value": "MR"}
        }
      ]
    }
  }
}
```

**Frontend Loading:**
```typescript
// Load schema list
const schemaIndex = await fetch('/schemas/index.json');
const availableSchemas = await schemaIndex.json();

// Load specific schema
const schemaResponse = await fetch(`/schemas/${schemaId}.json`);
const schema = await schemaResponse.json();
```

## Example and Demo Functions


### getExampleDicomData
Get example DICOM analysis data for demonstration.

```python
def get_example_dicom_data() -> AnalysisResult:
    """
    Get example DICOM data (same structure as analyze_dicom_files).
    
    Returns:
        AnalysisResult with realistic example data
    """
```

**Example:**
```python
example_data = dicompare.get_example_dicom_data()
print(f"Example has {len(example_data['acquisitions'])} acquisitions")
```

### analyzeFilesForUI (UI Wrapper)
Analyze files and return UI-formatted acquisitions.

```python
def analyze_files_for_ui(files: List[Dict[str, Any]]) -> List[dict]:
    """
    Wrapper around analyze_dicom_files that returns UI-formatted data.
    Converts snake_case to camelCase and flattens some structures.
    
    Args:
        files: List of file objects with structure:
               [{"name": "file1.dcm", "content": bytes}, ...]
        
    Returns:
        List of UI-formatted acquisition objects
    """
```

### getExampleDicomDataForUI (UI Wrapper)  
Get example DICOM data in UI format.

```python
def get_example_dicom_data_for_ui() -> List[dict]:
    """
    Wrapper around get_example_dicom_data that returns UI-formatted data.
    
    Returns:
        List of UI-formatted acquisition objects
    """
```

### getSchemaFields
Get field requirements for a specific schema.

```python
def get_schema_fields(schema_id: str) -> List[FieldInfo]:
    """
    Get schema field requirements for a specific schema.
    
    Args:
        schema_id: Identifier of the schema
        
    Returns:
        List of FieldInfo objects representing required fields
        
    Raises:
        SchemaNotFoundError: If schema ID is not found
    """
```

**Example:**
```python
fields = dicompare.get_schema_fields("clinical_research_v1")
for field in fields:
    print(f"{field['name']} ({field['tag']}): {field['validation_rule']}")
```

## Data Type Definitions

### FieldDictionary
Complete information about a DICOM field from the data dictionary.

```typescript
interface FieldDictionary {
  tag: string;                    // DICOM tag
  name: string;                   // Official field name
  keyword: string;                // DICOM keyword
  vr: string;                     // Value Representation
  vm: string;                     // Value Multiplicity
  description: string;            // Detailed description
  suggested_data_type: string;    // Recommended data type for validation
  suggested_validation: string;   // Recommended validation approach
  common_values: any[];          // Commonly seen values
  validation_hints?: {
    tolerance_typical?: number;   // Typical tolerance for numeric fields
    range_typical?: [number, number]; // Typical range for numeric fields
  };
}
```

### ValidationTemplate
Generated validation template with statistics.

```typescript
interface ValidationTemplate {
  template: {
    version: string;
    name: string;
    description: string;
    created: string;
    acquisitions: any[];
    global_constraints: Record<string, any>;
  };
  statistics: {
    total_acquisitions: number;
    total_validation_fields: number;
    estimated_validation_time: string;
  };
}
```

### ComplianceReport
Detailed compliance validation results.

```typescript
interface ComplianceReport {
  schemaId: string;
  timestamp: string;
  overallStatus: 'pass' | 'fail' | 'warning';
  fieldResults: ComplianceFieldResult[];
  summary: {
    total: number;
    passed: number;
    failed: number;
    warnings: number;
  };
}

interface ComplianceFieldResult {
  fieldPath: string;
  fieldName: string;
  status: 'pass' | 'fail' | 'warning' | 'unknown';
  expectedValue?: any;
  actualValue?: any;
  message?: string;
  rule?: ValidationRule;
}
```

## Field Naming Conventions

The Python API uses snake_case naming conventions, while the TypeScript UI uses camelCase. The UI wrapper functions handle this conversion:

**Python API (snake_case):**
- `protocol_name`, `series_description`, `total_files`
- `acquisition_fields`, `series_fields`
- `field_values`, `data_type`, `validation_rule`

**TypeScript UI (camelCase):**
- `protocolName`, `seriesDescription`, `totalFiles`
- `acquisitionFields`, `seriesFields`  
- `fields`, `dataType`, `validationRule`

## Error Handling

All API functions should handle errors gracefully and return structured error information:

```python
# For functions returning analysis results
{
    "error": "Error message describing what went wrong",
    "error_type": "ValidationError|DicomError|SchemaParseError|TagNotFoundError",
    "details": {
        "file_path": "/path/to/problematic/file",
        "line_number": 42,
        "additional_context": "..."
    }
}
```

## Performance Considerations

- **File Analysis**: Should handle 1000+ DICOM files efficiently
- **Memory Usage**: Stream processing for large datasets  
- **Caching**: Cache field dictionary lookups and parsed schemas
- **Progress Reporting**: Provide progress callbacks for long operations
- **Async Support**: Support for asynchronous processing where beneficial

## API Usage Patterns

### Complete Workflow Example
```python
# 1. Analyze DICOM files
dicom_files = ["/data/study/series1/img001.dcm", "/data/study/series1/img002.dcm"]
analysis = dicompare.analyze_dicom_files(dicom_files)

# 2. Configure acquisitions with validation rules
configured_acquisitions = []
for acq in analysis['acquisitions']:
    # Add validation rules to fields
    for field in acq['acquisition_fields']:
        if field['consistency'] == 'constant':
            field['validation_rule'] = {
                "type": "exact",
                "value": field['value']
            }
    configured_acquisitions.append(acq)

# 3. Generate validation template
template_metadata = {
    "name": "My Validation Template",
    "version": "1.0",
    "description": "Custom validation template"
}
template = dicompare.generate_validation_template(configured_acquisitions, template_metadata)

# 4. Frontend converts template to downloadable file
schema_content = json.dumps(template['template'], indent=2)
# Browser creates downloadable file using Blob API

# 5. Use template for compliance checking  
compliance = dicompare.validate_compliance(analysis, schema_content, "json")

print(f"Compliance status: {compliance['compliance_report']['overallStatus']}")
```

## Template File Generation

The Python API generates template objects in memory. The frontend is responsible for converting these to downloadable files:

**Template Generation Flow:**
```typescript
// 1. Generate template via Python API
const templateObj = await dicompareAPI.generateTemplate(acquisitions, metadata);

// 2. Convert to JSON for download (frontend responsibility)
const jsonContent = JSON.stringify(templateObj.template, null, 2);
const blob = new Blob([jsonContent], { type: 'application/json' });
const downloadUrl = URL.createObjectURL(blob);

// 3. Trigger download
const link = document.createElement('a');
link.href = downloadUrl;
link.download = `${templateName}.json`;
link.click();
```

**Python Template Generation (backend only):**
```python
# Generate Python validation script content
python_content = f'''
"""
{template_name} - Version {version}
{description}
"""

class DicomValidator:
    def __init__(self):
        self.template = {json.dumps(template_obj, indent=8)}
    
    def validate_acquisition(self, dicom_data, acquisition_type):
        # Validation logic here
        pass
'''

# Return as downloadable content
return {"template": template_obj, "python_script": python_content}
```

This API specification provides the foundation for a robust DICOM validation and compliance checking system with comprehensive analysis, flexible template generation, and detailed compliance reporting capabilities.