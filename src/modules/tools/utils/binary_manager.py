"""
Binary manager for external tools like fd and rg.
 
Handles checking for binary availability and providing paths.
For simplicity, this implementation assumes fd is installed system-wide.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

class BinaryNotFoundError(Exception):
    """Raised when a required binary is not available."""
    pass

def get_fd_path() -> Optional[str]:
    """
    Get the path to the fd binary.
    
    Checks if fd is available in the system PATH.
    
    Returns:
        Path to fd binary, or None if not found
        
    Note:
        The TypeScript version downloads fd if not found.
        For simplicity, this Python version requires fd to be installed.
        You can extend this to download fd from GitHub releases.
    """
    # Try common names for fd
    for name in ["fd", "fdfind"]:  # Debian/Ubuntu uses 'fdfind'
        fd_path = shutil.which(name)
        if fd_path:
            return fd_path
    
    return None

def ensure_fd(silent: bool = False) -> str:
    """
    Ensure fd binary is available.
    
    Args:
        silent: If True, don't print messages
        
    Returns:
        Path to fd binary
        
    Raises:
        BinaryNotFoundError: If fd is not available
        
    Example:
        >>> fd_path = ensure_fd()
        >>> print(f"Using fd at: {fd_path}")
    """
    fd_path = get_fd_path()
    
    if fd_path:
        return fd_path
    
    # fd not found
    if not silent:
        print(
            "fd not found. Please install it:\n"
            "  macOS:   brew install fd\n"
            "  Ubuntu:  apt install fd-find\n"
            "  Arch:    pacman -S fd\n"
            "  Cargo:   cargo install fd-find"
        )
    
    raise BinaryNotFoundError(
        "fd is not available. Please install fd-find: https://github.com/sharkdp/fd"
    )

def get_rg_path() -> Optional[str]:
    """
    Get the path to the rg (ripgrep) binary.

    Checks if rg is available in the system PATH.

    Returns:
        Path to rg binary, or None if not found
    """
    rg_path = shutil.which("rg")
    if rg_path:
        return rg_path

    return None


def ensure_rg(silent: bool = False) -> str:
    """
    Ensure rg (ripgrep) binary is available.

    Args:
        silent: If True, don't print messages

    Returns:
        Path to rg binary

    Raises:
        BinaryNotFoundError: If rg is not available

    Example:
        >>> rg_path = ensure_rg()
        >>> print(f"Using rg at: {rg_path}")
    """
    rg_path = get_rg_path()

    if rg_path:
        return rg_path

    # rg not found
    if not silent:
        print(
            "rg (ripgrep) not found. Please install it:\n"
            "  macOS:   brew install ripgrep\n"
            "  Ubuntu:  apt install ripgrep\n"
            "  Arch:    pacman -S ripgrep\n"
            "  Cargo:   cargo install ripgrep"
        )

    raise BinaryNotFoundError(
        "rg is not available. Please install ripgrep: https://github.com/BurntSushi/ripgrep"
    )


def check_fd_version() -> Optional[str]:
    """
    Check fd version.
    
    Returns:
        Version string, or None if fd not available
    """
    fd_path = get_fd_path()
    if not fd_path:
        return None
    
    try:
        result = subprocess.run(
            [fd_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Output format: "fd 8.7.0"
            return result.stdout.strip()
    except Exception:
        pass
    
    return None