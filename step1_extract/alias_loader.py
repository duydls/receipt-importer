#!/usr/bin/env python3
"""
Alias Loader
Loads and applies alias mappings from kb/aliase/aliase_general.yaml
Fixes typos like "Potate → Potato" before name normalization and matching.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Cache for loaded aliases
_alias_cache: Optional[Dict[str, str]] = None


def load_aliases() -> Dict[str, str]:
    """
    Load alias mappings from kb/aliase/aliase_general.yaml
    
    Returns:
        Dictionary mapping match strings to canonical strings
    """
    global _alias_cache
    
    if _alias_cache is not None:
        return _alias_cache
    
    _alias_cache = {}
    
    # Find the alias file (relative to project root)
    project_root = Path(__file__).parent.parent
    alias_file = project_root / 'kb' / 'aliase' / 'aliase_general.yaml'
    
    if not alias_file.exists():
        logger.warning(f"Alias file not found: {alias_file}. Alias normalization will be skipped.")
        return _alias_cache
    
    try:
        import yaml
        with open(alias_file, 'r', encoding='utf-8') as f:
            alias_data = yaml.safe_load(f)
        
        aliases_list = alias_data.get('aliases', [])
        for alias_entry in aliases_list:
            match_list = alias_entry.get('match', [])
            canonical = alias_entry.get('canonical', '')
            
            if canonical:
                # Map each match string to the canonical form
                for match_str in match_list:
                    if match_str:
                        _alias_cache[match_str] = canonical
                        logger.debug(f"Loaded alias: '{match_str}' -> '{canonical}'")
        
        logger.info(f"Loaded {len(_alias_cache)} alias mappings from {alias_file.name}")
        
    except Exception as e:
        logger.error(f"Error loading alias file {alias_file}: {e}", exc_info=True)
    
    return _alias_cache


def apply_aliases(text: str, keep_cjk: bool = True) -> str:
    """
    Apply alias mappings to text (fix typos like "Potate → Potato")
    
    Args:
        text: Text to apply aliases to
        keep_cjk: If True, preserve Chinese/Japanese/Korean characters (default: True)
                  Note: This parameter is kept for API compatibility but CJK characters are always preserved
    
    Returns:
        Text with aliases applied
    """
    if not text:
        return text
    
    aliases = load_aliases()
    if not aliases:
        return text
    
    # Apply aliases in order (longest matches first to avoid partial replacements)
    # Sort by length (longest first) to match "Potate Corn Dog" before "Potate"
    sorted_aliases = sorted(aliases.items(), key=lambda x: len(x[0]), reverse=True)
    
    import re
    result = text
    for match_str, canonical in sorted_aliases:
        # Case-insensitive replacement with word boundaries to avoid partial matches
        # Use word boundary to avoid partial matches (e.g., "Potate" in "Potato" should not match)
        pattern = r'\b' + re.escape(match_str) + r'\b'
        result = re.sub(pattern, canonical, result, flags=re.IGNORECASE)
    
    return result

