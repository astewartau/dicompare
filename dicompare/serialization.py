"""
JSON serialization utilities for dicompare.

This module provides functions to convert numpy/pandas types to standard Python types
for JSON serialization.
"""

import numpy as np
import pandas as pd
from typing import Any


def make_json_serializable(data: Any) -> Any:
    """
    Convert numpy/pandas types to standard Python types for JSON serialization.
    
    This function recursively processes data structures to convert:
    - numpy arrays to lists
    - numpy scalars to Python scalars
    - pandas NaN/NA to None
    - pandas Series to lists
    - pandas DataFrames to list of dicts
    
    Args:
        data: Any data structure potentially containing numpy/pandas types
        
    Returns:
        Data structure with all numpy/pandas types converted to JSON-serializable types
        
    Examples:
        >>> import numpy as np
        >>> data = {'array': np.array([1, 2, 3]), 'value': np.int64(42)}
        >>> make_json_serializable(data)
        {'array': [1, 2, 3], 'value': 42}
    """
    if isinstance(data, dict):
        return {k: make_json_serializable(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return [make_json_serializable(item) for item in data]
    elif isinstance(data, np.ndarray):
        return data.tolist()
    elif isinstance(data, pd.Series):
        return data.tolist()
    elif isinstance(data, pd.DataFrame):
        return data.to_dict('records')
    elif pd.isna(data) or data is None:
        return None
    elif isinstance(data, (np.integer, np.floating)):
        if np.isnan(data) or np.isinf(data):
            return None
        return data.item()
    elif isinstance(data, float):
        if np.isnan(data) or np.isinf(data):
            return None
        return data
    else:
        # For any other type, try to convert to standard Python type
        try:
            # Handle numpy bool_
            if hasattr(data, 'item'):
                return data.item()
        except:
            pass
        return data