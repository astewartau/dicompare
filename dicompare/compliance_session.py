"""
Compliance session management for dicompare.

This module provides the ComplianceSession class for managing
DICOM compliance validation workflows with multiple schemas.
"""

import pandas as pd
from typing import Dict, List, Any, Optional, Union
import json
import logging
from pathlib import Path

from .compliance import check_session_compliance_with_json_schema
from .generate_schema import create_json_schema
from .web_utils import format_compliance_results_for_web, prepare_session_for_web
from .serialization import make_json_serializable
from .utils import filter_available_fields
from .config import DEFAULT_SETTINGS_FIELDS

logger = logging.getLogger(__name__)


class ComplianceSession:
    """
    Manage DICOM compliance validation workflows with user-controlled schema mappings.
    
    This class provides a schema library and supports user-driven compliance checking
    where users manually map schema acquisitions to actual session acquisitions.
    Designed to work with web interfaces where users control the mapping process.
    
    Examples:
        >>> session = ComplianceSession()
        >>> session.load_dicom_session(session_df)
        >>> session.add_schema('my_schema', schema_dict)
        >>> user_mapping = {'schema_t1': 'T1_MPRAGE', 'schema_t2': 'T2_FLAIR'}
        >>> results = session.check_compliance('my_schema', user_mapping)
    """
    
    def __init__(self):
        """Initialize a new compliance session."""
        self.session_df: Optional[pd.DataFrame] = None
        self.schemas: Dict[str, Dict[str, Any]] = {}  # schema_id -> schema_dict
        self.compliance_results: Dict[str, Dict[str, Any]] = {}  # schema_id -> results
        self.session_metadata: Dict[str, Any] = {}
        
    def load_dicom_session(self, session_df: pd.DataFrame, metadata: Optional[Dict[str, Any]] = None):
        """
        Load a DICOM session DataFrame.
        
        Args:
            session_df: DataFrame containing DICOM session data
            metadata: Optional metadata about the session
            
        Raises:
            ValueError: If session_df is empty or missing required columns
            
        Examples:
            >>> session.load_dicom_session(df, {'source': 'clinical_study'})
        """
        if session_df.empty:
            raise ValueError("Session DataFrame cannot be empty")
            
        if 'Acquisition' not in session_df.columns:
            raise ValueError("Session DataFrame must contain 'Acquisition' column")
            
        self.session_df = session_df.copy()
        self.session_metadata = metadata or {}
        
        # Clear previous results
        self.compliance_results.clear()
        
        logger.info(f"Loaded DICOM session with {len(session_df)} files, "
                   f"{session_df['Acquisition'].nunique()} acquisitions")
    
    def add_schema(self, schema_id: str, schema_dict: Dict[str, Any]):
        """
        Add a schema to the library.
        
        Args:
            schema_id: Unique identifier for this schema
            schema_dict: Schema dictionary
            
        Examples:
            >>> schema = {'acquisitions': {'t1': {'fields': [...]}}}
            >>> session.add_schema('my_schema', schema)
        """
        self.schemas[schema_id] = schema_dict.copy()
        
        # Clear any existing results for this schema
        if schema_id in self.compliance_results:
            del self.compliance_results[schema_id]
            
        logger.info(f"Added schema '{schema_id}' with {len(schema_dict.get('acquisitions', {}))} acquisitions")
    
    def add_schema_from_dict(self, schema_dict: Dict[str, Any], schema_name: str):
        """
        Add a schema from a dictionary (backwards compatibility).
        
        Args:
            schema_dict: Schema dictionary
            schema_name: Name to identify this schema
            
        Examples:
            >>> schema = {'acquisitions': {'t1': {'fields': [...]}}}
            >>> session.add_schema_from_dict(schema, 'my_schema')
        """
        self.add_schema(schema_name, schema_dict)
    
    def add_schema_from_file(self, file_path: Union[str, Path], schema_name: Optional[str] = None):
        """
        Add a schema from a JSON file.
        
        Args:
            file_path: Path to JSON schema file
            schema_name: Optional name (defaults to filename)
            
        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If file is not valid JSON
            
        Examples:
            >>> session.add_schema_from_file('/path/to/schema.json')
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Schema file not found: {file_path}")
            
        if schema_name is None:
            schema_name = file_path.stem
            
        with open(file_path, 'r') as f:
            schema_dict = json.load(f)
            
        self.add_schema_from_dict(schema_dict, schema_name)
    
    def generate_schema_from_session(self, 
                                   schema_name: str,
                                   reference_fields: Optional[List[str]] = None,
                                   acquisitions: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Generate a new schema from the current session.
        
        Args:
            schema_name: Name for the generated schema
            reference_fields: Fields to include in schema (defaults to DEFAULT_SETTINGS_FIELDS)
            acquisitions: Specific acquisitions to include (defaults to all)
            
        Returns:
            Generated schema dictionary
            
        Raises:
            ValueError: If no session is loaded
            
        Examples:
            >>> schema = session.generate_schema_from_session('auto_schema')
            >>> session.check_compliance_with_schema('auto_schema')
        """
        if self.session_df is None:
            raise ValueError("No session loaded. Call load_dicom_session() first.")
            
        if reference_fields is None:
            reference_fields = DEFAULT_SETTINGS_FIELDS
            
        # Filter to specified acquisitions if provided
        df_to_use = self.session_df
        if acquisitions:
            df_to_use = self.session_df[self.session_df['Acquisition'].isin(acquisitions)]
            if df_to_use.empty:
                raise ValueError(f"No data found for acquisitions: {acquisitions}")
        
        # Filter to available fields
        try:
            available_fields = filter_available_fields(df_to_use, reference_fields)
        except ValueError as e:
            raise ValueError(f"No suitable fields found for schema generation: {e}")
        
        # Generate schema
        schema_dict = create_json_schema(df_to_use, available_fields)
        
        # Add metadata
        schema_dict.update({
            'name': schema_name,
            'generated_from': 'dicompare_session',
            'total_files': len(df_to_use),
            'acquisition_count': df_to_use['Acquisition'].nunique(),
            'fields_used': available_fields
        })
        
        # Store in session
        self.add_schema_from_dict(schema_dict, schema_name)
        
        return schema_dict
    
    def check_compliance(self, schema_id: str, user_mapping: Dict[str, str]) -> Dict[str, Any]:
        """
        Check compliance against a specific schema with user-provided mapping.
        
        Args:
            schema_id: ID of schema to check against  
            user_mapping: User-defined mapping from schema acquisition names to actual acquisition names
                         e.g., {'schema_t1': 'T1_MPRAGE', 'schema_t2': 'T2_FLAIR'}
            
        Returns:
            Compliance results dictionary
            
        Raises:
            ValueError: If no session loaded, schema not found, or invalid mapping
            
        Examples:
            >>> mapping = {'t1_acq': 'T1_MPRAGE', 't2_acq': 'T2_FLAIR'}
            >>> results = session.check_compliance('my_schema', mapping)
            >>> results['summary']['compliance_rate']
            85.5
        """
        if self.session_df is None:
            raise ValueError("No session loaded. Call load_dicom_session() first.")
            
        if schema_id not in self.schemas:
            raise ValueError(f"Schema '{schema_id}' not found. Available: {list(self.schemas.keys())}")
        
        if not user_mapping:
            raise ValueError("User mapping cannot be empty. Provide mapping from schema to actual acquisitions.")
        
        schema = self.schemas[schema_id]
        
        # Validate user mapping
        schema_acquisitions = set(schema.get('acquisitions', {}).keys())
        actual_acquisitions = set(self.session_df['Acquisition'].unique())
        
        # Check that all mapped schema acquisitions exist in the schema
        for schema_acq in user_mapping.keys():
            if schema_acq not in schema_acquisitions:
                raise ValueError(f"Schema acquisition '{schema_acq}' not found in schema. "
                               f"Available: {list(schema_acquisitions)}")
        
        # Check that all mapped actual acquisitions exist in the session
        for actual_acq in user_mapping.values():
            if actual_acq not in actual_acquisitions:
                raise ValueError(f"Session acquisition '{actual_acq}' not found in session. "
                               f"Available: {list(actual_acquisitions)}")
        
        # Use the user-provided mapping directly
        session_map = user_mapping.copy()
        
        # Perform compliance check
        raw_results = check_session_compliance_with_json_schema(self.session_df, schema, session_map)
        
        print(f"DEBUG ComplianceSession: raw_results length = {len(raw_results)}")
        series_results = [r for r in raw_results if r.get('series') is not None]
        print(f"DEBUG ComplianceSession: Found {len(series_results)} series results")
        if series_results:
            print(f"  First series result: {series_results[0]}")
        
        # Convert raw results list to the format expected by format_compliance_results_for_web
        # Group results by schema acquisition (not input acquisition)
        schema_acquisition_results = {}
        
        for result in raw_results:
            # Use schema acquisition as the key, not input acquisition
            schema_acq_name = result.get('schema acquisition', 'unknown')
            input_acq_name = result.get('input acquisition', 'unknown')
            
            if schema_acq_name not in schema_acquisition_results:
                schema_acquisition_results[schema_acq_name] = {
                    'compliant': True,
                    'compliance_percentage': 0,
                    'message': '',
                    'detailed_results': [],
                    'input_acquisition': input_acq_name  # Track which input acquisition this maps to
                }
            
            # Add to detailed results - fix: use 'value' instead of 'actual' to match compliance record structure
            detailed_result = {
                'field': result.get('field', ''),
                'expected': result.get('expected', ''),
                'actual': result.get('value', ''),  # Fixed: use 'value' key from compliance record
                'compliant': result.get('passed', False),
                'message': result.get('message', ''),
                'difference_score': 0  # Not provided by raw results
            }
            
            # Add series information if this is a series-level result
            if 'series' in result:
                detailed_result['series'] = result['series']
            
            schema_acquisition_results[schema_acq_name]['detailed_results'].append(detailed_result)
            
            # Update overall compliance for this acquisition
            if not result.get('passed', False):
                schema_acquisition_results[schema_acq_name]['compliant'] = False
        
        # Calculate compliance percentages
        for acq_name, acq_data in schema_acquisition_results.items():
            detailed = acq_data['detailed_results']
            if detailed:
                compliant_count = sum(1 for r in detailed if r['compliant'])
                acq_data['compliance_percentage'] = (compliant_count / len(detailed)) * 100
                
                if acq_data['compliant']:
                    acq_data['message'] = 'All fields compliant'
                else:
                    failed_count = len(detailed) - compliant_count
                    acq_data['message'] = f'{failed_count} field(s) non-compliant'
        
        # Create the expected format
        formatted_raw_results = {'schema acquisition': schema_acquisition_results}
        
        # Format for web display
        formatted_results = format_compliance_results_for_web(formatted_raw_results)
        
        # Debug: Check if series results survived formatting
        print(f"DEBUG ComplianceSession: After format_compliance_results_for_web")
        for acq_name, acq_data in formatted_results.get('acquisition_details', {}).items():
            detailed = acq_data.get('detailed_results', [])
            series_count = sum(1 for r in detailed if 'series' in r)
            print(f"  Acquisition '{acq_name}': {len(detailed)} results, {series_count} with series")
        
        # Store results
        self.compliance_results[schema_id] = {
            'raw_results': raw_results,
            'formatted_results': formatted_results,
            'schema_id': schema_id,
            'user_mapping': user_mapping.copy(),
            'timestamp': pd.Timestamp.now().isoformat()
        }
        
        logger.info(f"Completed compliance check against '{schema_id}': "
                   f"{formatted_results['summary']['compliance_rate']:.1f}% compliant")
        
        return formatted_results
    
    def check_compliance_all(self, user_mappings: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
        """
        Check compliance against all loaded schemas with user-provided mappings.
        
        Args:
            user_mappings: Dict mapping schema_id to user mapping for that schema
                          e.g., {'schema1': {'t1': 'T1_MPRAGE'}, 'schema2': {'t2': 'T2_FLAIR'}}
        
        Returns:
            Dict mapping schema names to compliance results
            
        Examples:
            >>> mappings = {
            ...     'schema1': {'t1': 'T1_MPRAGE', 't2': 'T2_FLAIR'},
            ...     'schema2': {'dwi': 'DWI_30dir'}
            ... }
            >>> all_results = session.check_compliance_all(mappings)
            >>> for schema_name, results in all_results.items():
            ...     print(f"{schema_name}: {results['summary']['compliance_rate']:.1f}%")
        """
        if not self.schemas:
            logger.warning("No schemas loaded for compliance checking")
            return {}
        
        results = {}
        for schema_name in self.schemas:
            try:
                if schema_name in user_mappings:
                    results[schema_name] = self.check_compliance(schema_name, user_mappings[schema_name])
                else:
                    logger.warning(f"No user mapping provided for schema '{schema_name}', skipping compliance check")
                    results[schema_name] = {
                        'error': f"No user mapping provided for schema '{schema_name}'",
                        'status': 'skipped'
                    }
            except Exception as e:
                logger.error(f"Error checking compliance with '{schema_name}': {e}")
                results[schema_name] = {
                    'error': str(e),
                    'status': 'failed'
                }
        
        return results
    
    def get_session_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the current session.
        
        Returns:
            Dict containing session summary information
            
        Examples:
            >>> summary = session.get_session_summary()
            >>> summary['session']['total_files']
            1024
        """
        if self.session_df is None:
            return {'error': 'No session loaded', 'status': 'no_session'}
        
        # Get basic session data
        session_data = prepare_session_for_web(self.session_df)
        
        # Add schema information
        schema_summary = {}
        for name, schema in self.schemas.items():
            schema_summary[name] = {
                'acquisition_count': len(schema.get('acquisitions', {})),
                'has_results': name in self.compliance_results,
                'schema_type': 'user_provided' if 'generated_from' not in schema else 'generated'
            }
        
        # Add compliance results summary
        compliance_summary = {}
        for name, results in self.compliance_results.items():
            if 'formatted_results' in results and 'summary' in results['formatted_results']:
                summary = results['formatted_results']['summary']
                compliance_summary[name] = {
                    'compliance_rate': summary.get('compliance_rate', 0),
                    'total_acquisitions': summary.get('total_acquisitions', 0),
                    'compliant_acquisitions': summary.get('compliant_acquisitions', 0),
                    'timestamp': results.get('timestamp')
                }
        
        return make_json_serializable({
            'session': session_data,
            'schemas': schema_summary,
            'compliance_summary': compliance_summary,
            'metadata': self.session_metadata,
            'status': 'loaded'
        })
    
    def export_results(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Export compliance results for download.
        
        Args:
            schema_name: Specific schema to export (if None, exports all)
            
        Returns:
            Dict containing exportable results
            
        Examples:
            >>> export_data = session.export_results('my_schema')
            >>> with open('results.json', 'w') as f:
            ...     json.dump(export_data, f, indent=2)
        """
        if schema_name:
            if schema_name not in self.compliance_results:
                raise ValueError(f"No results found for schema '{schema_name}'")
            
            return make_json_serializable({
                'schema_name': schema_name,
                'results': self.compliance_results[schema_name],
                'session_metadata': self.session_metadata,
                'export_timestamp': pd.Timestamp.now().isoformat()
            })
        else:
            # Export all results
            return make_json_serializable({
                'all_results': self.compliance_results,
                'schemas': self.schemas,
                'session_summary': self.get_session_summary(),
                'export_timestamp': pd.Timestamp.now().isoformat()
            })
    
    def clear_results(self, schema_name: Optional[str] = None):
        """
        Clear compliance results.
        
        Args:
            schema_name: Specific schema results to clear (if None, clears all)
            
        Examples:
            >>> session.clear_results('old_schema')  # Clear specific results
            >>> session.clear_results()              # Clear all results
        """
        if schema_name:
            if schema_name in self.compliance_results:
                del self.compliance_results[schema_name]
                logger.info(f"Cleared results for schema '{schema_name}'")
        else:
            self.compliance_results.clear()
            logger.info("Cleared all compliance results")
    
    def remove_schema(self, schema_name: str):
        """
        Remove a schema and its results.
        
        Args:
            schema_name: Name of schema to remove
            
        Examples:
            >>> session.remove_schema('outdated_schema')
        """
        if schema_name in self.schemas:
            del self.schemas[schema_name]
            logger.info(f"Removed schema '{schema_name}'")
        
        if schema_name in self.compliance_results:
            del self.compliance_results[schema_name]
            logger.info(f"Removed results for schema '{schema_name}'")
    
    def get_schema_names(self) -> List[str]:
        """
        Get list of loaded schema names.
        
        Returns:
            List of schema names
            
        Examples:
            >>> session.get_schema_names()
            ['user_schema', 'generated_schema', 'reference_schema']
        """
        return list(self.schemas.keys())
    
    def has_session(self) -> bool:
        """
        Check if a session is loaded.
        
        Returns:
            True if session is loaded, False otherwise
        """
        return self.session_df is not None
    
    def has_schema(self, schema_name: str) -> bool:
        """
        Check if a specific schema is loaded.
        
        Args:
            schema_name: Schema name to check
            
        Returns:
            True if schema exists, False otherwise
        """
        return schema_name in self.schemas
    
    def has_results(self, schema_name: str) -> bool:
        """
        Check if compliance results exist for a schema.
        
        Args:
            schema_name: Schema name to check
            
        Returns:
            True if results exist, False otherwise
        """
        return schema_name in self.compliance_results
    
    def get_schema_acquisitions(self, schema_id: str) -> List[str]:
        """
        Get list of acquisition names defined in a schema.
        
        Args:
            schema_id: ID of schema to query
            
        Returns:
            List of schema acquisition names
            
        Raises:
            ValueError: If schema not found
            
        Examples:
            >>> session.get_schema_acquisitions('my_schema')
            ['t1_mprage', 't2_flair', 'dwi']
        """
        if schema_id not in self.schemas:
            raise ValueError(f"Schema '{schema_id}' not found. Available: {list(self.schemas.keys())}")
        
        schema = self.schemas[schema_id]
        return list(schema.get('acquisitions', {}).keys())
    
    def get_session_acquisitions(self) -> List[str]:
        """
        Get list of acquisition names in the current session.
        
        Returns:
            List of session acquisition names
            
        Raises:
            ValueError: If no session is loaded
            
        Examples:
            >>> session.get_session_acquisitions()
            ['T1_MPRAGE', 'T2_FLAIR', 'DWI_30dir']
        """
        if self.session_df is None:
            raise ValueError("No session loaded. Call load_dicom_session() first.")
        
        return list(self.session_df['Acquisition'].unique())
    
    def get_schema_info(self, schema_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a schema.
        
        Args:
            schema_id: ID of schema to query
            
        Returns:
            Dict containing schema metadata and structure
            
        Raises:
            ValueError: If schema not found
            
        Examples:
            >>> info = session.get_schema_info('my_schema')
            >>> info['acquisition_count']
            3
        """
        if schema_id not in self.schemas:
            raise ValueError(f"Schema '{schema_id}' not found. Available: {list(self.schemas.keys())}")
        
        schema = self.schemas[schema_id]
        acquisitions = schema.get('acquisitions', {})
        
        return make_json_serializable({
            'schema_id': schema_id,
            'name': schema.get('name', schema_id),
            'acquisition_count': len(acquisitions),
            'acquisitions': list(acquisitions.keys()),
            'generated_from': schema.get('generated_from'),
            'total_files': schema.get('total_files'),
            'fields_used': schema.get('fields_used'),
            'has_results': schema_id in self.compliance_results
        })
    
    def validate_user_mapping(self, schema_id: str, user_mapping: Dict[str, str]) -> Dict[str, Any]:
        """
        Validate a user mapping without running compliance check.
        
        Args:
            schema_id: ID of schema to validate against
            user_mapping: User mapping to validate
            
        Returns:
            Dict containing validation results
            
        Raises:
            ValueError: If schema not found or session not loaded
            
        Examples:
            >>> mapping = {'t1': 'T1_MPRAGE', 't2': 'T2_FLAIR'}
            >>> result = session.validate_user_mapping('my_schema', mapping)
            >>> result['valid']
            True
        """
        if self.session_df is None:
            raise ValueError("No session loaded. Call load_dicom_session() first.")
            
        if schema_id not in self.schemas:
            raise ValueError(f"Schema '{schema_id}' not found. Available: {list(self.schemas.keys())}")
        
        schema = self.schemas[schema_id]
        schema_acquisitions = set(schema.get('acquisitions', {}).keys())
        session_acquisitions = set(self.session_df['Acquisition'].unique())
        
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'mapping_coverage': {},
            'unmapped_schema_acquisitions': [],
            'unmapped_session_acquisitions': []
        }
        
        # Check mapped schema acquisitions exist in schema
        for schema_acq in user_mapping.keys():
            if schema_acq not in schema_acquisitions:
                validation_result['valid'] = False
                validation_result['errors'].append(
                    f"Schema acquisition '{schema_acq}' not found in schema. Available: {list(schema_acquisitions)}"
                )
        
        # Check mapped session acquisitions exist in session
        for session_acq in user_mapping.values():
            if session_acq not in session_acquisitions:
                validation_result['valid'] = False
                validation_result['errors'].append(
                    f"Session acquisition '{session_acq}' not found in session. Available: {list(session_acquisitions)}"
                )
        
        # Calculate coverage
        mapped_schema_acqs = set(user_mapping.keys()) & schema_acquisitions
        mapped_session_acqs = set(user_mapping.values()) & session_acquisitions
        
        validation_result['mapping_coverage'] = {
            'schema_coverage': len(mapped_schema_acqs) / len(schema_acquisitions) if schema_acquisitions else 0,
            'session_coverage': len(mapped_session_acqs) / len(session_acquisitions) if session_acquisitions else 0,
            'mapped_schema_count': len(mapped_schema_acqs),
            'total_schema_count': len(schema_acquisitions),
            'mapped_session_count': len(mapped_session_acqs),
            'total_session_count': len(session_acquisitions)
        }
        
        # Find unmapped acquisitions
        validation_result['unmapped_schema_acquisitions'] = list(schema_acquisitions - set(user_mapping.keys()))
        validation_result['unmapped_session_acquisitions'] = list(session_acquisitions - set(user_mapping.values()))
        
        # Add warnings for partial mapping
        if validation_result['unmapped_schema_acquisitions']:
            validation_result['warnings'].append(
                f"Schema acquisitions not mapped: {validation_result['unmapped_schema_acquisitions']}"
            )
        
        if validation_result['unmapped_session_acquisitions']:
            validation_result['warnings'].append(
                f"Session acquisitions not mapped: {validation_result['unmapped_session_acquisitions']}"
            )
        
        return validation_result
    
    def suggest_automatic_mapping(self, schema_id: str) -> Dict[str, str]:
        """
        Suggest an automatic mapping based on name similarity.
        This is a helper method - users should review and modify the suggestions.
        
        Args:
            schema_id: ID of schema to map
            
        Returns:
            Dict with suggested mapping
            
        Raises:
            ValueError: If schema not found or session not loaded
            
        Examples:
            >>> suggestions = session.suggest_automatic_mapping('my_schema')
            >>> suggestions
            {'t1_mprage': 'T1_MPRAGE', 't2_flair': 'T2_FLAIR'}
        """
        if self.session_df is None:
            raise ValueError("No session loaded. Call load_dicom_session() first.")
            
        if schema_id not in self.schemas:
            raise ValueError(f"Schema '{schema_id}' not found. Available: {list(self.schemas.keys())}")
        
        schema = self.schemas[schema_id]
        schema_acquisitions = list(schema.get('acquisitions', {}).keys())
        session_acquisitions = list(self.session_df['Acquisition'].unique())
        
        suggested_mapping = {}
        
        for schema_acq in schema_acquisitions:
            # Try exact match first
            if schema_acq in session_acquisitions:
                suggested_mapping[schema_acq] = schema_acq
                continue
            
            # Try case-insensitive match
            for session_acq in session_acquisitions:
                if schema_acq.lower() == session_acq.lower():
                    suggested_mapping[schema_acq] = session_acq
                    break
            
            # Try substring matching
            if schema_acq not in suggested_mapping:
                for session_acq in session_acquisitions:
                    if (schema_acq.lower() in session_acq.lower() or 
                        session_acq.lower() in schema_acq.lower()):
                        suggested_mapping[schema_acq] = session_acq
                        break
        
        logger.info(f"Suggested mapping for schema '{schema_id}': {suggested_mapping}")
        return suggested_mapping
    
    def get_schema_generation_data(self, reference_fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get session data formatted for schema generation UI.
        
        This method replaces processExistingSession() in pyodideService.ts (45 lines)
        by providing comprehensive session analysis for the schema generation interface.
        
        Args:
            reference_fields: List of fields to analyze for schema generation
            
        Returns:
            Dict containing:
            {
                'session_summary': {...},
                'acquisitions': {...},
                'field_recommendations': {...},
                'generation_options': {...}
            }
            
        Raises:
            ValueError: If no session is loaded
            
        Examples:
            >>> data = session.get_schema_generation_data()
            >>> data['session_summary']['total_files']
            1024
            >>> data['acquisitions']['T1_MPRAGE']['suggested_fields']
            ['RepetitionTime', 'EchoTime', 'FlipAngle']
        """
        if self.session_df is None:
            raise ValueError("No session loaded. Call load_dicom_session() first.")
        
        from .web_utils import prepare_schema_generation_data
        
        # Use existing web utils function for comprehensive analysis
        generation_data = prepare_schema_generation_data(self.session_df)
        
        # Add session-specific information
        session_summary = {
            'total_files': len(self.session_df),
            'total_acquisitions': self.session_df['Acquisition'].nunique(),
            'acquisition_names': list(self.session_df['Acquisition'].unique()),
            'available_columns': list(self.session_df.columns),
            'has_loaded_schemas': len(self.schemas) > 0,
            'schema_count': len(self.schemas)
        }
        
        # Enhanced generation options
        generation_options = {
            'use_default_fields': reference_fields is None,
            'reference_fields': reference_fields or DEFAULT_SETTINGS_FIELDS,
            'can_generate_from_all': True,
            'can_generate_per_acquisition': len(session_summary['acquisition_names']) > 1,
            'recommended_approach': 'all_acquisitions' if len(session_summary['acquisition_names']) > 1 else 'single_acquisition'
        }
        
        return make_json_serializable({
            'session_summary': session_summary,
            'acquisitions': generation_data.get('acquisition_analysis', {}),
            'field_recommendations': {
                'suggested_fields': generation_data.get('suggested_fields', []),
                'available_columns': generation_data.get('available_columns', []),
                'total_suggested': len(generation_data.get('suggested_fields', []))
            },
            'generation_options': generation_options,
            'status': 'ready'
        })
    
    def batch_add_schemas(self, schemas: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
        """
        Add multiple schemas at once with validation.
        
        This method simplifies multiple loadSchema() calls in the interface
        by allowing bulk schema loading with comprehensive validation.
        
        Args:
            schemas: Dict mapping schema_id to schema_dict
            
        Returns:
            Dict mapping schema_id to success status (bool)
            
        Examples:
            >>> schemas = {
            ...     'clinical': {'acquisitions': {'t1': {...}}},
            ...     'research': {'acquisitions': {'dwi': {...}}}
            ... }
            >>> results = session.batch_add_schemas(schemas)
            >>> results['clinical']
            True
            >>> results['research'] 
            False  # If validation failed
        """
        results = {}
        
        for schema_id, schema_dict in schemas.items():
            try:
                # Validate schema structure before adding
                if not isinstance(schema_dict, dict):
                    logger.error(f"Schema '{schema_id}' is not a dictionary")
                    results[schema_id] = False
                    continue
                
                if 'acquisitions' not in schema_dict:
                    logger.error(f"Schema '{schema_id}' missing 'acquisitions' key")
                    results[schema_id] = False
                    continue
                
                # Add schema
                self.add_schema(schema_id, schema_dict)
                results[schema_id] = True
                
            except Exception as e:
                logger.error(f"Failed to add schema '{schema_id}': {e}")
                results[schema_id] = False
        
        successful_count = sum(results.values())
        total_count = len(schemas)
        logger.info(f"Batch schema loading: {successful_count}/{total_count} schemas loaded successfully")
        
        return results
    
    def get_comprehensive_summary(self) -> Dict[str, Any]:
        """
        Get complete session summary for web dashboard.
        
        This method provides comprehensive session information including
        session statistics, schema info, and acquisition details for
        dashboard display and navigation.
        
        Returns:
            Dict containing complete session state
            
        Examples:
            >>> summary = session.get_comprehensive_summary()
            >>> summary['overview']['session_loaded']
            True
            >>> summary['schemas']['count']
            3
            >>> summary['acquisitions']['T1_MPRAGE']['file_count']
            176
        """
        if self.session_df is None:
            return {
                'overview': {
                    'session_loaded': False,
                    'status': 'no_session'
                },
                'schemas': {'count': 0, 'available': []},
                'acquisitions': {},
                'compliance': {}
            }
        
        # Get basic session summary
        base_summary = self.get_session_summary()
        
        # Enhanced overview
        overview = {
            'session_loaded': True,
            'total_files': len(self.session_df),
            'total_acquisitions': self.session_df['Acquisition'].nunique(),
            'total_columns': len(self.session_df.columns),
            'schemas_loaded': len(self.schemas),
            'compliance_results_available': len(self.compliance_results),
            'status': 'loaded'
        }
        
        # Enhanced schema information
        schema_details = {}
        for schema_id, schema in self.schemas.items():
            schema_details[schema_id] = {
                'acquisition_count': len(schema.get('acquisitions', {})),
                'acquisition_names': list(schema.get('acquisitions', {}).keys()),
                'has_results': schema_id in self.compliance_results,
                'schema_type': schema.get('type', 'json'),
                'generated_from': schema.get('generated_from', 'unknown')
            }
        
        # Acquisition details with enhanced metadata
        acquisition_details = {}
        for acq_name in self.session_df['Acquisition'].unique():
            acq_data = self.session_df[self.session_df['Acquisition'] == acq_name]
            acquisition_details[acq_name] = {
                'file_count': len(acq_data),
                'display_name': acq_name.replace('_', ' ').title(),
                'sample_files': acq_data['DICOM_Path'].head(3).tolist() if 'DICOM_Path' in acq_data.columns else [],
                'has_compliance_results': any(
                    acq_name in results.get('formatted_results', {}).get('acquisition_details', {})
                    for results in self.compliance_results.values()
                )
            }
        
        # Enhanced compliance summary
        compliance_overview = {
            'total_checks_run': len(self.compliance_results),
            'schemas_with_results': list(self.compliance_results.keys()),
            'average_compliance_rate': 0,
            'last_check_timestamp': None
        }
        
        if self.compliance_results:
            rates = []
            latest_timestamp = None
            
            for results in self.compliance_results.values():
                if 'formatted_results' in results and 'summary' in results['formatted_results']:
                    rate = results['formatted_results']['summary'].get('compliance_rate', 0)
                    rates.append(rate)
                
                timestamp = results.get('timestamp')
                if timestamp and (latest_timestamp is None or timestamp > latest_timestamp):
                    latest_timestamp = timestamp
            
            if rates:
                compliance_overview['average_compliance_rate'] = sum(rates) / len(rates)
            compliance_overview['last_check_timestamp'] = latest_timestamp
        
        return make_json_serializable({
            'overview': overview,
            'schemas': {
                'count': len(self.schemas),
                'available': list(self.schemas.keys()),
                'details': schema_details
            },
            'acquisitions': acquisition_details,
            'compliance': compliance_overview,
            'session_metadata': self.session_metadata
        })
    
    def export_session_for_web(self) -> Dict[str, Any]:
        """
        Export complete session state for web persistence.
        
        This method enables session save/restore functionality in the interface
        by providing a complete, serializable representation of the session state.
        
        Returns:
            Dict containing complete session state for persistence
            
        Examples:
            >>> export_data = session.export_session_for_web()
            >>> export_data['session_state']['has_session']
            True
            >>> len(export_data['schemas'])
            3
        """
        if self.session_df is None:
            return {
                'session_state': {
                    'has_session': False,
                    'export_timestamp': pd.Timestamp.now().isoformat()
                },
                'schemas': {},
                'compliance_results': {},
                'metadata': self.session_metadata
            }
        
        # Prepare session data for export (without full DataFrame due to size)
        session_state = {
            'has_session': True,
            'total_files': len(self.session_df),
            'total_acquisitions': self.session_df['Acquisition'].nunique(),
            'acquisition_names': list(self.session_df['Acquisition'].unique()),
            'columns': list(self.session_df.columns),
            'export_timestamp': pd.Timestamp.now().isoformat()
        }
        
        # Include a sample of data for verification during import
        sample_data = self.session_df.head(10).to_dict('records') if len(self.session_df) <= 100 else self.session_df.head(5).to_dict('records')
        session_state['sample_data'] = sample_data
        
        return make_json_serializable({
            'session_state': session_state,
            'schemas': self.schemas,
            'compliance_results': self.compliance_results,
            'metadata': self.session_metadata,
            'export_version': '1.0'
        })