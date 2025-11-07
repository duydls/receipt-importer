#!/usr/bin/env python3
"""
RD OCR Line Normalization
Pre-cleans OCR text lines for RD receipts before regex parsing.

Handles:
- Colon-decimal replacement (32:15 → 32.15)
- Garbage token removal (PAS, cP, aE)
- Stray pipe removal
- Trailing junk removal (qT)
- Non-item line skipping
- Continuation line joining
"""

import re
import logging

logger = logging.getLogger(__name__)

# Patterns for non-item lines (skip these)
NON_ITEM_PATTERNS = [
    r'^SUBTOTAL',
    r'^TOTAL\s+(?:PAID|ON\s+ACCOUNT|TAX)',
    r'^IL\s+(?:FOOD\s+)?TAX',
    r'^TRANSACTION\s+TOTAL',
    r'^TOTAL\s+PAID',
    r'^FINAL\s+TOTAL',
    r'^MC\s*/\s*VISA',
    r'^VISA\s+\d+',
    r'^MC\s+\d+',
    r'^MASTERCARD\s+\d+',
    r'^AMEX\s+\d+',
    r'^APPROVAL\s*#',
    r'^REFERENCE\s+\d+',
    r'^Contactless',
    r'^Previous\s+Balance',
    r'^UPC\s+Item\s+Description',  # Header row
    r'^Item\s+Description\s+Unit\s+Price',  # Header row variant
]


def normalize_rd_lines(ocr_lines: list) -> list:
    """
    Normalize RD OCR lines before regex parsing.
    
    Args:
        ocr_lines: List of raw OCR text lines
        
    Returns:
        List of normalized lines (non-item lines removed, continuation lines joined)
    """
    if not ocr_lines:
        return []
    
    normalized_lines = []
    i = 0
    
    while i < len(ocr_lines):
        line = ocr_lines[i].strip()
        
        # Skip empty lines
        if not line:
            i += 1
            continue
        
        # Check if this is a non-item line (skip it)
        is_non_item = False
        for pattern in NON_ITEM_PATTERNS:
            if re.match(pattern, line, re.IGNORECASE):
                is_non_item = True
                break
        
        if is_non_item:
            i += 1
            continue
        
        # Apply line-level cleaning
        cleaned_line = _clean_rd_line(line)
        
        # Check if this line looks like a continuation (doesn't start with UPC+item# and doesn't end with amount)
        # Continuation lines should be joined to previous line
        is_continuation = _is_continuation_line(cleaned_line)
        
        if is_continuation and normalized_lines:
            # Join to previous line
            normalized_lines[-1] = normalized_lines[-1] + ' ' + cleaned_line
        else:
            # New line (or first line)
            normalized_lines.append(cleaned_line)
        
        i += 1
    
    return normalized_lines


def _clean_rd_line(line: str) -> str:
    """
    Clean a single RD OCR line.
    
    Handles:
    - Colon-decimal replacement (32:15 → 32.15)
    - Garbage token removal (PAS, cP, aE)
    - Stray pipe removal
    - Trailing junk removal (qT)
    
    Args:
        line: Raw OCR line
        
    Returns:
        Cleaned line
    """
    cleaned = line
    
    # Replace colon-decimals: 32:15 → 32.15 (but only in price contexts)
    # Pattern: digit(s) : digit(s) where it looks like a price
    cleaned = re.sub(r'(\d+):(\d{1,2})\b', r'\1.\2', cleaned)
    
    # Drop tiny garbage tokens between price and qty
    # Pattern: price followed by garbage (PAS, cP, aE) followed by qty or U/C
    # Examples: "32.15 cP aE 1 U (T)" → "32.15 1 U (T)"
    cleaned = re.sub(r'(\d+[.,]\d{1,2})\s+(?:PAS|cP|aE|pA|aS)\s+(\d+\s+[UC]|U|C)', r'\1 \2', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'(\d+[.,]\d{1,2})\s+(?:PAS|cP|aE|pA|aS)\s+(\d+)', r'\1 \2', cleaned, flags=re.IGNORECASE)
    
    # Remove stray pipe characters | (but preserve if it's part of a valid pattern)
    # Remove standalone | or | at start/end
    cleaned = re.sub(r'^\|\s*', '', cleaned)
    cleaned = re.sub(r'\s*\|\s*$', '', cleaned)
    cleaned = re.sub(r'\s+\|\s+', ' ', cleaned)  # Remove | in middle (with spaces)
    
    # Remove trailing 1-3 letter junk after totals (e.g., qT, T, q)
    # Pattern: price or amount followed by 1-3 letter junk at end
    # But preserve "U (T)" and "C (T)" patterns
    cleaned = re.sub(r'(\d+[.,]\d{1,2})\s*([a-z]{1,3})\s*$', r'\1', cleaned, flags=re.IGNORECASE)
    # But restore U (T) and C (T) if they were removed
    # This is a bit tricky - we'll handle it more carefully
    # Actually, let's be more specific: remove trailing junk that's NOT U (T) or C (T)
    cleaned = re.sub(r'(\d+[.,]\d{1,2})\s+(?!U\s*\(?T\)?|C\s*\(?T\)?)([a-z]{1,3})\s*$', r'\1', cleaned, flags=re.IGNORECASE)
    
    # Clean up extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned


def _is_continuation_line(line: str) -> bool:
    """
    Check if a line is a continuation (should be joined to previous line).
    
    A line is a continuation if:
    - It doesn't start with UPC (10-14 digits) + item# (5-10 digits)
    - It doesn't end with an amount (price pattern)
    
    Args:
        line: OCR line to check
        
    Returns:
        True if line is a continuation, False otherwise
    """
    # Check if line starts with UPC + item# pattern
    upc_item_pattern = r'^(\d{10,14})\s+(\d{5,10})\s+'
    if re.match(upc_item_pattern, line):
        return False  # This is a new item line
    
    # Check if line ends with an amount (price pattern)
    # Pattern: digit(s) + [.,:] + 1-2 digits at end
    price_at_end = re.search(r'\d+[.,:]\d{1,2}\s*$', line)
    if price_at_end:
        return False  # This line has an amount, likely complete
    
    # Otherwise, it's likely a continuation
    return True

