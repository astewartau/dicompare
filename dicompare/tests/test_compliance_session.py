"""
Unit tests for dicompare.compliance_session module.
"""

import unittest
import pandas as pd
import numpy as np
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

from dicompare.compliance_session import ComplianceSession


class TestComplianceSession(unittest.TestCase):
    """Test cases for ComplianceSession class."""
    
    def setUp(self):
        """Set up test data."""
        # Create sample session DataFrame
        self.session_df = pd.DataFrame({
            'Acquisition': ['T1_MPRAGE'] * 3 + ['T2_FLAIR'] * 2,
            'DICOM_Path': [f'/path/{i}.dcm' for i in range(5)],
            'RepetitionTime': [2000, 2000, 2000, 9000, 9000],
            'EchoTime': [0.01, 0.01, 0.01, 0.1, 0.1],
            'FlipAngle': [30, 30, 30, 90, 90],
            'InstanceNumber': [1, 2, 3, 1, 2],
            'SliceThickness': [1.0, 1.0, 1.0, 3.0, 3.0]
        })
        
        # Sample schema
        self.test_schema = {
            'name': 'Test Schema',
            'acquisitions': {
                't1mprage': {
                    'fields': [
                        {'field': 'RepetitionTime', 'value': 2000},
                        {'field': 'EchoTime', 'value': 0.01}
                    ],
                    'series': []
                },
                't2flair': {
                    'fields': [
                        {'field': 'RepetitionTime', 'value': 9000},
                        {'field': 'EchoTime', 'value': 0.1}
                    ],
                    'series': []
                }
            }
        }
        
        self.session = ComplianceSession()
    
    def test_initialization(self):
        """Test ComplianceSession initialization."""
        session = ComplianceSession()
        
        self.assertIsNone(session.session_df)
        self.assertEqual(session.schemas, {})
        self.assertEqual(session.compliance_results, {})
        self.assertEqual(session.session_metadata, {})
        
        self.assertFalse(session.has_session())
        self.assertEqual(session.get_schema_names(), [])
    
    def test_load_dicom_session_basic(self):
        """Test loading DICOM session."""
        metadata = {'source': 'test_study', 'date': '2023-01-01'}
        
        self.session.load_dicom_session(self.session_df, metadata)
        
        self.assertTrue(self.session.has_session())
        self.assertEqual(len(self.session.session_df), 5)
        self.assertEqual(self.session.session_metadata, metadata)
        
        # Should have cleared any previous results
        self.assertEqual(self.session.compliance_results, {})
    
    def test_load_dicom_session_validation(self):
        """Test session loading validation."""
        # Empty DataFrame
        with self.assertRaises(ValueError) as cm:
            self.session.load_dicom_session(pd.DataFrame())
        self.assertIn("empty", str(cm.exception))
        
        # Missing Acquisition column
        bad_df = pd.DataFrame({'RepetitionTime': [2000, 2000]})
        with self.assertRaises(ValueError) as cm:
            self.session.load_dicom_session(bad_df)
        self.assertIn("Acquisition", str(cm.exception))
    
    def test_add_schema(self):
        """Test adding schema."""
        self.session.add_schema('test_schema', self.test_schema)
        
        self.assertTrue(self.session.has_schema('test_schema'))
        self.assertEqual(self.session.get_schema_names(), ['test_schema'])
        self.assertEqual(self.session.schemas['test_schema'], self.test_schema)
    
    def test_add_schema_from_dict(self):
        """Test adding schema from dictionary (backwards compatibility)."""
        self.session.add_schema_from_dict(self.test_schema, 'test_schema')
        
        self.assertTrue(self.session.has_schema('test_schema'))
        self.assertEqual(self.session.get_schema_names(), ['test_schema'])
        self.assertEqual(self.session.schemas['test_schema'], self.test_schema)
    
    def test_add_schema_from_file(self):
        """Test adding schema from JSON file."""
        # Create temporary JSON file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.test_schema, f)
            temp_path = f.name
        
        try:
            self.session.add_schema_from_file(temp_path)
            
            # Should use filename as schema name
            expected_name = Path(temp_path).stem
            self.assertTrue(self.session.has_schema(expected_name))
            self.assertEqual(self.session.schemas[expected_name], self.test_schema)
        finally:
            Path(temp_path).unlink()
    
    def test_add_schema_from_file_custom_name(self):
        """Test adding schema from file with custom name."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.test_schema, f)
            temp_path = f.name
        
        try:
            self.session.add_schema_from_file(temp_path, 'custom_name')
            
            self.assertTrue(self.session.has_schema('custom_name'))
            self.assertFalse(self.session.has_schema(Path(temp_path).stem))
        finally:
            Path(temp_path).unlink()
    
    def test_add_schema_from_file_errors(self):
        """Test schema file loading error handling."""
        # Non-existent file
        with self.assertRaises(FileNotFoundError):
            self.session.add_schema_from_file('/nonexistent/file.json')
        
        # Invalid JSON
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('invalid json content')
            temp_path = f.name
        
        try:
            with self.assertRaises(json.JSONDecodeError):
                self.session.add_schema_from_file(temp_path)
        finally:
            Path(temp_path).unlink()
    
    def test_generate_schema_from_session(self):
        """Test generating schema from session."""
        self.session.load_dicom_session(self.session_df)
        
        schema = self.session.generate_schema_from_session('auto_schema')
        
        # Should create and store schema
        self.assertTrue(self.session.has_schema('auto_schema'))
        
        # Schema should have expected structure
        self.assertIn('acquisitions', schema)
        self.assertIn('name', schema)
        self.assertEqual(schema['name'], 'auto_schema')
        self.assertIn('generated_from', schema)
        
        # Should include both acquisitions
        acquisitions = schema['acquisitions']
        self.assertIn('t1mprage', acquisitions)  # clean_string('T1_MPRAGE')
        self.assertIn('t2flair', acquisitions)   # clean_string('T2_FLAIR')
    
    def test_generate_schema_from_session_custom_fields(self):
        """Test schema generation with custom fields."""
        self.session.load_dicom_session(self.session_df)
        
        custom_fields = ['RepetitionTime', 'EchoTime']
        schema = self.session.generate_schema_from_session(
            'custom_schema', reference_fields=custom_fields
        )
        
        self.assertEqual(schema['fields_used'], custom_fields)
    
    def test_generate_schema_from_session_specific_acquisitions(self):
        """Test schema generation for specific acquisitions."""
        self.session.load_dicom_session(self.session_df)
        
        schema = self.session.generate_schema_from_session(
            'partial_schema', acquisitions=['T1_MPRAGE']
        )
        
        # Should only include T1_MPRAGE
        acquisitions = schema['acquisitions']
        self.assertIn('t1mprage', acquisitions)
        self.assertNotIn('t2flair', acquisitions)
        self.assertEqual(schema['total_files'], 3)
    
    def test_generate_schema_from_session_no_session(self):
        """Test schema generation without loaded session."""
        with self.assertRaises(ValueError) as cm:
            self.session.generate_schema_from_session('test')
        self.assertIn("No session loaded", str(cm.exception))
    
    def test_check_compliance(self):
        """Test compliance checking with user mapping."""
        self.session.load_dicom_session(self.session_df)
        self.session.add_schema('test_schema', self.test_schema)
        
        # Create user mapping
        user_mapping = {
            't1mprage': 'T1_MPRAGE',
            't2flair': 'T2_FLAIR'
        }
        
        results = self.session.check_compliance('test_schema', user_mapping)
        
        # Should return formatted results
        self.assertIn('summary', results)
        self.assertIn('acquisition_details', results)
        
        # Should store results internally
        self.assertTrue(self.session.has_results('test_schema'))
        
        # Summary should have expected structure
        summary = results['summary']
        self.assertIn('total_acquisitions', summary)
        self.assertIn('compliant_acquisitions', summary)
        self.assertIn('compliance_rate', summary)
    
    def test_check_compliance_errors(self):
        """Test compliance checking error handling."""
        user_mapping = {'t1mprage': 'T1_MPRAGE'}
        
        # No session loaded
        self.session.add_schema('test_schema', self.test_schema)
        
        with self.assertRaises(ValueError) as cm:
            self.session.check_compliance('test_schema', user_mapping)
        self.assertIn("No session loaded", str(cm.exception))
        
        # Schema not found
        self.session.load_dicom_session(self.session_df)
        
        with self.assertRaises(ValueError) as cm:
            self.session.check_compliance('nonexistent', user_mapping)
        self.assertIn("Schema 'nonexistent' not found", str(cm.exception))
        
        # Empty mapping
        with self.assertRaises(ValueError) as cm:
            self.session.check_compliance('test_schema', {})
        self.assertIn("User mapping cannot be empty", str(cm.exception))
        
        # Invalid schema acquisition in mapping
        with self.assertRaises(ValueError) as cm:
            self.session.check_compliance('test_schema', {'invalid_acq': 'T1_MPRAGE'})
        self.assertIn("Schema acquisition 'invalid_acq' not found", str(cm.exception))
        
        # Invalid session acquisition in mapping
        with self.assertRaises(ValueError) as cm:
            self.session.check_compliance('test_schema', {'t1mprage': 'INVALID_ACQ'})
        self.assertIn("Session acquisition 'INVALID_ACQ' not found", str(cm.exception))
    
    def test_check_compliance_all(self):
        """Test checking compliance against all schemas."""
        self.session.load_dicom_session(self.session_df)
        
        # Add multiple schemas
        self.session.add_schema('schema1', self.test_schema)
        self.session.add_schema('schema2', self.test_schema)
        
        # Create user mappings for both schemas
        user_mappings = {
            'schema1': {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'},
            'schema2': {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        }
        
        results = self.session.check_compliance_all(user_mappings)
        
        # Should return results for all schemas
        self.assertIn('schema1', results)
        self.assertIn('schema2', results)
        
        # Each result should have expected structure
        for schema_name, result in results.items():
            if 'error' not in result:  # Skip failed results
                self.assertIn('summary', result)
                self.assertIn('acquisition_details', result)
    
    def test_check_compliance_all_no_schemas(self):
        """Test checking compliance when no schemas are loaded."""
        self.session.load_dicom_session(self.session_df)
        
        results = self.session.check_compliance_all({})
        self.assertEqual(results, {})
    
    def test_check_compliance_all_missing_mapping(self):
        """Test checking compliance when some mappings are missing."""
        self.session.load_dicom_session(self.session_df)
        
        # Add multiple schemas but only provide mapping for one
        self.session.add_schema('schema1', self.test_schema)
        self.session.add_schema('schema2', self.test_schema)
        
        user_mappings = {
            'schema1': {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
            # Missing mapping for schema2
        }
        
        results = self.session.check_compliance_all(user_mappings)
        
        # Should have results for schema1, skipped for schema2
        self.assertIn('schema1', results)
        self.assertIn('schema2', results)
        
        # schema1 should have proper results
        self.assertIn('summary', results['schema1'])
        
        # schema2 should be skipped
        self.assertEqual(results['schema2']['status'], 'skipped')
        self.assertIn('No user mapping provided', results['schema2']['error'])
    
    def test_get_session_summary(self):
        """Test getting session summary."""
        # No session loaded
        summary = self.session.get_session_summary()
        self.assertEqual(summary['status'], 'no_session')
        
        # With session loaded
        self.session.load_dicom_session(self.session_df, {'test': 'metadata'})
        self.session.add_schema_from_dict(self.test_schema, 'test_schema')
        
        summary = self.session.get_session_summary()
        
        self.assertEqual(summary['status'], 'loaded')
        self.assertIn('session', summary)
        self.assertIn('schemas', summary)
        self.assertIn('compliance_summary', summary)
        self.assertIn('metadata', summary)
        
        # Check session info
        session_info = summary['session']
        self.assertIn('session_characteristics', session_info)
        
        # Check schema info
        schemas_info = summary['schemas']
        self.assertIn('test_schema', schemas_info)
        self.assertEqual(schemas_info['test_schema']['acquisition_count'], 2)
    
    def test_export_results(self):
        """Test exporting compliance results."""
        self.session.load_dicom_session(self.session_df)
        self.session.add_schema_from_dict(self.test_schema, 'test_schema')
        
        # Run compliance check to generate results
        user_mapping = {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        self.session.check_compliance('test_schema', user_mapping)
        
        # Export specific schema results
        export_data = self.session.export_results('test_schema')
        
        self.assertEqual(export_data['schema_name'], 'test_schema')
        self.assertIn('results', export_data)
        self.assertIn('session_metadata', export_data)
        self.assertIn('export_timestamp', export_data)
        
        # Export all results
        all_export = self.session.export_results()
        
        self.assertIn('all_results', all_export)
        self.assertIn('schemas', all_export)
        self.assertIn('session_summary', all_export)
    
    def test_export_results_errors(self):
        """Test export results error handling."""
        with self.assertRaises(ValueError) as cm:
            self.session.export_results('nonexistent')
        self.assertIn("No results found", str(cm.exception))
    
    def test_clear_results(self):
        """Test clearing compliance results."""
        self.session.load_dicom_session(self.session_df)
        self.session.add_schema_from_dict(self.test_schema, 'schema1')
        self.session.add_schema_from_dict(self.test_schema, 'schema2')
        
        # Generate some results
        user_mapping = {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        self.session.check_compliance('schema1', user_mapping)
        self.session.check_compliance('schema2', user_mapping)
        
        # Clear specific results
        self.session.clear_results('schema1')
        self.assertFalse(self.session.has_results('schema1'))
        self.assertTrue(self.session.has_results('schema2'))
        
        # Clear all results
        self.session.clear_results()
        self.assertFalse(self.session.has_results('schema2'))
        self.assertEqual(self.session.compliance_results, {})
    
    def test_remove_schema(self):
        """Test removing schemas."""
        self.session.add_schema('test_schema', self.test_schema)
        self.session.load_dicom_session(self.session_df)
        user_mapping = {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        self.session.check_compliance('test_schema', user_mapping)
        
        # Should have schema and results
        self.assertTrue(self.session.has_schema('test_schema'))
        self.assertTrue(self.session.has_results('test_schema'))
        
        # Remove schema
        self.session.remove_schema('test_schema')
        
        # Should remove both schema and results
        self.assertFalse(self.session.has_schema('test_schema'))
        self.assertFalse(self.session.has_results('test_schema'))
    
    def test_session_state_management(self):
        """Test session state management methods."""
        # Initial state
        self.assertFalse(self.session.has_session())
        self.assertEqual(self.session.get_schema_names(), [])
        
        # Add schema
        self.session.add_schema('test', self.test_schema)
        self.assertTrue(self.session.has_schema('test'))
        self.assertFalse(self.session.has_results('test'))
        
        # Load session
        self.session.load_dicom_session(self.session_df)
        self.assertTrue(self.session.has_session())
        
        # Run compliance
        user_mapping = {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        self.session.check_compliance('test', user_mapping)
        self.assertTrue(self.session.has_results('test'))
    
    def test_real_world_workflow(self):
        """Test a realistic end-to-end workflow."""
        # Step 1: Load DICOM session
        metadata = {
            'study_id': 'STUDY_001',
            'patient_id': 'PAT_123',
            'scan_date': '2023-01-15'
        }
        self.session.load_dicom_session(self.session_df, metadata)
        
        # Step 2: Generate schema from session
        auto_schema = self.session.generate_schema_from_session(
            'auto_generated',
            reference_fields=['RepetitionTime', 'EchoTime', 'FlipAngle']
        )
        
        # Step 3: Add external schema
        self.session.add_schema('external_schema', self.test_schema)
        
        # Step 4: Check compliance against all schemas
        user_mappings = {
            'auto_generated': {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'},
            'external_schema': {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        }
        all_results = self.session.check_compliance_all(user_mappings)
        
        # Verify we have results for both schemas
        self.assertEqual(len(all_results), 2)
        self.assertIn('auto_generated', all_results)
        self.assertIn('external_schema', all_results)
        
        # Step 5: Get comprehensive summary
        summary = self.session.get_session_summary()
        
        self.assertEqual(summary['status'], 'loaded')
        self.assertEqual(len(summary['schemas']), 2)
        self.assertEqual(len(summary['compliance_summary']), 2)
        
        # Step 6: Export results
        export_data = self.session.export_results()
        
        self.assertIn('all_results', export_data)
        self.assertEqual(len(export_data['all_results']), 2)
        
        # Verify metadata is preserved
        self.assertEqual(export_data['session_summary']['metadata'], metadata)
    
    def test_edge_cases_and_error_handling(self):
        """Test various edge cases and error conditions."""
        # Adding duplicate schema names (should overwrite)
        self.session.add_schema('duplicate', {'test': 1})
        self.session.add_schema('duplicate', {'test': 2})
        self.assertEqual(self.session.schemas['duplicate'], {'test': 2})
        
        # Loading session multiple times (should clear previous results)
        self.session.load_dicom_session(self.session_df)
        self.session.add_schema('test', self.test_schema)
        user_mapping = {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        self.session.check_compliance('test', user_mapping)
        
        # Load different session - should clear results
        new_df = self.session_df.copy()
        new_df['NewField'] = 'value'
        self.session.load_dicom_session(new_df)
        
        self.assertFalse(self.session.has_results('test'))
        
        # Schema operations on empty schema names
        self.assertFalse(self.session.has_schema(''))
        self.assertFalse(self.session.has_results(''))
    
    def test_json_serialization_compatibility(self):
        """Test that all exported data is JSON serializable."""
        self.session.load_dicom_session(self.session_df)
        self.session.add_schema('test', self.test_schema)
        user_mapping = {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        self.session.check_compliance('test', user_mapping)
        
        # Test session summary
        summary = self.session.get_session_summary()
        json_str = json.dumps(summary)  # Should not raise
        loaded = json.loads(json_str)
        self.assertIn('session', loaded)
        
        # Test export data
        export_data = self.session.export_results()
        json_str = json.dumps(export_data)  # Should not raise
        loaded = json.loads(json_str)
        self.assertIn('all_results', loaded)
    
    def test_get_schema_acquisitions(self):
        """Test getting schema acquisition names."""
        self.session.add_schema('test_schema', self.test_schema)
        
        acquisitions = self.session.get_schema_acquisitions('test_schema')
        self.assertEqual(set(acquisitions), {'t1mprage', 't2flair'})
        
        # Test with non-existent schema
        with self.assertRaises(ValueError) as cm:
            self.session.get_schema_acquisitions('nonexistent')
        self.assertIn("Schema 'nonexistent' not found", str(cm.exception))
    
    def test_get_session_acquisitions(self):
        """Test getting session acquisition names."""
        self.session.load_dicom_session(self.session_df)
        
        acquisitions = self.session.get_session_acquisitions()
        self.assertEqual(set(acquisitions), {'T1_MPRAGE', 'T2_FLAIR'})
        
        # Test without loaded session
        session = ComplianceSession()
        with self.assertRaises(ValueError) as cm:
            session.get_session_acquisitions()
        self.assertIn("No session loaded", str(cm.exception))
    
    def test_get_schema_info(self):
        """Test getting detailed schema information."""
        self.session.add_schema('test_schema', self.test_schema)
        
        info = self.session.get_schema_info('test_schema')
        
        self.assertEqual(info['schema_id'], 'test_schema')
        self.assertEqual(info['acquisition_count'], 2)
        self.assertEqual(set(info['acquisitions']), {'t1mprage', 't2flair'})
        self.assertFalse(info['has_results'])
        
        # Test with non-existent schema
        with self.assertRaises(ValueError) as cm:
            self.session.get_schema_info('nonexistent')
        self.assertIn("Schema 'nonexistent' not found", str(cm.exception))
    
    def test_validate_user_mapping(self):
        """Test user mapping validation."""
        self.session.load_dicom_session(self.session_df)
        self.session.add_schema('test_schema', self.test_schema)
        
        # Valid mapping
        valid_mapping = {'t1mprage': 'T1_MPRAGE', 't2flair': 'T2_FLAIR'}
        result = self.session.validate_user_mapping('test_schema', valid_mapping)
        
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['errors']), 0)
        self.assertEqual(result['mapping_coverage']['schema_coverage'], 1.0)
        self.assertEqual(result['mapping_coverage']['session_coverage'], 1.0)
        
        # Partial mapping
        partial_mapping = {'t1mprage': 'T1_MPRAGE'}
        result = self.session.validate_user_mapping('test_schema', partial_mapping)
        
        self.assertTrue(result['valid'])  # Still valid, just partial
        self.assertEqual(len(result['warnings']), 2)  # Unmapped acquisitions
        self.assertEqual(result['mapping_coverage']['schema_coverage'], 0.5)
        self.assertEqual(result['mapping_coverage']['session_coverage'], 0.5)
        
        # Invalid schema acquisition
        invalid_mapping = {'invalid_acq': 'T1_MPRAGE'}
        result = self.session.validate_user_mapping('test_schema', invalid_mapping)
        
        self.assertFalse(result['valid'])
        self.assertGreater(len(result['errors']), 0)
        self.assertIn("Schema acquisition 'invalid_acq' not found", result['errors'][0])
        
        # Invalid session acquisition
        invalid_mapping = {'t1mprage': 'INVALID_SESSION_ACQ'}
        result = self.session.validate_user_mapping('test_schema', invalid_mapping)
        
        self.assertFalse(result['valid'])
        self.assertGreater(len(result['errors']), 0)
        self.assertIn("Session acquisition 'INVALID_SESSION_ACQ' not found", result['errors'][0])
    
    def test_suggest_automatic_mapping(self):
        """Test automatic mapping suggestions."""
        self.session.load_dicom_session(self.session_df)
        self.session.add_schema('test_schema', self.test_schema)
        
        suggestions = self.session.suggest_automatic_mapping('test_schema')
        
        # Should suggest mappings based on name similarity
        # Note: exact suggestions depend on the matching algorithm
        self.assertIsInstance(suggestions, dict)
        
        # Test with exact match schema
        exact_match_schema = {
            'acquisitions': {
                'T1_MPRAGE': {'fields': []},
                'T2_FLAIR': {'fields': []}
            }
        }
        self.session.add_schema('exact_match', exact_match_schema)
        
        suggestions = self.session.suggest_automatic_mapping('exact_match')
        self.assertEqual(suggestions['T1_MPRAGE'], 'T1_MPRAGE')
        self.assertEqual(suggestions['T2_FLAIR'], 'T2_FLAIR')
        
        # Test with no session loaded
        session = ComplianceSession()
        session.add_schema('test', self.test_schema)
        
        with self.assertRaises(ValueError) as cm:
            session.suggest_automatic_mapping('test')
        self.assertIn("No session loaded", str(cm.exception))


if __name__ == '__main__':
    unittest.main()