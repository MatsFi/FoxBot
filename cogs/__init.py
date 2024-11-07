"""Initialize the cogs package and define available cogs."""
from typing import List

# List of core cog modules that should be loaded
CORE_EXTENSIONS: List[str] = [
    "cogs.points",
    "cogs.players",
]

# Optional extensions that can be loaded
OPTIONAL_EXTENSIONS: List[str] = [
    "jishaku"  # Debugging extension
]

def get_extensions(include_optional: bool = False) -> List[str]:
    """Get list of extensions to load.
    
    Args:
        include_optional: Whether to include optional extensions
        
    Returns:
        List of extension module paths
    """
    if include_optional:
        return CORE_EXTENSIONS + OPTIONAL_EXTENSIONS
    return CORE_EXTENSIONS

# Module exports
__all__ = [
    "CORE_EXTENSIONS",
    "OPTIONAL_EXTENSIONS",
    "get_extensions"
]