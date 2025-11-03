#!/usr/bin/env python3
"""
Receipt Line Engine - Generic YAML-driven receipt parsing

Applies patterns from YAML layouts to extract items from receipt text.
No vendor-specific logic - all patterns come from YAML rules.

Python = engine; YAML = business logic.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class ReceiptLineEngine:
    """
    Generic receipt line parser that applies patterns from YAML layouts.
    
    No vendor-specific logic - all patterns, matching rules, and field extraction
    come from the layout dictionary provided by layout_applier.py.
    """
    
    def __init__(self):
        """Initialize receipt line engine"""
        pass
    
    def parse_receipt_text(self, text: str, layout: Dict, shared_rules: Optional[Dict] = None) -> List[Dict]:
        """
        Parse receipt text using patterns from layout YAML
        
        Args:
            text: Raw receipt text from PDF
            layout: Layout dictionary with line_patterns, merge_multiline, summary_keywords, etc.
            shared_rules: Shared rules dictionary (optional, for normalization, etc.)
            
        Returns:
            List of item dictionaries
        """
        if not text or not layout:
            return []
        
        shared_rules = shared_rules or {}
        
        # Filter out address lines first
        try:
            from .utils.address_filter import AddressFilter
            address_filter = AddressFilter()
            lines_list = text.split('\n')
            filtered_lines_list = address_filter.filter_address_lines(lines_list)
            text = '\n'.join(filtered_lines_list)
        except ImportError:
            logger.debug("Address filter not available, continuing without filtering")
        
        # Split text into lines
        lines = [line.strip() for line in text.split('\n')]
        
        # Check if this is a tabular-style receipt (RD style with header) or multiline (Costco style)
        line_patterns = layout.get('line_patterns', [])
        
        # Check for header-based parsing (RD style)
        has_header = any(pattern.get('type') == 'header' for pattern in line_patterns)
        has_rd_item = any(pattern.get('type') == 'rd_item' for pattern in line_patterns)
        
        if has_header or has_rd_item:
            # RD-style parsing: header-based with single-line items
            return self._parse_header_based(lines, layout, shared_rules)
        else:
            # Costco-style parsing: multiline with item codes
            return self._parse_multiline(lines, layout, shared_rules)
    
    def _parse_header_based(self, lines: List[str], layout: Dict, shared_rules: Dict) -> List[Dict]:
        """
        Parse header-based receipt (RD style: header line, then item lines)
        
        Args:
            lines: List of receipt lines
            layout: Layout dictionary
            shared_rules: Shared rules dictionary
            
        Returns:
            List of item dictionaries
        """
        items = []
        line_patterns = layout.get('line_patterns', [])
        number_identification = layout.get('number_identification', {})
        skip_patterns = layout.get('skip_patterns', [])
        
        # Build regex patterns from layout
        item_pattern = None
        header_keywords = []
        
        for pattern_def in line_patterns:
            pattern_type = pattern_def.get('type', '')
            if pattern_type in ['rd_item', 'item_line']:
                regex_str = pattern_def.get('regex', '')
                flags_str = pattern_def.get('flags', '')
                flags = 0
                if 'IGNORECASE' in flags_str:
                    flags |= re.IGNORECASE
                if regex_str:
                    item_pattern = re.compile(regex_str, flags)
            elif pattern_type == 'header':
                header_keywords = pattern_def.get('keywords', [])
        
        if not item_pattern:
            logger.warning("No item pattern found in layout for header-based parsing")
            return []
        
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
            elif not header_keywords and any(keyword in line for keyword in ['UPC', 'Item', 'Description']):
                header_found = True
                continue
            
            # Skip lines before header
            if not header_found:
                continue
            
            # Skip summary lines
            line_upper = line.upper()
            if any(keyword in line_upper for keyword in skip_patterns):
                continue
            
            # Try to match item pattern
            match = item_pattern.search(line)
            if match:
                try:
                    item = self._extract_item_from_match(match, line, layout, number_identification, shared_rules)
                    if item:
                        # Add parsed_by from layout
                        parsed_by = layout.get('parsed_by')
                        if parsed_by:
                            item['parsed_by'] = parsed_by
                        items.append(item)
                except (ValueError, IndexError) as e:
                    logger.debug(f"Error parsing item line '{line[:50]}...': {e}")
                    continue
        
        return items
    
    def _parse_multiline(self, lines: List[str], layout: Dict, shared_rules: Dict) -> List[Dict]:
        """
        Parse multiline receipt (Costco style: item codes on separate lines, products on following lines)
        
        Args:
            lines: List of receipt lines
            layout: Layout dictionary
            shared_rules: Shared rules dictionary
            
        Returns:
            List of item dictionaries
        """
        items = []
        
        # Get configuration from layout
        line_patterns = layout.get('line_patterns', [])
        merge_multiline = layout.get('merge_multiline', False)
        max_merge_distance = layout.get('max_merge_distance', 10)
        summary_keywords = layout.get('summary_keywords', ['SUBTOTAL', 'TAX', 'TOTAL'])
        
        # Find summary section start
        summary_start_line = len(lines)
        for idx, line in enumerate(lines):
            line_upper = line.upper()
            if any(keyword in line_upper for keyword in summary_keywords):
                summary_start_line = idx
                break
        
        # Collect item codes and product/price pairs using patterns from layout
        item_codes = {}  # {line_idx: item_code}
        product_price_pairs = []  # List of (product_start_line, product_lines, price_line, price_value)
        summary_items = []
        used_skus = set()
        
        # Build regex patterns from layout
        pattern_map = {}
        for pattern_def in line_patterns:
            pattern_type = pattern_def.get('type', '')
            regex_str = pattern_def.get('regex', '')
            flags_str = pattern_def.get('flags', '')
            if regex_str:
                flags = 0
                if 'IGNORECASE' in flags_str:
                    flags |= re.IGNORECASE
                pattern_map[pattern_type] = {
                    'regex': re.compile(regex_str, flags),
                    'groups': pattern_def.get('groups', []),
                    'max_lookback': pattern_def.get('max_lookback_lines', 5)
                }
        
        # Collect all item codes (before summary section)
        item_code_pattern = pattern_map.get('item_code_standalone', {}).get('regex')
        if item_code_pattern:
            for idx in range(summary_start_line):
                line = lines[idx]
                if not line:
                    continue
                match = item_code_pattern.match(line)
                if match:
                    item_code = match.group(0).strip()
                    item_codes[idx] = item_code
        
        # Collect summary items
        for idx in range(summary_start_line, len(lines)):
            line = lines[idx]
            if not line:
                continue
            line_upper = line.upper()
            is_summary = any(keyword in line_upper for keyword in summary_keywords)
            if is_summary:
                summary_item = self._extract_summary_item(line, layout)
                if summary_item:
                    summary_items.append(summary_item)
        
        # Process lines before summary section
        i = 0
        while i < summary_start_line:
            line = lines[i]
            
            if not line:
                i += 1
                continue
            
            # Skip item codes (already collected)
            if i in item_codes:
                i += 1
                continue
            
            # Check for item code + product + price on same line
            item_product_price_pattern = pattern_map.get('item_code_product_price', {}).get('regex')
            if item_product_price_pattern:
                match = item_product_price_pattern.match(line)
                if match:
                    groups = pattern_map['item_code_product_price'].get('groups', [])
                    if len(groups) >= 3:
                        item_code = match.group(1)
                        product_text = match.group(2).strip()
                        price_value = float(match.group(3))
                        
                        item = self._build_item_from_parts(
                            item_code=item_code,
                            product_text=product_text,
                            price_value=price_value,
                            line_text=line,
                            layout=layout,
                            shared_rules=shared_rules
                        )
                        if item:
                            items.append(item)
                            used_skus.add(item_code)
                    
                    i += 1
                    continue
            
            # Check for Instacart item_line pattern: product + quantity + price
            item_line_pattern = pattern_map.get('item_line', {}).get('regex')
            if item_line_pattern:
                match = item_line_pattern.match(line)
                if match:
                    groups = pattern_map['item_line'].get('groups', [])
                    if len(groups) >= 3:
                        product_text = match.group(1).strip()
                        quantity_value = float(match.group(2))
                        price_value = float(match.group(3))
                        
                        item = {
                            'product_name': product_text,
                            'quantity': quantity_value,
                            'total_price': price_value,
                            'unit_price': price_value / quantity_value if quantity_value > 0 else price_value,
                            'line_text': line,
                        }
                        items.append(item)
                    i += 1
                    continue
            
            # Check for Instacart item_line_simple pattern: product + price (quantity = 1)
            item_line_simple_pattern = pattern_map.get('item_line_simple', {}).get('regex')
            if item_line_simple_pattern:
                match = item_line_simple_pattern.match(line)
                if match and len(line) > 5:
                    groups = pattern_map['item_line_simple'].get('groups', [])
                    if len(groups) >= 2:
                        product_text = match.group(1).strip()
                        price_value = float(match.group(2))
                        
                        item = {
                            'product_name': product_text,
                            'quantity': 1.0,
                            'total_price': price_value,
                            'unit_price': price_value,
                            'line_text': line,
                        }
                        items.append(item)
                    i += 1
                    continue
            
            # Check for product + price on same line (generic pattern)
            product_price_pattern = pattern_map.get('product_price', {}).get('regex')
            if product_price_pattern:
                match = product_price_pattern.search(line)
                if match and len(line) > 5 and not re.match(r'^\d{1,10}\s+', line):
                    groups = pattern_map['product_price'].get('groups', [])
                    if len(groups) >= 2:
                        product_text = match.group(1).strip()
                        price_value = float(match.group(2))
                        product_price_pairs.append((i, [product_text], i, price_value))
                    i += 1
                    continue
            
            # Check for price-only line (if merge_multiline is enabled)
            # Support both 'price_only' and 'item_price_only' pattern types
            if merge_multiline:
                price_only_info = pattern_map.get('price_only', {}) or pattern_map.get('item_price_only', {})
                price_only_pattern = price_only_info.get('regex') if price_only_info else None
                max_lookback = price_only_info.get('max_lookback', 5) or price_only_info.get('max_lookback_lines', 5) if price_only_info else 5
                if price_only_pattern:
                    match = price_only_pattern.search(line)
                    if match and len(line.strip()) <= 12:
                        # Look backwards for product name parts
                        product_parts = []
                        product_start = i
                        
                        for j in range(max(0, i - max_lookback), i):
                            prev_line = lines[j]
                            if not prev_line:
                                continue
                            # Skip if it's an item code, price, or summary
                            if j in item_codes or price_only_pattern.search(prev_line):
                                continue
                            if any(keyword in prev_line.upper() for keyword in summary_keywords):
                                break
                            # This looks like a product part
                            if len(prev_line.strip()) > 1:
                                product_parts.insert(0, prev_line)
                                product_start = j
                        
                        if product_parts:
                            price_value = float(match.group(1))
                            product_price_pairs.append((product_start, product_parts, i, price_value))
                        
                        i += 1
                        continue
            
            i += 1
        
        # Match item codes to product/price pairs by distance (if merge_multiline is enabled)
        if merge_multiline:
            sorted_item_codes = sorted([(line_idx, code) for line_idx, code in item_codes.items() if code not in used_skus])
            used_product_indices = set()
            
            for item_code_line, item_code in sorted_item_codes:
                # Find closest unused product/price pair that comes after this item code
                best_match = None
                best_distance = float('inf')
                
                for idx, (product_start, product_lines, price_line, price_value) in enumerate(product_price_pairs):
                    if idx in used_product_indices:
                        continue
                    if price_line <= item_code_line:
                        continue  # Product must come after item code
                    
                    # Calculate distance
                    distance = price_line - item_code_line
                    if distance <= max_merge_distance and distance < best_distance:
                        best_distance = distance
                        best_match = (idx, product_start, product_lines, price_line, price_value)
                
                if best_match:
                    idx, product_start, product_lines, price_line, price_value = best_match
                    used_product_indices.add(idx)
                    
                    # Combine product lines
                    product_text = ' '.join(product_lines).strip()
                    item = self._build_item_from_parts(
                        item_code=item_code,
                        product_text=product_text,
                        price_value=price_value,
                        line_text=f"{item_code} {product_text} {price_value}",
                        layout=layout,
                        shared_rules=shared_rules
                    )
                    if item:
                        items.append(item)
        
        # Add summary items
        items.extend(summary_items)
        
        return items
    
    def _extract_item_from_match(self, match: re.Match, line: str, layout: Dict, 
                                 number_identification: Dict, shared_rules: Dict) -> Optional[Dict]:
        """
        Extract item dictionary from regex match (for header-based parsing)
        
        Args:
            match: Regex match object
            line: Original line text
            layout: Layout dictionary
            number_identification: Number identification rules
            shared_rules: Shared rules dictionary
            
        Returns:
            Item dictionary or None
        """
        try:
            # Extract groups based on match
            groups = match.groups()
            if len(groups) < 6:
                return None
            
            first_num = groups[0]
            second_num = groups[1]
            description = groups[2].strip()
            unit_price = float(groups[3])
            quantity = float(groups[4])
            ext_amount = float(groups[5])
            
            # Determine UPC vs item_number based on digit count (from layout rules)
            upc_min = number_identification.get('upc', {}).get('min_digits', 10)
            upc_max = number_identification.get('upc', {}).get('max_digits', 13)
            item_num_min = number_identification.get('item_number', {}).get('min_digits', 5)
            item_num_max = number_identification.get('item_number', {}).get('max_digits', 10)
            
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
            product_name, size, uom = self._parse_description(description, layout, shared_rules)
            
            item = {
                'product_name': product_name,
                'quantity': quantity,
                'purchase_uom': uom,
                'unit_price': unit_price,
                'total_price': ext_amount,
                'line_text': line,
                'item_number': item_number,
            }
            
            # Only add UPC if we have it
            if upc:
                item['upc'] = upc
            
            # Add parsed_by from layout
            parsed_by = layout.get('parsed_by')
            if parsed_by:
                item['parsed_by'] = parsed_by
            
            return item
            
        except (ValueError, IndexError) as e:
            logger.debug(f"Error extracting item from match: {e}")
            return None
    
    def _build_item_from_parts(self, item_code: Optional[str], product_text: str, price_value: float,
                                line_text: str, layout: Dict, shared_rules: Dict) -> Optional[Dict]:
        """
        Build item dictionary from parts (for multiline parsing)
        
        Args:
            item_code: Item code (optional)
            product_text: Product text/description
            price_value: Price value
            line_text: Original line text
            layout: Layout dictionary
            shared_rules: Shared rules dictionary
            
        Returns:
            Item dictionary or None
        """
        product_name, size, uom = self._parse_description(product_text, layout, shared_rules)
        
        if not product_name:
            return None
        
        item = {
            'item_code': item_code,
            'item_number': item_code,
            'product_name': product_name,
            'description': product_text,
            'quantity': 1.0,
            'purchase_uom': uom,
            'unit_price': price_value,
            'total_price': price_value,
            'line_text': line_text,
            'is_summary': False,
        }
        
        # Add parsed_by from layout
        parsed_by = layout.get('parsed_by')
        if parsed_by:
            item['parsed_by'] = parsed_by
        
        return item
    
    def _parse_description(self, description: str, layout: Dict, shared_rules: Dict) -> Tuple[str, Optional[str], str]:
        """
        Parse description to extract name, size, and unit
        
        Args:
            description: Product description
            layout: Layout dictionary
            shared_rules: Shared rules dictionary
            
        Returns:
            Tuple of (product_name, size, uom)
        """
        # Use UoM extraction rules if available (would come from 30_uom_extraction.yaml)
        # For now, do basic extraction
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
    
    def _extract_summary_item(self, line: str, layout: Dict) -> Optional[Dict]:
        """
        Extract summary item (subtotal, tax, total) from line
        
        Args:
            line: Summary line text
            layout: Layout dictionary
            
        Returns:
            Summary item dictionary or None
        """
        line_upper = line.upper()
        summary_type = None
        
        if 'SUBTOTAL' in line_upper:
            summary_type = 'subtotal'
        elif 'TAX' in line_upper:
            summary_type = 'tax'
        elif 'TOTAL' in line_upper:
            summary_type = 'total'
        
        if not summary_type:
            return None
        
        price_matches = list(re.finditer(r'(\d+\.\d{2})', line))
        if not price_matches:
            return None
        
        summary_item = {
            'product_name': line.strip(),
            'line_text': line,
            'is_summary': True,
            'summary_type': summary_type,
            'total_price': float(price_matches[-1].group(1)),
        }
        
        # Add parsed_by from layout
        parsed_by = layout.get('parsed_by')
        if parsed_by:
            summary_item['parsed_by'] = parsed_by
        
        return summary_item

