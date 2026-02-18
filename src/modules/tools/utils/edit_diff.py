"""
Diff and fuzzy matching utilities for the edit tool.

Handles line ending normalization, BOM stripping, fuzzy text matching,
and unified diff generation.
"""

from typing import Literal, Optional, NamedTuple
from difflib import unified_diff


# ============================================================================
# Line Ending Utilities
# ============================================================================

def detect_line_ending(content: str) -> Literal["\r\n", "\n"]:
    """Detect whether file uses CRLF or LF line endings."""
    crlf_idx = content.find("\r\n")
    lf_idx = content.find("\n")
    
    if lf_idx == -1:
        return "\n"
    if crlf_idx == -1:
        return "\n"
    
    return "\r\n" if crlf_idx < lf_idx else "\n"


def normalize_to_lf(text: str) -> str:
    """Convert all line endings to LF (\n)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def restore_line_endings(text: str, ending: Literal["\r\n", "\n"]) -> str:
    """Restore original line endings."""
    return text.replace("\n", "\r\n") if ending == "\r\n" else text


# ============================================================================
# BOM Handling
# ============================================================================

def strip_bom(content: str) -> tuple[str, str]:
    """
    Strip UTF-8 BOM if present.
    
    Returns:
        Tuple of (bom, text_without_bom)
    """
    if content.startswith("\ufeff"):
        return ("\ufeff", content[1:])
    return ("", content)


# ============================================================================
# Fuzzy Matching
# ============================================================================

def normalize_for_fuzzy_match(text: str) -> str:
    """
    Normalize text for fuzzy matching.
    
    Applies transformations:
    - Strip trailing whitespace from each line
    - Normalize smart quotes to ASCII
    - Normalize Unicode dashes to ASCII hyphen
    - Normalize special Unicode spaces to regular space
    """
    lines = text.split("\n")
    stripped_lines = [line.rstrip() for line in lines]
    normalized = "\n".join(stripped_lines)
    
    # Smart single quotes → '
    normalized = normalized.translate(str.maketrans({
        '\u2018': "'",  # Left single quote
        '\u2019': "'",  # Right single quote
        '\u201a': "'",  # Single low-9 quote
        '\u201b': "'",  # Single high-reversed-9 quote
    }))
    
    # Smart double quotes → "
    normalized = normalized.translate(str.maketrans({
        '\u201c': '"',  # Left double quote
        '\u201d': '"',  # Right double quote
        '\u201e': '"',  # Double low-9 quote
        '\u201f': '"',  # Double high-reversed-9 quote
    }))
    
    # Various dashes → -
    normalized = normalized.translate(str.maketrans({
        '\u2010': '-',  # Hyphen
        '\u2011': '-',  # Non-breaking hyphen
        '\u2012': '-',  # Figure dash
        '\u2013': '-',  # En dash
        '\u2014': '-',  # Em dash
        '\u2015': '-',  # Horizontal bar
        '\u2212': '-',  # Minus sign
    }))
    
    # Special spaces → regular space
    normalized = normalized.translate(str.maketrans({
        '\u00a0': ' ',  # NBSP
        '\u2002': ' ',  # En space
        '\u2003': ' ',  # Em space
        '\u2004': ' ',  # Three-per-em space
        '\u2005': ' ',  # Four-per-em space
        '\u2006': ' ',  # Six-per-em space
        '\u2007': ' ',  # Figure space
        '\u2008': ' ',  # Punctuation space
        '\u2009': ' ',  # Thin space
        '\u200a': ' ',  # Hair space
        '\u202f': ' ',  # Narrow NBSP
        '\u205f': ' ',  # Medium mathematical space
        '\u3000': ' ',  # Ideographic space
    }))
    
    return normalized


class FuzzyMatchResult(NamedTuple):
    """Result of fuzzy text matching."""
    found: bool
    index: int
    match_length: int
    used_fuzzy_match: bool
    content_for_replacement: str


def fuzzy_find_text(content: str, old_text: str) -> FuzzyMatchResult:
    """
    Find old_text in content, trying exact match first, then fuzzy.
    
    When fuzzy matching is used, content_for_replacement is the
    normalized version (trailing whitespace stripped, Unicode normalized).
    
    Args:
        content: File content to search in
        old_text: Text to find
        
    Returns:
        FuzzyMatchResult with match details
    """
    # Try exact match first
    exact_index = content.find(old_text)
    if exact_index != -1:
        return FuzzyMatchResult(
            found=True,
            index=exact_index,
            match_length=len(old_text),
            used_fuzzy_match=False,
            content_for_replacement=content,
        )
    
    # Try fuzzy match - work in normalized space
    fuzzy_content = normalize_for_fuzzy_match(content)
    fuzzy_old_text = normalize_for_fuzzy_match(old_text)
    fuzzy_index = fuzzy_content.find(fuzzy_old_text)
    
    if fuzzy_index == -1:
        return FuzzyMatchResult(
            found=False,
            index=-1,
            match_length=0,
            used_fuzzy_match=False,
            content_for_replacement=content,
        )
    
    # When fuzzy matching, work in normalized space for replacement
    return FuzzyMatchResult(
        found=True,
        index=fuzzy_index,
        match_length=len(fuzzy_old_text),
        used_fuzzy_match=True,
        content_for_replacement=fuzzy_content,
    )


# ============================================================================
# Diff Generation
# ============================================================================

def generate_diff_string(
    old_content: str,
    new_content: str,
    context_lines: int = 4,
) -> tuple[str, Optional[int]]:
    """
    Generate a unified diff string with line numbers.
    
    Args:
        old_content: Original content
        new_content: Modified content
        context_lines: Number of context lines to show
        
    Returns:
        Tuple of (diff_string, first_changed_line)
    """
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")
    
    # Generate unified diff
    diff_lines = list(unified_diff(
        old_lines,
        new_lines,
        lineterm="",
        n=context_lines,
    ))
    
    if not diff_lines:
        return ("", None)
    
    # Parse diff and add line numbers
    output = []
    old_line_num = 1
    new_line_num = 1
    first_changed_line = None
    
    max_line_num = max(len(old_lines), len(new_lines))
    line_num_width = len(str(max_line_num))
    
    for line in diff_lines:
        if line.startswith("---") or line.startswith("+++"):
            continue  # Skip file headers
        
        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            parts = line.split()
            if len(parts) >= 3:
                old_part = parts[1].lstrip("-")
                new_part = parts[2].lstrip("+")
                
                old_line_num = int(old_part.split(",")[0])
                new_line_num = int(new_part.split(",")[0])
            continue
        
        if line.startswith("-"):
            # Removed line
            line_num = str(old_line_num).rjust(line_num_width)
            output.append(f"-{line_num} {line[1:]}")
            old_line_num += 1
            if first_changed_line is None:
                first_changed_line = new_line_num
        elif line.startswith("+"):
            # Added line
            line_num = str(new_line_num).rjust(line_num_width)
            output.append(f"+{line_num} {line[1:]}")
            new_line_num += 1
            if first_changed_line is None:
                first_changed_line = new_line_num - 1
        else:
            # Context line
            line_num = str(old_line_num).rjust(line_num_width)
            output.append(f" {line_num} {line[1:] if line.startswith(' ') else line}")
            old_line_num += 1
            new_line_num += 1
    
    return ("\n".join(output), first_changed_line)