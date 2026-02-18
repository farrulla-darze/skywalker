"""
Image utilities for the read tool.

Handles MIME type detection, base64 encoding, and optional image resizing.
"""

import base64
import mimetypes
from pathlib import Path
from typing import Optional, Tuple


# Supported image MIME types
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/svg+xml",
    "image/tiff",
    "image/x-icon",
    "image/heic",
    "image/heif",
}

# Magic bytes for common image formats
MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",  # JPEG
    b"\x89PNG\r\n\x1a\n": "image/png",  # PNG
    b"GIF87a": "image/gif",  # GIF87a
    b"GIF89a": "image/gif",  # GIF89a
    b"RIFF": "image/webp",  # WebP (needs WEBP check after RIFF)
    b"BM": "image/bmp",  # BMP
    b"\x00\x00\x01\x00": "image/x-icon",  # ICO
    b"II*\x00": "image/tiff",  # TIFF (little-endian)
    b"MM\x00*": "image/tiff",  # TIFF (big-endian)
    b"<svg": "image/svg+xml",  # SVG (text-based)
}


def detect_image_mime_type(file_path: Path) -> Optional[str]:
    """
    Detect if a file is a supported image format.
    
    Uses magic bytes (file signature) for reliable detection,
    falling back to file extension if needed.
    
    Args:
        file_path: Path to the file
        
    Returns:
        MIME type string if image, None otherwise
        
    Example:
        >>> detect_image_mime_type(Path("photo.jpg"))
        'image/jpeg'
        >>> detect_image_mime_type(Path("script.py"))
        None
    """
    if not file_path.exists():
        return None
    
    try:
        # Read first 16 bytes for magic byte detection
        with open(file_path, "rb") as f:
            header = f.read(16)
        
        # Check magic bytes
        for magic, mime_type in MAGIC_BYTES.items():
            if header.startswith(magic):
                # Special case for WebP: check for "WEBP" after "RIFF"
                if magic == b"RIFF":
                    if len(header) >= 12 and header[8:12] == b"WEBP":
                        return "image/webp"
                    else:
                        continue  # Not WebP, might be other RIFF format
                return mime_type
        
        # Fallback to extension-based detection
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type and mime_type in SUPPORTED_IMAGE_TYPES:
            return mime_type
        
    except (IOError, OSError):
        pass
    
    return None


def encode_image_to_base64(file_path: Path) -> str:
    """
    Read an image file and encode it to base64.
    
    Args:
        file_path: Path to the image file
        
    Returns:
        Base64-encoded string
        
    Example:
        >>> encoded = encode_image_to_base64(Path("photo.jpg"))
        >>> encoded[:20]
        '/9j/4AAQSkZJRgABAQAA'
    """
    with open(file_path, "rb") as f:
        image_bytes = f.read()
    
    return base64.b64encode(image_bytes).decode("ascii")


def get_image_dimensions(file_path: Path) -> Optional[Tuple[int, int]]:
    """
    Get image dimensions without loading the entire image.
    
    This is optional - only needed if you want to implement image resizing.
    Requires Pillow library.
    
    Args:
        file_path: Path to the image file
        
    Returns:
        Tuple of (width, height) or None if not an image
    """
    try:
        from PIL import Image
        
        with Image.open(file_path) as img:
            return img.size
    except ImportError:
        # Pillow not installed
        return None
    except Exception:
        # Not a valid image or other error
        return None


def resize_image_if_needed(
    image_data: str,
    mime_type: str,
    max_dimension: int = 2000
) -> Tuple[str, Optional[str]]:
    """
    Resize image if it exceeds max dimensions.
    
    This is optional and requires Pillow library.
    If Pillow is not installed, returns original image unchanged.
    
    Args:
        image_data: Base64-encoded image data
        mime_type: MIME type of the image
        max_dimension: Maximum width or height (default: 2000)
        
    Returns:
        Tuple of (resized_base64_data, dimension_note)
        dimension_note is None if no resize occurred
        
    Example:
        >>> resized, note = resize_image_if_needed(large_image, "image/jpeg")
        >>> print(note)
        'Image resized from 4000x3000 to 2000x1500'
    """
    try:
        from PIL import Image
        import io
        
        # Decode base64 to bytes
        image_bytes = base64.b64decode(image_data)
        
        # Open image
        img = Image.open(io.BytesIO(image_bytes))
        original_width, original_height = img.size
        
        # Check if resize needed
        if original_width <= max_dimension and original_height <= max_dimension:
            return image_data, None
        
        # Calculate new dimensions (preserve aspect ratio)
        if original_width > original_height:
            new_width = max_dimension
            new_height = int(original_height * (max_dimension / original_width))
        else:
            new_height = max_dimension
            new_width = int(original_width * (max_dimension / original_height))
        
        # Resize image
        resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Convert back to base64
        output_buffer = io.BytesIO()
        
        # Determine format from MIME type
        format_map = {
            "image/jpeg": "JPEG",
            "image/jpg": "JPEG",
            "image/png": "PNG",
            "image/gif": "GIF",
            "image/webp": "WEBP",
            "image/bmp": "BMP",
        }
        
        img_format = format_map.get(mime_type, "PNG")
        resized_img.save(output_buffer, format=img_format)
        
        resized_base64 = base64.b64encode(output_buffer.getvalue()).decode("ascii")
        
        # Create dimension note
        dimension_note = (
            f"Image resized from {original_width}x{original_height} "
            f"to {new_width}x{new_height}"
        )
        
        return resized_base64, dimension_note
        
    except ImportError:
        # Pillow not installed - return original
        return image_data, None
    except Exception:
        # Error during resize - return original
        return image_data, None


def format_dimension_note(
    original_size: Optional[Tuple[int, int]],
    resized_size: Optional[Tuple[int, int]]
) -> Optional[str]:
    """
    Format a human-readable dimension note.
    
    Args:
        original_size: Original (width, height) or None
        resized_size: Resized (width, height) or None
        
    Returns:
        Formatted note string or None
    """
    if not original_size:
        return None
    
    if resized_size and resized_size != original_size:
        return (
            f"Image resized from {original_size[0]}x{original_size[1]} "
            f"to {resized_size[0]}x{resized_size[1]}"
        )
    
    return f"Image dimensions: {original_size[0]}x{original_size[1]}"