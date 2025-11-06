#!/usr/bin/env python3
"""
Name Hygiene Module
Extracts UPC (12-14 digits, including spaced/hyphenated) and Item#/SKU from product_name,
strips them out, and creates a clean_name for classification.

RD-specific enhancements:
- Line-start parsing: UPC (8-14 digits) and RD Item# (5-8 digits) at beginning of line
- Size/spec extraction: CT, LB, GAL/SGAL, OZ, multi-packs (3000CT, 100 CT, 10LB, 5-GAL)
- "No Charge" detection: sets is_no_charge=true for zero-price items
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


def extract_rd_line_start_codes(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    RD-specific: Extract UPC and Item# from the start of a line.
    Format: "76069502838 2230129 — SKYLINE ..." or "76069501732 1120153 — ..."
    
    Rules:
    - First token: 8-14 digits = UPC
    - Second token: 5-8 digits = RD Item#
    - Separator: "—", " - ", or double spaces
    
    Args:
        text: Text to parse (should be product_name from RD receipt)
        
    Returns:
        Tuple of (upc, item_number) or (None, None)
    """
    if not text:
        return None, None
    
    # Pattern to match line-start codes: "UPC Item# — Description" or "UPC Item# Description"
    # Examples: "76069502838 2230129 — SKYLINE", "76069501732 1120153 — "
    line_start_pattern = re.compile(
        r'^(\d{8,14})\s+(\d{5,8})\s*[—\-]\s*(.*)$',  # UPC Item# — Description
        re.IGNORECASE
    )
    
    match = line_start_pattern.match(text)
    if match:
        upc = match.group(1).strip()
        item_num = match.group(2).strip()
        # Validate: UPC should be 8-14 digits, Item# should be 5-8 digits
        if len(upc) >= 8 and len(upc) <= 14 and upc.isdigit():
            if len(item_num) >= 5 and len(item_num) <= 8 and item_num.isdigit():
                logger.debug(f"RD line-start codes: UPC={upc}, Item#={item_num} from '{text[:50]}...'")
                return upc, item_num
    
    # Fallback: try without em dash separator (double spaces)
    line_start_pattern2 = re.compile(
        r'^(\d{8,14})\s+(\d{5,8})\s{2,}(.*)$',  # UPC Item#  Description (double spaces)
        re.IGNORECASE
    )
    
    match2 = line_start_pattern2.match(text)
    if match2:
        upc = match2.group(1).strip()
        item_num = match2.group(2).strip()
        if len(upc) >= 8 and len(upc) <= 14 and upc.isdigit():
            if len(item_num) >= 5 and len(item_num) <= 8 and item_num.isdigit():
                logger.debug(f"RD line-start codes (no dash): UPC={upc}, Item#={item_num} from '{text[:50]}...'")
                return upc, item_num
    
    return None, None


def extract_size_spec(text: str) -> Optional[str]:
    """
    Extract size/spec tokens from text.
    Detects: CT, LB, GAL/SGAL, OZ, and multi-packs (3000CT, 100 CT, 10LB, 5-GAL).
    
    Examples:
    - "3000CT" -> "3000CT"
    - "100 CT" -> "100 CT"
    - "10LB" -> "10LB"
    - "5-GAL" -> "5-GAL"
    - "32 OZ" -> "32 OZ"
    - "SGAL" -> "SGAL"
    
    Args:
        text: Text to search for size/spec tokens
        
    Returns:
        Size/spec string or None
    """
    if not text:
        return None
    
    # Patterns for size/spec tokens
    # Multi-pack patterns: "3000CT", "100 CT", "10LB", "5-GAL"
    size_patterns = [
        # Multi-pack with number: "3000CT", "100 CT", "10LB", "5-GAL"
        re.compile(r'\b(\d+(?:\s*|-)?(?:CT|LB|GAL|SGAL|OZ|OZ\.?))\b', re.IGNORECASE),
        # Standalone units: "CT", "LB", "GAL", "SGAL", "OZ" (but not at start of line)
        re.compile(r'(?<!\d)\b(CT|LB|GAL|SGAL|OZ\.?)\b(?!\d)', re.IGNORECASE),
    ]
    
    for pattern in size_patterns:
        matches = pattern.findall(text)
        if matches:
            # Return the first match (most likely to be the size/spec)
            size_spec = matches[0] if isinstance(matches[0], str) else matches[0][0] if matches[0] else None
            if size_spec:
                # Normalize: uppercase for consistency
                size_spec = size_spec.upper().strip()
                logger.debug(f"Extracted size_spec: {size_spec} from '{text[:50]}...'")
                return size_spec
    
    return None


def detect_no_charge(text: str) -> bool:
    """
    Detect "No Charge" markers in text.
    
    Examples:
    - "Aluminum Tray No Charge" -> True
    - "Chopsticks No Charge" -> True
    
    Args:
        text: Text to search for "No Charge" markers
        
    Returns:
        True if "No Charge" is detected, False otherwise
    """
    if not text:
        return False
    
    # Pattern for "No Charge" (case-insensitive)
    no_charge_pattern = re.compile(r'\bno\s+charge\b', re.IGNORECASE)
    return bool(no_charge_pattern.search(text))


def clean_product_name(name: str, upc: Optional[str] = None, item_number: Optional[str] = None, size_spec: Optional[str] = None) -> str:
    """
    Strip UPC, Item#, and size/spec from product name, returning clean name.
    
    Args:
        name: Original product name
        upc: UPC to strip (if already extracted)
        item_number: Item Number to strip (if already extracted)
        size_spec: Size/spec to strip (if already extracted)
        
    Returns:
        Clean product name with UPC, Item#, and size/spec removed
    """
    if not name:
        return ''
    
    clean = name
    
    # Strip UPC if provided (from start of line for RD, or anywhere for others)
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
            clean = re.sub(rf'^{re.escape(variant)}\s+', '', clean, flags=re.IGNORECASE)  # Start of line
            clean = re.sub(rf'\b{re.escape(variant)}\b', '', clean, flags=re.IGNORECASE)  # Anywhere else
    
    # Strip Item Number if provided (from start of line for RD, or anywhere for others)
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
            clean = re.sub(rf'^{re.escape(variant)}\s+', '', clean, flags=re.IGNORECASE)  # Start of line
            clean = re.sub(rf'\b{re.escape(variant)}\b', '', clean, flags=re.IGNORECASE)  # Anywhere else
    
    # Strip size/spec if provided
    if size_spec:
        # Remove size/spec in various formats
        size_variants = [
            size_spec,  # Exact match
            size_spec.replace('-', ' '),  # "5-GAL" -> "5 GAL"
            size_spec.replace(' ', '-'),  # "5 GAL" -> "5-GAL"
        ]
        for variant in size_variants:
            # Remove from anywhere in the text
            clean = re.sub(rf'\b{re.escape(variant)}\b', '', clean, flags=re.IGNORECASE)
    
    # Strip separators (em dash, regular dash, double spaces) from start
    clean = re.sub(r'^[—\-]\s+', '', clean).strip()
    clean = re.sub(r'^\s{2,}', '', clean).strip()
    
    # Strip "No Charge" from the end (will be handled separately)
    clean = re.sub(r'\bno\s+charge\b', '', clean, flags=re.IGNORECASE)
    
    # Clean up extra whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    
    return clean


def apply_name_hygiene(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply name hygiene to an item: extract UPC, Item#, size/spec from product_name,
    strip them out, and create clean_name.
    
    RD-specific enhancements:
    - Line-start parsing: Extract UPC (8-14 digits) and RD Item# (5-8 digits) from start of line
    - Size/spec extraction: Extract size tokens (CT, LB, GAL, OZ, etc.) to size_spec field
    - "No Charge" detection: Set is_no_charge=true if "No Charge" is found
    
    This function:
    1. Extracts UPC and Item# from product_name if not already in item
       - For RD: Try line-start parsing first (UPC Item# — Description)
       - Otherwise: Use general extraction patterns
    2. Extracts size/spec tokens to size_spec field
    3. Detects "No Charge" markers
    4. Strips UPC, Item#, and size/spec from product_name to create clean_name
    5. Sets display_name = clean_name (canonical short name)
    
    Args:
        item: Item dictionary with product_name
        
    Returns:
        Updated item dictionary with:
        - upc: Extracted UPC (if found)
        - item_number or vendor_item_no: Extracted Item Number (if found)
        - size_spec: Extracted size/spec tokens (if found)
        - clean_name: Product name with UPC/Item#/size stripped
        - display_name: Same as clean_name (canonical short name)
        - is_no_charge: True if "No Charge" detected
        - product_name: Original product_name (preserved)
    """
    # Get original product name
    product_name = item.get('product_name', '')
    if not product_name:
        return item
    
    # Detect vendor code
    vendor_code = item.get('detected_vendor_code') or item.get('vendor', '') or ''
    is_rd = 'RD' in vendor_code.upper() or 'RESTAURANT' in vendor_code.upper() or 'RESTAURANT_DEPOT' in vendor_code.upper()
    
    # Extract UPC and Item# if not already present
    # Priority: use existing fields if present, otherwise extract from product_name
    upc = item.get('upc')
    item_number = item.get('item_number') or item.get('vendor_item_no')
    
    # RD-specific: Try line-start parsing first
    if is_rd and not (upc and item_number):
        rd_upc, rd_item_num = extract_rd_line_start_codes(product_name)
        if rd_upc:
            upc = rd_upc
            item['upc'] = upc
        if rd_item_num:
            item_number = rd_item_num
            item['item_number'] = item_number
            item['vendor_item_no'] = item_number  # Also set vendor_item_no for RD
    
    # If UPC not in item, try general extraction
    if not upc:
        upc = extract_upc(product_name)
        if upc:
            item['upc'] = upc
    
    # If Item Number not in item, try general extraction
    if not item_number:
        item_number = extract_item_number(product_name)
        if item_number:
            item['item_number'] = item_number
            if is_rd:
                item['vendor_item_no'] = item_number  # Also set vendor_item_no for RD
    
    # Extract size/spec
    size_spec = item.get('size_spec')
    if not size_spec:
        size_spec = extract_size_spec(product_name)
        if size_spec:
            item['size_spec'] = size_spec
    
    # Detect "No Charge"
    is_no_charge = detect_no_charge(product_name)
    if is_no_charge:
        item['is_no_charge'] = True
    
    # Strip UPC, Item#, and size/spec from product_name to create clean_name
    clean_name = clean_product_name(product_name, upc=upc, item_number=item_number, size_spec=size_spec)
    
    # Preserve original for audit
    item['raw_name_original'] = product_name
    
    # Apply alias mappings (fix typos like "Potate → Potato")
    from .alias_loader import apply_aliases
    aliased_name = apply_aliases(clean_name, keep_cjk=True)
    
    # Set clean_name and display_name (canonical short name)
    item['clean_name'] = clean_name
    item['display_name'] = clean_name  # Display name policy: canonical short name
    
    # Note: canonical_name will be set by normalize_item_name() before classification
    # It uses fold_ws() which keeps CJK characters and collapses whitespace
    # This ensures "Mousse\nCake" becomes "Mousse Cake" for matching
    
    # Preserve original product_name
    # product_name is already in item, so we don't need to set it
    
    logger.debug(
        f"Name hygiene{' (RD)' if is_rd else ''}: '{product_name[:50]}...' -> "
        f"clean='{clean_name[:50]}...', UPC={upc}, Item#={item_number}, size_spec={size_spec}, "
        f"is_no_charge={is_no_charge}"
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

