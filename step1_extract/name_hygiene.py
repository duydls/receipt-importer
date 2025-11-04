#!/usr/bin/env python3
"""
Name Hygiene Module
Extracts UPC (12-14 digits, including spaced/hyphenated) and Item#/SKU from product_name,
strips them out, and creates a clean_name for classification.
"""

import re
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# UPC patterns: 12-14 digits, allowing spaces/hyphens in the middle
# Examples: "123456789012", "123 456 789 012", "123-456-789-012", "1234567890123", "12345678901234"
UPC_PATTERNS = [
    # 12 digits with spaces/hyphens: "123 456 789 012" or "123-456-789-012"
    re.compile(r'(?<![0-9])([0-9]{1,3}[-\s][0-9]{1,3}[-\s][0-9]{1,3}[-\s][0-9]{1,3})(?![0-9])', re.IGNORECASE),
    # 12-14 continuous digits
    re.compile(r'(?<![0-9])([0-9]{12,14})(?![0-9])', re.IGNORECASE),
]

# Item Number/SKU patterns (covers "Item No/Item #/SKU/MFR/RD/ITM")
# Examples: "12345", "ITM12345", "RD12345", "MFR-12345", "SKU-12345"
ITEM_NUMBER_PATTERNS = [
    # Prefixed patterns: "Item No 12345", "Item # 12345", "SKU 12345", "MFR 12345", "RD 12345", "ITM 12345"
    re.compile(r'(?i)(?:item\s*(?:no|#|number|num\.?)?|sku|mfr|rd|itm)[\s:]*([A-Z0-9\-]{4,15})', re.IGNORECASE),
    # Standalone alphanumeric codes (5-15 chars, no spaces/hyphens in middle, but allow at boundaries)
    # Exclude pure numbers (handled by UPC) and very short codes
    re.compile(r'(?<![A-Z0-9])([A-Z]{2,}[0-9]{3,}[A-Z0-9]*|[0-9]{5,}[A-Z]{2,}[A-Z0-9]*)(?![A-Z0-9])', re.IGNORECASE),
    # Item numbers that might be at start of line: "12345 Description"
    re.compile(r'^(?<![0-9])([0-9]{5,10})(?=\s+[A-Z])', re.IGNORECASE),
]


def extract_upc(text: str) -> Optional[str]:
    """
    Extract UPC from text.
    UPC is 12-14 digits, optionally spaced or hyphenated.
    
    Args:
        text: Text to search for UPC
        
    Returns:
        UPC string (digits only, no spaces/hyphens) or None
    """
    if not text:
        return None
    
    # Try each pattern
    for pattern in UPC_PATTERNS:
        match = pattern.search(text)
        if match:
            upc = match.group(1)
            # Normalize: remove spaces and hyphens, keep only digits
            upc_clean = re.sub(r'[-\s]', '', upc)
            # Validate: must be 12-14 digits
            if len(upc_clean) >= 12 and len(upc_clean) <= 14 and upc_clean.isdigit():
                logger.debug(f"Extracted UPC: {upc_clean} from '{text[:50]}...'")
                return upc_clean
    
    return None


def extract_item_number(text: str) -> Optional[str]:
    """
    Extract Item Number/SKU from text.
    Covers "Item No/Item #/SKU/MFR/RD/ITM" patterns.
    
    Args:
        text: Text to search for Item Number
        
    Returns:
        Item Number string or None
    """
    if not text:
        return None
    
    # Try each pattern
    for pattern in ITEM_NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            item_num = match.group(1).strip()
            # Basic validation: not too short, not too long
            if len(item_num) >= 4 and len(item_num) <= 15:
                # Exclude if it's clearly a UPC (12+ digits)
                if not (item_num.isdigit() and len(item_num) >= 12):
                    logger.debug(f"Extracted Item#: {item_num} from '{text[:50]}...'")
                    return item_num
    
    return None


def clean_product_name(name: str, upc: Optional[str] = None, item_number: Optional[str] = None) -> str:
    """
    Strip UPC and Item# from product name, returning clean name.
    
    Args:
        name: Original product name
        upc: UPC to strip (if already extracted)
        item_number: Item Number to strip (if already extracted)
        
    Returns:
        Clean product name with UPC and Item# removed
    """
    if not name:
        return ''
    
    clean = name
    
    # Strip UPC if provided
    if upc:
        # Remove UPC in various formats
        upc_variants = [
            upc,  # Exact match
            re.sub(r'(\d{4})', r'\1 ', upc),  # "1234 5678 9012"
            re.sub(r'(\d{4})', r'\1-', upc).rstrip('-'),  # "1234-5678-9012"
            ' '.join([upc[i:i+4] for i in range(0, len(upc), 4)])  # "1234 5678 9012"
        ]
        for variant in upc_variants:
            # Remove from start, middle, or end
            clean = re.sub(rf'\b{re.escape(variant)}\b', '', clean, flags=re.IGNORECASE)
    
    # Strip Item Number if provided
    if item_number:
        # Remove Item Number in various formats
        item_variants = [
            item_number,  # Exact match
            f"Item {item_number}",
            f"Item #{item_number}",
            f"Item No {item_number}",
            f"Item No. {item_number}",
            f"Item Number {item_number}",
            f"SKU {item_number}",
            f"MFR {item_number}",
            f"RD {item_number}",
            f"ITM {item_number}",
        ]
        for variant in item_variants:
            # Remove from start, middle, or end
            clean = re.sub(rf'\b{re.escape(variant)}\b', '', clean, flags=re.IGNORECASE)
    
    # Clean up extra whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    
    return clean


def apply_name_hygiene(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply name hygiene to an item: extract UPC and Item# from product_name,
    strip them out, and create clean_name.
    
    This function:
    1. Extracts UPC and Item# from product_name if not already in item
    2. Strips UPC and Item# from product_name to create clean_name
    3. Sets clean_name as the name to use for classification
    
    Args:
        item: Item dictionary with product_name
        
    Returns:
        Updated item dictionary with:
        - upc: Extracted UPC (if found)
        - item_number: Extracted Item Number (if found)
        - clean_name: Product name with UPC and Item# stripped
        - product_name: Original product_name (preserved)
    """
    # Get original product name
    product_name = item.get('product_name', '')
    if not product_name:
        return item
    
    # Extract UPC and Item# if not already present
    # Priority: use existing fields if present, otherwise extract from product_name
    upc = item.get('upc')
    item_number = item.get('item_number')
    
    # If UPC not in item, try to extract from product_name
    if not upc:
        upc = extract_upc(product_name)
        if upc:
            item['upc'] = upc
    
    # If Item Number not in item, try to extract from product_name
    if not item_number:
        item_number = extract_item_number(product_name)
        if item_number:
            item['item_number'] = item_number
    
    # Strip UPC and Item# from product_name to create clean_name
    clean_name = clean_product_name(product_name, upc=upc, item_number=item_number)
    
    # Set clean_name (this will be used for classification)
    item['clean_name'] = clean_name
    
    # Also set canonical_name for compatibility (if not already set)
    if 'canonical_name' not in item:
        item['canonical_name'] = clean_name
    
    # Preserve original product_name
    # product_name is already in item, so we don't need to set it
    
    logger.debug(
        f"Name hygiene: '{product_name[:50]}...' -> "
        f"clean='{clean_name[:50]}...', UPC={upc}, Item#={item_number}"
    )
    
    return item


def apply_name_hygiene_batch(items: list) -> list:
    """
    Apply name hygiene to a batch of items.
    
    Args:
        items: List of item dictionaries
        
    Returns:
        List of updated item dictionaries
    """
    return [apply_name_hygiene(item) for item in items]

