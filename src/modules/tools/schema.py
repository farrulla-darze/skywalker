from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional, Literal, Union
from dataclasses import dataclass

from .enums import ToolTypeEnum

# ============================================================================
# Shared Content Types (used by all tools)
# ============================================================================
 
class TextContent(BaseModel):
    """Text content block."""
    type: Literal["text"] = "text"
    text: str

class ImageContent(BaseModel):
    """Image content block (base64 encoded)."""
    type: Literal["image"] = "image"
    data: str  # base64 encoded image data
    mime_type: str  # e.g., "image/jpeg", "image/png"

# Union type for content blocks
ContentBlock = Union[TextContent, ImageContent]

# ============================================================================
# Find Tool Schemas
# ============================================================================

class FindParams(BaseModel):
    """
    Input parameters for the find tool.
    
    The find tool searches for files matching a glob pattern,
    respecting .gitignore files.
    """

    pattern: str = Field(..., description="Glob pattern to match files, e.g. '*.txt', '*.py'")
    path: Optional[str] = Field(None, description="Directory to search in (default: current directory)")
    limit: Optional[int] = Field(None, description="Maximum number of results to return (default: 1000)")
    

    class Config:
        """Pydantic configuration."""
        # Allow extra fields to be ignored (for forward compatibility)
        extra = "forbid"
        # Use enum values instead of enum objects in JSON
        use_enum_values = True

class FindToolDetails(BaseModel):
    """
    Metadata about find tool execution.
    
    Provides information about truncation and limits hit during search.
    """
    trunctation: Optional[dict] = Field(None, description="Truncation metadata if output was truncated")
    result_limit_hit: Optional[int] = Field(None, description="Number of results that hit the limit")

class GrepParams(BaseModel):
    """
    Input parameters for the grep tool.

    The grep tool searches file contents for lines matching a regex pattern,
    using ripgrep as the backend.
    """

    pattern: str = Field(..., description="Regex pattern to search for in file contents")
    path: Optional[str] = Field(None, description="Directory to search in (default: current directory)")
    include: Optional[str] = Field(None, description="Glob filter for files to search, e.g. '*.py'")
    case_insensitive: Optional[bool] = Field(None, description="Enable case-insensitive search")
    context_lines: Optional[int] = Field(None, description="Number of context lines before and after each match")

    class Config:
        extra = "forbid"
        use_enum_values = True


class GrepToolDetails(BaseModel):
    """
    Metadata about grep tool execution.

    Provides information about truncation and limits hit during search.
    """
    truncation: Optional[dict] = Field(None, description="Truncation metadata if output was truncated")
    result_limit_reached: Optional[int] = Field(None, description="Number of results that hit the limit")


class ToolResult(BaseModel):
    """
    Result of a tool execution.

    All tools return this structure containing content blocks
    and optional tool-specific details.
    """
    content: list[ContentBlock] = Field(..., description="Content blocks")
    details: Optional[Union[FindToolDetails, GrepToolDetails, dict]] = Field(None, description="Tool-specific execution details")
    

# ============================================================================
# Agent Tool Descriptor (what the agent sees)
# ============================================================================
 
@dataclass
class AgentTool:
    """
    Tool descriptor for the agent.
    
    This is NOT a Pydantic model because it contains a callable (execute function).
    Dataclasses are lighter for internal structures.
    """
    
    name: str
    """Tool name (e.g., 'find', 'read', 'write')"""
    
    label: str
    """Human-readable label for UI display"""
    
    description: str
    """Description of what the tool does (shown to LLM)"""
    
    parameters_schema: type[BaseModel]
    """Pydantic model class for input parameters"""
    
    execute: callable
    """
    Async function that executes the tool.
    
    Signature: async def execute(
        tool_call_id: str,
        params: BaseModel,
        signal: Optional[Event] = None
    ) -> ToolResult
    """

# ============================================================================
# Read Tool Schemas
# ============================================================================

class ReadParams(BaseModel):
    """
    Input parameters for the read tool.
    
    The read tool reads file contents, supporting both text and images.
    For text files, offset and limit allow reading large files in chunks.
    """
    
    path: str = Field(
        ...,
        description="Path to the file to read (relative or absolute)",
        examples=["src/main.py", "/absolute/path/to/file.txt", "~/Documents/notes.md"]
    )
    
    offset: Optional[int] = Field(
        None,
        description="Line number to start reading from (1-indexed). Use for large files.",
        ge=1,  # Must be >= 1 (1-indexed)
        examples=[1, 100, 500]
    )
    
    limit: Optional[int] = Field(
        None,
        description="Maximum number of lines to read from offset",
        ge=1,  # Must be >= 1
        examples=[50, 100, 500]
    )
    
    class Config:
        extra = "forbid"
        use_enum_values = True


class ReadToolDetails(BaseModel):
    """
    Metadata about read tool execution.
    
    Provides information about truncation that occurred during reading.
    """
    
    truncation: Optional[dict] = Field(
        None,
        description="Truncation metadata if output was truncated"
    )

# ============================================================================
# Write Tool Schemas
# ============================================================================

class WriteParams(BaseModel):
    """
    Input parameters for the write tool.

    The write tool writes content to a file, creating it if it doesn't exists
    or overwriting if it does. Parent directories are created automatically.
    """
    path: str = Field(..., description="Path to the file to write (relative or absolute)",
    examples=["src/main.py", "/absolute/path/to/file.txt", "~/Documents/notes.md"]
    )
    
    content: str = Field(..., description="Content to write to the file",
    examples=["print('Hello, World!')", "{\n \"key\": \"value\"}"]
    )
    
    class Config:
        extra = "forbid"
        use_enum_values = True

# Note: Write tool has no details metadata - always returns None


# ============================================================================
# Edit Tool Schemas
# ============================================================================

class EditParams(BaseModel):
    """
    Input parameters for the edit tool.
    
    The edit tool performs surgical text replacements. It finds oldText
    (with fuzzy matching for whitespace/quotes) and replaces it with newText.
    The oldText must be unique in the file.
    """
    
    path: str = Field(
        ...,
        description="Path to the file to edit (relative or absolute)",
        examples=["src/main.py", "config.json"]
    )
    
    old_text: str = Field(
        ...,
        description="Exact text to find and replace (must match exactly including whitespace)",
        examples=["def old_function():\n    pass", "old_value = 123"]
    )
    
    new_text: str = Field(
        ...,
        description="New text to replace the old text with",
        examples=["def new_function():\n    return True", "new_value = 456"]
    )
    
    class Config:
        extra = "forbid"
        use_enum_values = True


class EditToolDetails(BaseModel):
    """
    Metadata about edit tool execution.
    
    Provides unified diff showing the changes made.
    """
    
    diff: str = Field(
        ...,
        description="Unified diff string showing changes with line numbers"
    )
    
    first_changed_line: Optional[int] = Field(
        None,
        description="Line number of the first change in the new file (for editor navigation)"
    )


# ============================================================================
# Support DB Tool Schemas
# ============================================================================


class GetCustomerOverviewParams(BaseModel):
    """Input parameters for get_customer_overview tool."""

    user_id: str = Field(
        ...,
        description="Unique user identifier to fetch support overview for",
        examples=["client789"],
    )

    class Config:
        extra = "forbid"
        use_enum_values = True


class GetRecentOperationsParams(BaseModel):
    """Input parameters for get_recent_operations tool."""

    user_id: str = Field(
        ...,
        description="Unique user identifier whose recent operations should be fetched",
        examples=["client789"],
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of transfers and devices to return",
    )

    class Config:
        extra = "forbid"
        use_enum_values = True


class GetActiveIncidentsParams(BaseModel):
    """Input parameters for get_active_incidents tool."""

    class Config:
        extra = "forbid"
        use_enum_values = True


class Tool(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    tool_type: ToolTypeEnum
    