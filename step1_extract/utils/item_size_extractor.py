#!/usr/bin/env python3
"""
Item Size Extractor - Utility to ensure all items have unit_size and unit_uom
Extracts from knowledge base, product name, size_spec, raw_uom_text, or purchase_uom.
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# Module-level knowledge base cache
_KB_CACHE = None


def _load_knowledge_base() -> Dict[str, Any]:
    """Load knowledge base for size lookup."""
    global _KB_CACHE
    if _KB_CACHE is not None:
        return _KB_CACHE
    
    # Try input location first, then data fallback
    kb_candidates = [
        Path('data/step1_input/knowledge_base.json'),
        Path('data/knowledge_base.json'),
    ]
    
    for kb_path in kb_candidates:
        if kb_path.exists():
            try:
                with kb_path.open('r', encoding='utf-8') as f:
                    kb_raw = json.load(f)
                # Normalize into dict[str, dict] or dict[str, list]
                _KB_CACHE = kb_raw
                logger.debug(f"KB loaded with {len(kb_raw)} items from {kb_path}")
                return _KB_CACHE
            except Exception as e:
                logger.warning(f"Failed to load KB from {kb_path}: {e}")
    
    _KB_CACHE = {}
    return _KB_CACHE


def _extract_size_and_uom_from_text(text: str) -> Tuple[Optional[float], Optional[str]]:
    """Extract unit_size (number) and unit_uom (unit) from text."""
    if not text:
        return None, None
    
    text_str = str(text).strip()
    
    # Handle pack sizes: "6/5 lb" -> extract "5 lb" (the unit size, not pack count)
    # Pattern: "6/5 lb", "12/8.4 OZ", etc.
    pack_pattern = r'(\d+)\s*/\s*(\d+(?:\.\d+)?)\s*(lb|lbs|fl\s*oz|floz|oz|ct|count|gallon|gal|qt|qts)\b'
    pack_match = re.search(pack_pattern, text_str, re.I)
    if pack_match:
        # Extract the unit size (second number), not pack count
        size_num = float(pack_match.group(2))
        uom_text = pack_match.group(3).lower()
        
        # Normalize UoM
        uom_map = {
            'lb': 'lb', 'lbs': 'lb', 'pound': 'lb',
            'oz': 'oz', 'fl oz': 'oz', 'floz': 'oz',
            'gal': 'gal', 'gallon': 'gal',
            'qt': 'qt', 'qts': 'qt',
            'ct': 'ct', 'count': 'ct',
        }
        uom = uom_map.get(uom_text, uom_text)
        return size_num, uom
    
    # Pattern: "3 lbs", "64 fl oz", "1 gal", "12 ct", "32 oz", "10LB", "20 lb"
    # Also handle: "10LB", "20 lb", "6.98OZ", "5.29OZ", "~ 0.4 lbs" (with tilde)
    # Handle tilde prefix: "~ 0.4 lbs" -> extract "0.4 lbs"
    pattern = r'~?\s*(\d+(?:\.\d+)?)\s*(lb|lbs|fl\s*oz|floz|oz|ct|count|gallon|gal|qt|qts|each|ea|unit|units)\b'
    match = re.search(pattern, text_str, re.I)
    if match:
        size_num = float(match.group(1))
        uom_text = match.group(2).lower()
        
        # Normalize UoM
        uom_map = {
            'lb': 'lb', 'lbs': 'lb', 'pound': 'lb',
            'oz': 'oz', 'fl oz': 'oz', 'floz': 'oz',
            'gal': 'gal', 'gallon': 'gal',
            'qt': 'qt', 'qts': 'qt',
            'ct': 'ct', 'count': 'ct',
            'each': 'each', 'ea': 'each',
            'unit': 'each', 'units': 'each',
        }
        uom = uom_map.get(uom_text, uom_text)
        return size_num, uom
    
    # Try pattern without word boundary for cases like "10LB", "6.98OZ"
    pattern_no_boundary = r'(\d+(?:\.\d+)?)\s*(LB|LBS|OZ|CT|GAL|QT)\b'
    match_no_boundary = re.search(pattern_no_boundary, text_str, re.I)
    if match_no_boundary:
        size_num = float(match_no_boundary.group(1))
        uom_text = match_no_boundary.group(2).lower()
        
        # Normalize UoM
        uom_map = {
            'lb': 'lb', 'lbs': 'lb',
            'oz': 'oz',
            'gal': 'gal',
            'qt': 'qt',
            'ct': 'ct',
        }
        uom = uom_map.get(uom_text, uom_text)
        return size_num, uom
    
    return None, None


def ensure_unit_size_uom_qty(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensure all items have unit_size, unit_uom, and qty (quantity).
    Extracts from knowledge base, product name, size_spec, raw_uom_text, or purchase_uom.
    
    Args:
        items: List of item dictionaries
        
    Returns:
        List of item dictionaries with unit_size, unit_uom, and qty populated
    """
    # Load knowledge base for size lookup
    kb = _load_knowledge_base()
    
    for item in items:
        # Ensure qty (quantity) is set
        if 'quantity' not in item or not item.get('quantity'):
            item['quantity'] = 1
        
        # Try to extract unit_size and unit_uom if not already set
        if not item.get('unit_size') or not item.get('unit_uom'):
            # First, try KB if item_number is available
            kb_size_text = None
            item_number = str(item.get('item_number') or '').strip()
            if item_number and kb:
                kb_entry = kb.get(item_number)
                if isinstance(kb_entry, dict):
                    kb_size_text = kb_entry.get('size') or kb_entry.get('size_spec') or ''
                elif isinstance(kb_entry, list) and len(kb_entry) >= 3:
                    kb_size_text = kb_entry[2] if len(kb_entry) > 2 else ''
            
            # Try multiple sources in priority order
            # For Instacart items, prioritize 'size' field (from CSV) which contains formatted size like "500 ct", "64 fl oz"
            # For Wismettac items, prioritize 'size_spec' field (from Size/Spec column)
            # For other vendors, prioritize size_spec and raw fields
            vendor_code = (item.get('detected_vendor_code') or item.get('vendor') or '').upper()
            is_wismettac = 'WISMETTAC' in vendor_code
            
            sources = [
                kb_size_text,  # KB size (highest priority)
                item.get('size'),  # CSV size field (Instacart) - prioritize this for Instacart items
                item.get('size_spec'),  # Size/Spec field (Wismettac, RD) - prioritize this for Wismettac items
                item.get('raw_size_text'),  # raw_size_text often contains the same as size but may be more detailed
                item.get('raw_uom_text'),
                item.get('product_name'),
            ]
            
            # For Wismettac items, prioritize size_spec over size field
            if is_wismettac and item.get('size_spec') and item.get('size'):
                # Move size_spec before size in the sources list
                sources = [
                    kb_size_text,
                    item.get('size_spec'),  # Wismettac Size/Spec column (higher priority)
                    item.get('size'),
                    item.get('raw_size_text'),
                    item.get('raw_uom_text'),
                    item.get('product_name'),
                ]
            
            for source in sources:
                if not source:
                    continue
                
                unit_size, unit_uom = _extract_size_and_uom_from_text(str(source))
                if unit_size is not None and unit_uom:
                    if not item.get('unit_size'):
                        item['unit_size'] = unit_size
                    if not item.get('unit_uom'):
                        item['unit_uom'] = unit_uom
                    # If we got both, we're done
                    if item.get('unit_size') and item.get('unit_uom'):
                        break
            
            # Fallback: use purchase_uom if available (set unit_size to 1)
            if not item.get('unit_uom') and item.get('purchase_uom'):
                item['unit_uom'] = item['purchase_uom']
                if not item.get('unit_size'):
                    item['unit_size'] = 1.0
            
            # Final fallback: default to "each"
            if not item.get('unit_uom'):
                item['unit_uom'] = 'each'
                if not item.get('unit_size'):
                    item['unit_size'] = 1.0
    
    return items

