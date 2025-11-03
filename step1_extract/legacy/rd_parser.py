#!/usr/bin/env python3
"""
Restaurant Depot (RD) - Specific Receipt Parser
Handles RD receipt format using layout rules from YAML:
  UPC Item Description Unit Price Qty Ext.Amount Tax
  Example: 2370002749 980356 CHXNUGGETBTRDTY10 LB 28.91 1 U(T) 28.91
"""

import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RDParser:
    """Parser for Restaurant Depot receipt format"""
    
    def __init__(self):
        """Initialize RD parser"""
        # Pattern for RD item format:
        # [UPC or Item_Number] [Item_Number or UPC] Description Unit_Price Qty U(T) Ext_Amount
        # Format depends on number size:
        #   - 10-13 digits = UPC
        #   - 5-10 digits = Item Number
        # Example: 2370002749 980356 CHXNUGGETBTRDTY10 LB 28.91 1 U(T) 28.91
        #          (UPC: 2370002749, Item#: 980356)
        # Example: 980356 2370002749 CHXNUGGETBTRDTY10 LB 28.91 1 U(T) 28.91
        #          (Item#: 980356, UPC: 2370002749)
        # Text variations may have extra spaces or missing characters
        self.item_pattern = re.compile(
            r'(\d{5,13})\s+(\d{5,13})\s+([A-Z][A-Z0-9\s/]+?)\s+(\d+\.\d{2})\s+(\d+(?:\.\d+)?)\s+[UC]\(T\)\s+(\d+\.\d{2})',
            re.IGNORECASE
        )
        
    def parse_rd_receipt(self, text: str, layout: Optional[Dict] = None, shared_rules: Optional[Dict] = None) -> List[Dict]:
        """
        Parse Restaurant Depot receipt text into items using layout patterns from YAML
        
        Args:
            text: Raw receipt text
            layout: Layout dictionary from layout_applier (contains line_patterns, etc.)
            shared_rules: Shared rules dictionary
            
        Returns:
            List of item dictionaries
        """
        # If layout is provided, use rule-driven parsing
        if layout:
            return self._parse_from_text_with_layout(text, layout, shared_rules or {})
        
        # No layout provided - this means no matching layout was found
        # Don't guess - return empty list so caller can handle fallback
        logger.debug("No layout provided to parse_rd_receipt - no matching layout found")
        return []
    
    def _parse_from_text_with_layout(self, text: str, layout: Dict, shared_rules: Dict) -> List[Dict]:
        """
        Parse RD receipt text using line patterns from layout YAML
        
        Args:
            text: Raw receipt text
            layout: Layout dictionary with line_patterns, number_identification, skip_patterns, etc.
            shared_rules: Shared rules dictionary
            
        Returns:
            List of item dictionaries
        """
        items = []
        lines = text.split('\n')
        
        # Filter out address lines
        try:
            from step1_extract.utils.address_filter import AddressFilter
            address_filter = AddressFilter()
            lines = address_filter.filter_address_lines(lines)
        except ImportError:
            pass
        
        # Get patterns from layout
        line_patterns = layout.get('line_patterns', [])
        number_identification = layout.get('number_identification', {})
        skip_patterns = layout.get('skip_patterns', [])
        
        # Build regex patterns from layout
        rd_item_pattern = None
        header_keywords = []
        
        for pattern_def in line_patterns:
            pattern_type = pattern_def.get('type', '')
            if pattern_type == 'rd_item':
                regex_str = pattern_def.get('regex', '')
                flags_str = pattern_def.get('flags', '')
                flags = 0
                if 'IGNORECASE' in flags_str:
                    flags |= re.IGNORECASE
                if regex_str:
                    rd_item_pattern = re.compile(regex_str, flags)
            elif pattern_type == 'header':
                header_keywords = pattern_def.get('keywords', [])
        
        # Use fallback pattern if not found in layout
        if not rd_item_pattern:
            rd_item_pattern = self.item_pattern
        
        # Skip header line
        header_found = False
        
        # Get number identification rules
        upc_min = number_identification.get('upc', {}).get('min_digits', 10)
        upc_max = number_identification.get('upc', {}).get('max_digits', 13)
        item_num_min = number_identification.get('item_number', {}).get('min_digits', 5)
        item_num_max = number_identification.get('item_number', {}).get('max_digits', 10)
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip until we find the header
            if header_keywords and all(keyword in line for keyword in header_keywords):
                header_found = True
                continue
            elif not header_keywords and 'UPC' in line and 'Item' in line and 'Description' in line:
                header_found = True
                continue
            
            # Skip lines before header
            if not header_found:
                continue
            
            # Skip summary lines
            line_upper = line.upper()
            if any(keyword in line_upper for keyword in skip_patterns):
                continue
            
            # Try to match RD item pattern
            match = rd_item_pattern.search(line)
            if match:
                try:
                    first_num = match.group(1)
                    second_num = match.group(2)
                    description = match.group(3).strip()
                    unit_price = float(match.group(4))
                    quantity = float(match.group(5))
                    ext_amount = float(match.group(6))
                    
                    # Determine UPC vs item_number based on digit count (from layout rules)
                    first_len = len(first_num)
                    second_len = len(second_num)
                    
                    if upc_min <= first_len <= upc_max:
                        # First is UPC
                        upc = first_num
                        item_number = second_num if item_num_min <= second_len <= item_num_max else None
                    elif item_num_min <= first_len <= item_num_max:
                        # First is item number
                        item_number = first_num
                        upc = second_num if upc_min <= second_len <= upc_max else None
                    else:
                        # Unclear - try to determine
                        if upc_min <= second_len <= upc_max:
                            upc = second_num
                            item_number = first_num if item_num_min <= first_len <= item_num_max else None
                        else:
                            # Both could be item numbers - use first as item_number
                            item_number = first_num
                            upc = None
                    
                    # Parse description to extract product name and size/UoM
                    product_name, size, uom = self._parse_description(description)
                    
                    item = {
                        'product_name': product_name,
                        'quantity': quantity,
                        'purchase_uom': uom,
                        'unit_price': unit_price,
                        'total_price': ext_amount,
                        'line_text': line,
                        'item_number': item_number,  # For vendor profile lookup
                    }
                    
                    # Only add UPC if we have it
                    if upc:
                        item['upc'] = upc
                    
                    items.append(item)
                except (ValueError, IndexError) as e:
                    logger.debug(f"Error parsing RD item line '{line[:50]}...': {e}")
                    continue
        
        return items
    
    def _parse_description(self, description: str) -> tuple:
        """
        Parse description to extract name, size, and unit
        
        Args:
            description: Product description (e.g., "CHXNUGGETBTRDTY10 LB", "FZMOZZSTXITBRD7 LB")
            
        Returns:
            Tuple of (product_name, size, uom)
        """
        # Try to extract size/unit patterns
        # Pattern: "PRODUCT_NAME [quantity] [unit]" or "PRODUCT_NAME [quantity][unit]"
        size_patterns = [
            (r'(.+?)\s+(\d+(?:\.\d+)?)\s*(LB|LBS|OZ|OZS|CT|PACK|PK|QT|QTS|GAL|GALS|EA|EACH|KG)\s*$', re.IGNORECASE),
            (r'(.+?)\s+(\d+(?:\.\d+)?)(LB|LBS|OZ|OZS|CT|PACK|PK|QT|QTS|GAL|GALS|EA|EACH|KG)\s*$', re.IGNORECASE),
            (r'(.+?)\s+(\d+(?:\.\d+)?)\s*(/|X|x)\s*(\d+)\s*(CT|PACK|PK)\s*$', re.IGNORECASE),  # e.g., "10 LB X 2 CT"
        ]
        
        for pattern, flags in size_patterns:
            match = re.search(pattern, description, flags)
            if match:
                product_name = match.group(1).strip()
                
                # Handle patterns with X/CT format
                if len(match.groups()) > 3 and match.group(3) in ['/', 'X', 'x']:
                    size_qty = match.group(2)
                    pack_count = match.group(4)
                    uom_text = match.group(5).upper()
                    # Format: "10 LB X 2 CT" -> size: "10 LB", uom: "CT", count_per_package: "2"
                    size = f"{size_qty} {uom_text if uom_text in ['LB', 'OZ', 'QT', 'GAL'] else ''} X {pack_count} CT"
                    uom = 'CT'
                else:
                    size = match.group(2)
                    uom_text = match.group(3).upper()
                    
                    # Normalize UoM
                    uom_map = {
                        'LB': 'LB', 'LBS': 'LB',
                        'OZ': 'OZ', 'OZS': 'OZ',
                        'CT': 'CT',
                        'PACK': 'CT', 'PK': 'CT',
                        'QT': 'QT', 'QTS': 'QT',
                        'GAL': 'GAL', 'GALS': 'GAL',
                        'EA': 'EACH', 'EACH': 'EACH',
                        'KG': 'KG',
                    }
                    uom = uom_map.get(uom_text, uom_text)
                
                return product_name, size, uom
        
        # No size/unit found, return whole description as product name
        return description, None, 'EACH'

