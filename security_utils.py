import re
import html
from typing import Any


def sanitize_for_log(value: Any) -> str:
    """
    Sanitize user input for safe logging to prevent log injection attacks.
    
    Args:
        value: Any value that might contain user input
    
    Returns:
        Sanitized string safe for logging
    """
    if value is None:
        return "None"
    
    # Convert to string
    text = str(value)
    
    # Remove or replace dangerous characters
    # Remove CRLF injection attempts
    text = re.sub(r'[\r\n\t]', ' ', text)
    
    # Remove ANSI escape sequences that could manipulate log output
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    
    # Remove null bytes and other control characters
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    
    # Limit length to prevent log flooding
    if len(text) > 200:
        text = text[:197] + "..."
    
    # HTML encode to prevent any remaining issues
    text = html.escape(text)
    
    return text


def sanitize_name(name: str) -> str:
    """
    Sanitize and validate name fields.
    
    Args:
        name: User-provided name
    
    Returns:
        Sanitized name
        
    Raises:
        ValueError: If name contains invalid characters
    """
    if not name or not isinstance(name, str):
        raise ValueError("Name must be a non-empty string")
    
    # Strip whitespace
    name = name.strip()
    
    # Check length
    if len(name) < 1:
        raise ValueError("Name cannot be empty")
    if len(name) > 100:
        raise ValueError("Name cannot exceed 100 characters")
    
    # Allow only letters, spaces, hyphens, apostrophes, and periods
    # This covers most international names while preventing injection
    if not re.match(r"^[a-zA-Z\u00C0-\u017F\u0100-\u024F\u1E00-\u1EFF\s\-'.]+$", name):
        raise ValueError("Name contains invalid characters. Only letters, spaces, hyphens, apostrophes, and periods are allowed")
    
    # Prevent excessive consecutive spaces or special characters
    if re.search(r'[\s\-\'.]{3,}', name):
        raise ValueError("Name contains too many consecutive spaces or special characters")
    
    # Clean up multiple spaces
    name = re.sub(r'\s+', ' ', name)
    
    return name


def validate_search_query(query: str) -> str:
    """
    Validate and sanitize search queries.
    
    Args:
        query: User search query
        
    Returns:
        Sanitized query
        
    Raises:
        ValueError: If query is invalid
    """
    if not query or not isinstance(query, str):
        raise ValueError("Search query must be a non-empty string")
    
    # Strip whitespace
    query = query.strip()
    
    # Check length
    if len(query) < 2:
        raise ValueError("Search query must be at least 2 characters")
    if len(query) > 200:
        raise ValueError("Search query cannot exceed 200 characters")
    
    # Remove potential injection attempts
    # Remove most special characters except basic punctuation
    query = re.sub(r'[<>"\'\x00-\x1F\x7F]', '', query)
    
    # Clean up multiple spaces
    query = re.sub(r'\s+', ' ', query)
    
    return query