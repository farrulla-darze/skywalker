"""
Truncation utilities for tool outputs.
 
Enforces line and byte limits on text output, providing metadata
about what was truncated and why.
"""
from dataclasses import dataclass
from typing import Optional, Literal

# Default limits
DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024  # 50KB
GREP_MAX_LINE_LENGTH = 500


@dataclass
class TruncationResult:
    """ Result of truncation operation """

    content: str
    """ Truncated content """
    
    truncated: bool
    """ Whether the content was truncated """
    
    truncated_by: Optional[Literal['bytes', 'lines']]
    """ What caused the truncation: lines, bytes or None if not truncated """

    total_lines: int
    """ Total number of lines in the original content """

    total_bytes: int
    """ Total number of bytes in the original content """

    output_lines: int
    """ Number of lines in the truncated content """

    output_bytes: int
    """ Number of bytes in the truncated content """

    last_line_partial: bool
    """Whether the last line was partially truncated (tail truncation only)"""
    
    first_line_exceeds_limit: bool
    """Whether the first line alone exceeded byte limit (head truncation)"""
    
    max_lines: int
    """The max lines limit that was applied"""
    
    max_bytes: int
    """The max bytes limit that was applied"""


def format_size(num_bytes: int) -> str:
    """
    Format bytes as human-readable size.
    
    Args:
        num_bytes: Number of bytes
        
    Returns:
        Formatted string like "1.5KB" or "2.3MB"
        
    Example:
        >>> format_size(1500)
        '1.5KB'
        >>> format_size(500)
        '500B'
    """
    if num_bytes < 1024:
        return f"{num_bytes}B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    else:
        return f"{num_bytes / (1024 * 1024):.1f}MB"

def truncate_head(
    content: str,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> TruncationResult:
    """
    Truncate content from the head (keep first N lines/bytes).
    
    Suitable for file reads and find results where you want to see the beginning.
    Never returns partial lines. If the first line exceeds byte limit,
    returns empty content with first_line_exceeds_limit=True.
    
    Args:
        content: Text content to truncate
        max_lines: Maximum number of lines (default: 2000)
        max_bytes: Maximum number of bytes (default: 50KB)
        
    Returns:
        TruncationResult with truncated content and metadata
        
    Example:
        >>> result = truncate_head("line1\\nline2\\nline3", max_lines=2)
        >>> result.content
        'line1\\nline2'
        >>> result.truncated
        True
        >>> result.truncated_by
        'lines'
    """
    total_bytes = len(content.encode('utf-8'))
    lines = content.split('\n')
    total_lines = len(lines)
    
    # Check if no truncation needed
    if total_lines <= max_lines and total_bytes <= max_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            last_line_partial=False,
            first_line_exceeds_limit=False,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )
    
    # Check if first line alone exceeds byte limit
    first_line_bytes = len(lines[0].encode('utf-8'))
    if first_line_bytes > max_bytes:
        return TruncationResult(
            content="",
            truncated=True,
            truncated_by="bytes",
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=0,
            output_bytes=0,
            last_line_partial=False,
            first_line_exceeds_limit=True,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )
    
    # Collect complete lines that fit within limits
    output_lines_arr = []
    output_bytes_count = 0
    truncated_by: Literal["lines", "bytes"] = "lines"
    
    for i, line in enumerate(lines):
        # Calculate bytes for this line (add 1 for newline, except first line)
        line_bytes = len(line.encode('utf-8')) + (1 if i > 0 else 0)
        
        # Check if adding this line would exceed byte limit
        if output_bytes_count + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        
        # Check if we've hit line limit
        if i >= max_lines:
            truncated_by = "lines"
            break
        
        output_lines_arr.append(line)
        output_bytes_count += line_bytes
    
    # Determine which limit was actually hit
    if len(output_lines_arr) >= max_lines and output_bytes_count <= max_bytes:
        truncated_by = "lines"
    
    output_content = '\n'.join(output_lines_arr)
    final_output_bytes = len(output_content.encode('utf-8'))
    
    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_arr),
        output_bytes=final_output_bytes,
        last_line_partial=False,
        first_line_exceeds_limit=False,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )

def truncate_line(line: str, max_chars: int = GREP_MAX_LINE_LENGTH) -> tuple[str, bool]:
    """
    Truncate a single line to max characters, adding [truncated] suffix.
    
    Used for grep match lines to prevent extremely long lines.
    
    Args:
        line: Line to truncate
        max_chars: Maximum characters (default: 500)
        
    Returns:
        Tuple of (truncated_text, was_truncated)
        
    Example:
        >>> truncate_line("a" * 600, max_chars=500)
        ('aaa...aaa... [truncated]', True)
    """
    if len(line) <= max_chars:
        return (line, False)
    return (f"{line[:max_chars]}... [truncated]", True)
    