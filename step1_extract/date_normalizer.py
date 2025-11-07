#!/usr/bin/env python3
"""
Date Normalization Module
Normalizes receipt dates using a hierarchy of date fields.

Date Hierarchy (highest to lowest priority):
1. transaction_date - Actual transaction/purchase date (most accurate)
2. order_date - When order was placed
3. delivery_date - When items were delivered (useful for Wismettac)
4. invoice_date - When invoice was created
5. Other date fields - Fallback dates

This ensures all receipts have a consistent transaction_date field.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def normalize_receipt_date(receipt_data: Dict[str, Any]) -> Optional[str]:
    """
    Normalize receipt date using hierarchy of date fields.
    
    Hierarchy (highest to lowest priority):
    1. transaction_date - Actual transaction/purchase date
    2. order_date - When order was placed
    3. delivery_date - When items were delivered
    4. invoice_date - When invoice was created
    5. Other date fields (purchase_date, receipt_date, etc.)
    
    Args:
        receipt_data: Receipt data dictionary
        
    Returns:
        Normalized date string (MM/DD/YYYY format) or None if no date found
    """
    if not receipt_data:
        return None
    
    # Date field hierarchy (highest to lowest priority)
    date_fields = [
        'transaction_date',  # Highest priority - actual transaction date
        'order_date',        # When order was placed
        'delivery_date',     # When items were delivered (Wismettac uses this)
        'invoice_date',      # When invoice was created
        'purchase_date',     # Purchase date (fallback)
        'receipt_date',      # Receipt date (fallback)
        'date',              # Generic date field (fallback)
    ]
    
    # Try each date field in priority order
    for field in date_fields:
        date_value = receipt_data.get(field)
        if date_value:
            # Normalize the date value
            normalized_date = _normalize_date_value(date_value)
            if normalized_date:
                logger.debug(f"Using {field} for transaction_date: {normalized_date}")
                return normalized_date
    
    # If no date found, log warning
    logger.warning(f"No date found in receipt {receipt_data.get('filename', 'unknown')} - checked fields: {date_fields}")
    return None


def _normalize_date_value(date_value: Any) -> Optional[str]:
    """
    Normalize a date value to MM/DD/YYYY format.
    
    Handles various date formats:
    - String dates: "09/02/2025", "2025-09-02", "September 2, 2025"
    - Datetime objects
    - ISO format strings
    
    Args:
        date_value: Date value (string, datetime, or other)
        
    Returns:
        Normalized date string (MM/DD/YYYY) or None if invalid
    """
    if not date_value:
        return None
    
    # If already a string, try to parse it
    if isinstance(date_value, str):
        date_str = date_value.strip()
        if not date_str:
            return None
        
        # Try various date formats
        date_formats = [
            '%m/%d/%Y',      # 09/02/2025
            '%m-%d-%Y',      # 09-02-2025
            '%Y-%m-%d',      # 2025-09-02
            '%Y/%m/%d',      # 2025/09/02
            '%m/%d/%y',      # 09/02/25
            '%m-%d-%y',      # 09-02-25
            '%d/%m/%Y',      # 02/09/2025 (European format)
            '%d-%m-%Y',      # 02-09-2025
            '%B %d, %Y',     # September 2, 2025
            '%b %d, %Y',     # Sep 2, 2025
            '%Y-%m-%d %H:%M:%S',  # 2025-09-02 12:34:56
            '%m/%d/%Y %H:%M:%S',  # 09/02/2025 12:34:56
        ]
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                # Return in MM/DD/YYYY format
                return parsed_date.strftime('%m/%d/%Y')
            except ValueError:
                continue
        
        # If all formats fail, try to extract date-like patterns
        import re
        # Pattern: MM/DD/YYYY or MM-DD-YYYY
        date_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', date_str)
        if date_match:
            month, day, year = date_match.groups()
            # Normalize year to 4 digits
            if len(year) == 2:
                year_int = int(year)
                # Assume 2000s for years 00-50, 1900s for 51-99
                year = f"20{year}" if year_int <= 50 else f"19{year}"
            # Normalize month and day to 2 digits
            month = month.zfill(2)
            day = day.zfill(2)
            try:
                # Validate the date
                datetime.strptime(f"{month}/{day}/{year}", '%m/%d/%Y')
                return f"{month}/{day}/{year}"
            except ValueError:
                pass
        
        # If still no match, return None
        logger.debug(f"Could not parse date string: {date_str}")
        return None
    
    # If it's a datetime object, format it
    elif isinstance(date_value, datetime):
        return date_value.strftime('%m/%d/%Y')
    
    # Otherwise, try to convert to string and parse
    else:
        try:
            date_str = str(date_value)
            return _normalize_date_value(date_str)
        except Exception:
            return None


def apply_date_hierarchy(receipt_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply date hierarchy to receipt data, setting transaction_date from available date fields.
    
    This function:
    1. Looks for all date fields in the receipt
    2. Uses the hierarchy to select the best date
    3. Sets transaction_date if not already set
    4. Preserves all original date fields for reference
    
    Args:
        receipt_data: Receipt data dictionary
        
    Returns:
        Updated receipt data dictionary with normalized transaction_date
    """
    if not receipt_data:
        return receipt_data
    
    # If transaction_date is already set and valid, keep it
    existing_transaction_date = receipt_data.get('transaction_date')
    if existing_transaction_date and _normalize_date_value(existing_transaction_date):
        logger.debug(f"transaction_date already set: {existing_transaction_date}")
        return receipt_data
    
    # Normalize date using hierarchy
    normalized_date = normalize_receipt_date(receipt_data)
    
    if normalized_date:
        # Set transaction_date if not already set or if it's invalid
        if not existing_transaction_date or not _normalize_date_value(existing_transaction_date):
            receipt_data['transaction_date'] = normalized_date
            logger.debug(f"Set transaction_date from date hierarchy: {normalized_date}")
        
        # Also set order_date if not set (for backward compatibility)
        if not receipt_data.get('order_date'):
            receipt_data['order_date'] = normalized_date
    
    return receipt_data

