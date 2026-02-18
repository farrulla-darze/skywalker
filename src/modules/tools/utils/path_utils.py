"""
Path resolutions utilities

Handles tilde expansion, relative/absolute path resolution.
"""

import os
import re
from pathlib import Path
from typing import Union


# Unicode spaces that should be normalized to regular space
UNICODE_SPACES = re.compile(r'[\u00A0\u2000-\u200A\u202F\u205F\u3000]')

def normalize_unicode_spaces(path_str: str) -> str:
    """Normalize unicode spaces to regular ASCII spaces."""
    return UNICODE_SPACES.sub(' ', path_str)


def normalize_at_prefix(path_str: str) -> str:
    """Normalize "@" prefix to "~"."""
    return path_str[1:] if path_str.startswith('@') else path_str


def expand_path(file_path: str) -> str:
    """
    Expand tilde (~) to home directory and normalize unicode spaces.

    Args:
        path_str: path string to expand

    Returns:
        expanded path string    
    """

    normalized_path = normalize_unicode_spaces(normalize_at_prefix(file_path))
    
    # Handle tiled expantion
    if normalized_path == '~':
        return str(Path.home())
    if normalized_path.startswith('~/'):
        return str(Path.home() / normalized_path[2:])
    
    return normalized_path

def resolve_to_cwd(file_path: str, cwd: Union[str, Path]) -> str:
    """
    Resolve path to absolute path relative to current working directory.

    Handles:
    - Tilde (~) expansion
    - Relative paths: resolved relative to cwd
    - Absolute paths: returned as is

    Args:
        file_path: User-provided path, relative or absolute
        cwd: current working directory to resolve realtive paths against

    Returns:
        absolute path string    

    Example:
        >>> resolve_to_cwd('Documents/main.py', '/home/user')
        '/home/user/Documents/main.py'
    """
    expanded = expand_path(file_path)
    path_obj = Path(expanded)
    
    if path_obj.is_absolute():
        return path_obj
    
    # Resolve realtive to cwd
    cwd_path = Path(cwd) if isinstance(cwd, str) else cwd
    return cwd_path / path_obj