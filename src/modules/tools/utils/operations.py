"""
Pluggable operations interfaces for tools.

Defines abstract interfaces that allow tools to work with different
backends (local filesystem, SSH, Docker, S3, etc.).
"""

import inspect
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypeVar, Union

T = TypeVar('T')


# ============================================================================
# Async/Sync Helper
# ============================================================================

async def maybe_await(value: Union[T, Awaitable[T]]) -> T:
    """
    Await a value if it's awaitable, otherwise return it directly.

    This allows handling both sync and async operations uniformly.

    Args:
        value: Either a direct value or an awaitable

    Returns:
        The resolved value

    Example:
        >>> result = await maybe_await(some_operation())
        # Works whether some_operation() returns a value or a coroutine
    """
    if inspect.iscoroutine(value) or inspect.isawaitable(value):
        return await value
    return value


# ============================================================================
# Find Tool Operations
# ============================================================================

@dataclass
class FindOperations:
    """
    Pluggable filesystem operations for the find tool.

    Override these to delegate file search to remote systems (e.g., SSH).
    All operations can be sync or async.
    """

    exists: Callable[[str], Union[bool, Awaitable[bool]]]
    """
    Check if a path exists.

    Args:
        absolute_path: Absolute path to check

    Returns:
        True if path exists, False otherwise
    """

    glob: Callable[[str, str, dict], Union[list[str], Awaitable[list[str]]]]
    """
    Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "*.py", "**/*.json")
        cwd: Working directory to search in
        options: Dict with keys:
            - ignore: List of patterns to ignore (e.g., ["**/node_modules/**"])
            - limit: Maximum number of results

    Returns:
        List of file paths (can be absolute or relative)
    """


# ============================================================================
# Grep Tool Operations
# ============================================================================

@dataclass
class GrepOperations:
    """
    Pluggable operations for the grep tool.

    Override these to delegate grep to remote systems (e.g., SSH, Docker).
    All operations can be sync or async.
    """

    exists: Callable[[str], Union[bool, Awaitable[bool]]]
    """
    Check if a path exists.

    Args:
        absolute_path: Absolute path to check

    Returns:
        True if path exists, False otherwise
    """

    grep: Callable[[str, str, dict], Union[str, Awaitable[str]]]
    """
    Search file contents for a pattern.

    Args:
        pattern: Regex pattern to search for
        cwd: Working directory to search in
        options: Dict with keys:
            - include: Glob filter for files (e.g., "*.py")
            - case_insensitive: bool
            - context_lines: int
            - limit: Maximum number of matching lines

    Returns:
        Raw grep output string (one match per line)
    """


# ============================================================================
# Read Tool Operations
# ============================================================================

@dataclass
class ReadOperations:
    """
    Pluggable filesystem operations for the read tool.

    Override these to delegate file reading to remote systems (e.g., SSH).
    All operations can be sync or async.
    """

    read_file: Callable[[str], Union[bytes, Awaitable[bytes]]]
    """
    Read file contents as bytes.

    Args:
        absolute_path: Absolute path to the file

    Returns:
        File contents as bytes

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file is not readable
    """

    access: Callable[[str], Union[None, Awaitable[None]]]
    """
    Check if file exists and is readable.

    Args:
        absolute_path: Absolute path to check

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file is not readable
    """

    detect_image_mime_type: Optional[Callable[[str], Union[Optional[str], Awaitable[Optional[str]]]]] = None
    """
    Detect if file is an image and return MIME type.

    Args:
        absolute_path: Absolute path to the file

    Returns:
        MIME type string if image (e.g., "image/jpeg"), None otherwise
    """


# ============================================================================
# Write Tool Operations
# ============================================================================

@dataclass
class WriteOperations:
    """
    Pluggable filesystem operations for the write tool.

    Override these to delegate file writing to remote systems (e.g., SSH).
    """

    write_file: Callable[[str, str], Union[None, Awaitable[None]]]
    """
    Write content to a file.

    Args:
        absolute_path: Absolute path to the file
        content: Content to write (UTF-8 string)

    Raises:
        PermissionError: If file is not writable
        OSError: If write fails
    """

    mkdir: Callable[[str], Union[None, Awaitable[None]]]
    """
    Create directory recursively.

    Args:
        dir_path: Directory path to create

    Note:
        Should create all parent directories (like mkdir -p)
    """


# ============================================================================
# Edit Tool Operations
# ============================================================================

@dataclass
class EditOperations:
    """
    Pluggable filesystem operations for the edit tool.

    Requires both read and write access to files.
    """

    read_file: Callable[[str], Union[bytes, Awaitable[bytes]]]
    """Read file contents as bytes."""

    write_file: Callable[[str, str], Union[None, Awaitable[None]]]
    """Write content to a file (UTF-8)."""

    access: Callable[[str], Union[None, Awaitable[None]]]
    """
    Check if file is readable and writable.

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file is not readable or writable
    """


# ============================================================================
# Default Local Filesystem Operations
# ============================================================================

def _default_exists(absolute_path: str) -> bool:
    """Check if path exists on local filesystem."""
    return Path(absolute_path).exists()


def _default_glob(pattern: str, cwd: str, options: dict) -> list[str]:
    """
    Placeholder glob for default operations.

    The actual find tool uses the fd binary directly for performance,
    so this placeholder is never called in the default path.
    """
    return []


def _default_grep(pattern: str, cwd: str, options: dict) -> str:
    """
    Placeholder grep for default operations.

    The actual grep tool uses the rg binary directly for performance,
    so this placeholder is never called in the default path.
    """
    return ""


def _default_read_file(absolute_path: str) -> bytes:
    """Read file contents from local filesystem."""
    return Path(absolute_path).read_bytes()


def _default_access(absolute_path: str) -> None:
    """
    Check if file exists and is readable on local filesystem.

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file is not readable
    """
    path = Path(absolute_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {absolute_path}")

    if not os.access(absolute_path, os.R_OK):
        raise PermissionError(f"File is not readable: {absolute_path}")


def _default_detect_image_mime_type(absolute_path: str) -> Optional[str]:
    """Detect image MIME type using local filesystem."""
    from .image_utils import detect_image_mime_type

    return detect_image_mime_type(Path(absolute_path))


def _default_write_file(absolute_path: str, content: str) -> None:
    """Write file to local filesystem."""
    Path(absolute_path).write_text(content, encoding='utf-8')


def _default_mkdir(dir_path: str) -> None:
    """Create directory on local filesystem."""
    Path(dir_path).mkdir(parents=True, exist_ok=True)


def _default_edit_access(absolute_path: str) -> None:
    """Check if file is readable and writable on local filesystem."""
    path = Path(absolute_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {absolute_path}")

    if not os.access(absolute_path, os.R_OK):
        raise PermissionError(f"File is not readable: {absolute_path}")

    if not os.access(absolute_path, os.W_OK):
        raise PermissionError(f"File is not writable: {absolute_path}")


# ============================================================================
# Default Operations Factories
# ============================================================================

def create_default_find_operations() -> FindOperations:
    """
    Create default find operations for local filesystem.

    Note: The glob operation is a placeholder. The actual find tool
    uses the fd binary directly for better performance and .gitignore support.

    Returns:
        FindOperations configured for local filesystem
    """
    return FindOperations(
        exists=_default_exists,
        glob=_default_glob,
    )


def create_default_grep_operations() -> GrepOperations:
    """
    Create default grep operations for local filesystem.

    Note: The grep operation is a placeholder. The actual grep tool
    uses the rg binary directly for better performance and .gitignore support.

    Returns:
        GrepOperations configured for local filesystem
    """
    return GrepOperations(
        exists=_default_exists,
        grep=_default_grep,
    )


def create_default_read_operations() -> ReadOperations:
    """
    Create default read operations for local filesystem.

    Returns:
        ReadOperations configured for local filesystem
    """
    return ReadOperations(
        read_file=_default_read_file,
        access=_default_access,
        detect_image_mime_type=_default_detect_image_mime_type,
    )


def create_default_write_operations() -> WriteOperations:
    """Create default write operations for local filesystem."""
    return WriteOperations(
        write_file=_default_write_file,
        mkdir=_default_mkdir,
    )


def create_default_edit_operations() -> EditOperations:
    """Create default edit operations for local filesystem."""
    return EditOperations(
        read_file=_default_read_file,
        write_file=_default_write_file,
        access=_default_edit_access,
    )


# ============================================================================
# Example: SSH Remote Operations
# ============================================================================

class SSHFindOperations:
    """
    Example implementation of FindOperations for SSH remote execution.

    This is a reference implementation showing how to create custom operations.
    You would need to install an SSH library like paramiko or fabric.
    """

    def __init__(self, ssh_client):
        """
        Initialize SSH operations.

        Args:
            ssh_client: SSH client instance (e.g., paramiko.SSHClient)
        """
        self.ssh_client = ssh_client

    async def exists(self, absolute_path: str) -> bool:
        """Check if path exists on remote server."""
        stdin, stdout, stderr = self.ssh_client.exec_command(
            f'test -e "{absolute_path}" && echo "1" || echo "0"'
        )
        result = stdout.read().decode().strip()
        return result == "1"

    async def glob(self, pattern: str, cwd: str, options: dict) -> list[str]:
        """Find files on remote server using fd."""
        ignore_patterns = options.get('ignore', [])
        limit = options.get('limit', 1000)

        ignore_args = ' '.join(f'--exclude "{ig}"' for ig in ignore_patterns)
        cmd = f'cd "{cwd}" && fd --glob {ignore_args} --max-results {limit} "{pattern}"'

        stdin, stdout, stderr = self.ssh_client.exec_command(cmd)
        output = stdout.read().decode().strip()

        if not output:
            return []

        return [line.strip() for line in output.split('\n') if line.strip()]

    def to_operations(self) -> FindOperations:
        """Convert to FindOperations dataclass."""
        return FindOperations(
            exists=self.exists,
            glob=self.glob,
        )


class SSHReadOperations:
    """
    Example implementation of ReadOperations for SSH remote execution.

    This is a reference implementation showing how to create custom operations.
    """

    def __init__(self, ssh_client):
        """
        Initialize SSH operations.

        Args:
            ssh_client: SSH client instance (e.g., paramiko.SSHClient)
        """
        self.ssh_client = ssh_client

    async def read_file(self, absolute_path: str) -> bytes:
        """Read file from remote server."""
        sftp = self.ssh_client.open_sftp()
        try:
            with sftp.file(absolute_path, 'rb') as f:
                return f.read()
        finally:
            sftp.close()

    async def access(self, absolute_path: str) -> None:
        """Check if file exists and is readable on remote server."""
        stdin, stdout, stderr = self.ssh_client.exec_command(
            f'test -r "{absolute_path}" && echo "ok" || echo "fail"'
        )
        result = stdout.read().decode().strip()

        if result != "ok":
            stdin, stdout, stderr = self.ssh_client.exec_command(
                f'test -e "{absolute_path}" && echo "exists" || echo "missing"'
            )
            exists = stdout.read().decode().strip() == "exists"

            if not exists:
                raise FileNotFoundError(f"File not found: {absolute_path}")
            else:
                raise PermissionError(f"File is not readable: {absolute_path}")

    async def detect_image_mime_type(self, absolute_path: str) -> Optional[str]:
        """Detect image MIME type on remote server."""
        stdin, stdout, stderr = self.ssh_client.exec_command(
            f'file --mime-type -b "{absolute_path}"'
        )
        mime_type = stdout.read().decode().strip()

        supported_types = {
            "image/jpeg", "image/png", "image/gif", "image/webp",
            "image/bmp", "image/svg+xml", "image/tiff"
        }

        return mime_type if mime_type in supported_types else None

    def to_operations(self) -> ReadOperations:
        """Convert to ReadOperations dataclass."""
        return ReadOperations(
            read_file=self.read_file,
            access=self.access,
            detect_image_mime_type=self.detect_image_mime_type,
        )

