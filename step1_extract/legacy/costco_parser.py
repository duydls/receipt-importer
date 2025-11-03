#!/usr/bin/env python3
"""
Costco-Specific Receipt Parser
Uses PDF text extraction (pdfplumber preferred, PDFMiner fallback) to parse Costco receipts
Costco receipts have structured format: [SKU] [item_name] [price]
Uses layout rules from YAML (20_costco_layout.yaml) for rule-driven parsing
Falls back to legacy parsing if no layout matches
"""

import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import pdfplumber (preferred for layout preservation)
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.debug("pdfplumber not available. Will fall back to PDFMiner.")

# Try to import PDFMiner (fallback)
try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
    PDFMINER_AVAILABLE = True
except ImportError:
    PDFMINER_AVAILABLE = False
    logger.debug("PDFMiner not available. Install: pip install pdfminer.six")

class CostcoParser:
    """Parser for Costco receipt format using PDF text extraction"""
    
    def __init__(self, item_map_path: Optional[Path] = None, ai_interpreter=None):
        """
        Initialize Costco parser
        
        Args:
            item_map_path: Optional path to JSON file mapping item codes to product names
            ai_interpreter: Optional AI interpreter for fallback parsing (Ollama/Transformers)
        """
        # Load item mapping if available
        self.item_map = {}
        if item_map_path and item_map_path.exists():
            try:
                with open(item_map_path, 'r', encoding='utf-8') as f:
                    self.item_map = json.load(f)
                logger.info(f"Loaded {len(self.item_map)} item mappings from {item_map_path}")
            except Exception as e:
                logger.warning(f"Failed to load item map from {item_map_path}: {e}")
        elif item_map_path:
            # Try default location
            default_path = Path(__file__).parent.parent / 'step1_rules' / 'costco_item_map.json'
            if default_path.exists():
                try:
                    with open(default_path, 'r', encoding='utf-8') as f:
                        self.item_map = json.load(f)
                    logger.info(f"Loaded {len(self.item_map)} item mappings from {default_path}")
                except Exception as e:
                    logger.debug(f"Could not load default item map: {e}")
        
        # AI interpreter for fallback parsing
        self.ai_interpreter = ai_interpreter
    
    def parse_costco_receipt(self, text: str, layout: Optional[Dict] = None, shared_rules: Optional[Dict] = None) -> List[Dict]:
        """
        Parse Costco receipt text into items using layout patterns from YAML
        
        Args:
            text: Raw receipt text from PDF
            layout: Layout dictionary from layout_applier (contains line_patterns, merge_multiline, etc.)
            shared_rules: Shared rules dictionary (for normalization, etc.)
            
        Returns:
            List of item dictionaries with summary items tagged
        """
        if not text:
            logger.warning("Empty text provided to parse_costco_receipt")
            return []
        
        # If layout is provided, use rule-driven parsing
        if layout:
            items = self._parse_from_text_with_layout(text, layout, shared_rules or {})
        else:
            # No layout provided - this means no matching layout was found
            # Don't guess - return empty list so caller can handle fallback
            logger.debug("No layout provided to parse_costco_receipt - no matching layout found")
            return []
        
        # If parsing failed or returned too few items, try AI interpreter as fallback
        if (not items or len(items) < 2) and self.ai_interpreter and self.ai_interpreter.enabled:
            logger.info(f"Costco parser returned {len(items)} items, trying AI interpreter fallback")
            try:
                ai_items = self.ai_interpreter.interpret_receipt(text, vendor='Costco')
                if ai_items and len(ai_items) > len(items):
                    logger.info(f"AI interpreter extracted {len(ai_items)} items (better than {len(items)})")
                    return ai_items
            except Exception as e:
                logger.warning(f"AI interpreter fallback failed: {e}")
        
        return items
    
    def _extract_summary_type(self, text: str) -> Optional[str]:
        """Extract summary type from text"""
        text_upper = text.upper()
        if 'SUBTOTAL' in text_upper:
            return 'subtotal'
        elif 'TAX' in text_upper:
            return 'tax'
        elif 'TOTAL' in text_upper:
            return 'total'
        elif 'CHANGE' in text_upper:
            return 'change'
        elif 'AMOUNT' in text_upper:
            return 'amount'
        return None
    
    def _parse_from_text(self, text: str) -> List[Dict]:
        """
        Parse Costco receipt from plain text using priority-based distance matching
        
        Costco receipt structure:
        - Item codes appear first (lines 6-25): 3923, 4032, 512515, 3, 506970, etc.
        - Products appear later (lines 12-30): LIMES 3 LB., WATERMELON 6.99 N, ORG STRAWBRY, etc.
        - Products can be split across multiple lines (ORG, STRAWBRY)
        - Prices can be on same line as product or separate line (6.49 N)
        
        New Strategy (Priority-Based Distance Matching):
        - Pass 1: Collect ALL item codes with their line positions
        - Pass 1: Collect ALL product/price pairs with their line positions
        - Pass 2: For each item code, find closest product/price pair that comes after it
        - Use line distance to prioritize matches (closest first)
        - Avoid duplicates by marking products/prices as used
        """
        items = []
        
        # Filter out address lines first
        try:
            from step1_extract.utils.address_filter import AddressFilter
            address_filter = AddressFilter()
            lines_list = text.split('\n')
            filtered_lines_list = address_filter.filter_address_lines(lines_list)
            text = '\n'.join(filtered_lines_list)
        except ImportError:
            pass  # Continue without filtering if module not available
        
        # Split text into lines
        lines = [line.strip() for line in text.split('\n')]
        
        # Find summary section start (SUBTOTAL, TAX, TOTAL)
        summary_start_line = len(lines)
        for idx, line in enumerate(lines):
            line_upper = line.upper()
            if any(keyword in line_upper for keyword in ['SUBTOTAL', 'TAX', 'TOTAL']):
                summary_start_line = idx
                break
        
        # ===== PASS 1: Collect ALL item codes and product/price pairs =====
        item_codes = {}  # {line_idx: item_code}
        product_price_pairs = []  # List of (product_start_line, product_lines, price_line, price_value)
        summary_items = []  # Summary lines to add later
        
        # Collect all item codes (before summary section)
        for idx in range(summary_start_line):
            line = lines[idx]
            if not line:
                continue
            item_code_match = re.match(r'^(\d{1,10})\s*$', line)
            if item_code_match:
                item_codes[idx] = item_code_match.group(1)
        
        # Collect summary items
        for idx in range(summary_start_line, len(lines)):
            line = lines[idx]
            if not line:
                continue
            line_upper = line.upper()
            is_summary = any(keyword in line_upper for keyword in [
                'SUBTOTAL', 'TAX', 'TOTAL', 'CHANGE', 'AMOUNT', 'MEMBER',
                'APPROVED', 'PURCHASE', 'TOTAL NUMBER OF ITEMS'
            ])
            if is_summary:
                summary_item = {
                    'vendor': 'Costco',
                    'product_name': line.strip(),
                    'line_text': line,
                    'is_summary': True,
                    'summary_type': self._extract_summary_type(line),
                }
                price_matches = list(re.finditer(r'(\d+\.\d{2})', line))
                if price_matches:
                    summary_item['total_price'] = float(price_matches[-1].group(1))
                summary_items.append(summary_item)
        
        # ===== PASS 1 (continued): Collect product/price pairs =====
        # Process lines before summary section to find products and prices
        used_skus = set()  # Track SKUs from single-line items
        
        i = 0
        while i < summary_start_line:
            line = lines[i]
            
            if not line:
                i += 1
                continue
            
            # Skip item codes (already collected in Pass 1)
            if i in item_codes:
                i += 1
                continue
            
            # Check for item code + product + price on same line (e.g., "506970 HEAVY CREAM 95.94 N")
            item_product_price_match = re.match(r'^(\d{1,10})\s+(.+?)\s+(\d+\.\d{2})\s*N?\s*$', line)
            if item_product_price_match:
                item_code = item_product_price_match.group(1)
                product_text = item_product_price_match.group(2).strip()
                price_value = float(item_product_price_match.group(3))
                
                # Create item directly (will be added to items list)
                product_name_clean, size, uom = self._parse_product_line(product_text)
                if product_name_clean:
                    item = {
                        'vendor': 'Costco',
                        'item_code': item_code,
                        'item_number': item_code,
                        'product_name': product_name_clean,
                        'description': product_text,
                        'quantity': 1.0,
                        'purchase_uom': uom,
                        'unit_price': price_value,
                        'total_price': price_value,
                        'line_text': line,
                        'is_summary': False,
                    }
                    items.append(item)
                    used_skus.add(item_code)
                
                i += 1
                continue
            
            # Check for product + price on same line (e.g., "WATERMELON 6.99 N")
            combined_match = re.search(r'^(.+?)\s+(\d+\.\d{2})\s*N?\s*$', line)
            if combined_match and len(line) > 5 and not re.match(r'^\d{1,10}\s+', line):
                product_text = combined_match.group(1).strip()
                price_value = float(combined_match.group(2))
                product_price_pairs.append((i, [product_text], i, price_value))
                i += 1
                continue
            
            # Check for price-only line (e.g., "6.49 N" or "8.99 N")
            price_match = re.search(r'(\d+\.\d{2})\s*N?\s*$', line)
            if price_match and len(line.strip()) <= 12:
                # Look backwards for product name parts (up to 5 lines)
                product_parts = []
                product_start = i
                
                for j in range(max(0, i-5), i):
                    prev_line = lines[j]
                    if not prev_line:
                        continue
                    # Skip if it's an item code, price, or summary
                    if j in item_codes or re.search(r'(\d+\.\d{2})\s*N?\s*$', prev_line):
                        continue
                    if any(keyword in prev_line.upper() for keyword in ['SUBTOTAL', 'TAX', 'TOTAL']):
                        break
                    # This looks like a product part
                    if len(prev_line.strip()) > 1:
                        product_parts.insert(0, prev_line)
                        product_start = j
                
                if product_parts:
                    price_value = float(price_match.group(1))
                    product_price_pairs.append((product_start, product_parts, i, price_value))
                
                i += 1
                continue
            
            i += 1
        
        # ===== PASS 2: Match item codes to product/price pairs by distance =====
        # Sort item codes by line position (excluding already processed ones)
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
                
                # Calculate distance (prefer closer matches)
                distance = price_line - item_code_line
                if distance < best_distance:
                    best_distance = distance
                    best_match = (idx, product_start, product_lines, price_line, price_value)
            
            # If we found a match, create item
            if best_match:
                idx, product_start, product_lines, price_line, price_value = best_match
                used_product_indices.add(idx)
                
                product_name = ' '.join(product_lines).strip()
                
                # Normalize using item map
                if self.item_map and item_code in self.item_map:
                    product_name = self.item_map[item_code]
                
                # Parse product name
                product_name_clean, size, uom = self._parse_product_line(product_name)
                
                if product_name_clean:
                    # Build line_text
                    line_text_parts = [lines[item_code_line]] + product_lines
                    if price_line != product_start + len(product_lines) - 1:
                        line_text_parts.append(lines[price_line])
                    line_text = ' | '.join(line_text_parts)
                    
                    item = {
                        'vendor': 'Costco',
                        'item_code': item_code,
                        'item_number': item_code,
                        'product_name': product_name_clean,
                        'description': product_name,
                        'quantity': 1.0,
                        'purchase_uom': uom,
                        'unit_price': price_value,
                        'total_price': price_value,
                        'line_text': line_text,
                        'is_summary': False,
                    }
                    items.append(item)
        
        # Add summary items
        items.extend(summary_items)
        
        return items
    
    def _parse_from_text_with_layout(self, text: str, layout: Dict, shared_rules: Dict) -> List[Dict]:
        """
        Parse Costco receipt text using line patterns from layout YAML
        
        Args:
            text: Raw receipt text from PDF
            layout: Layout dictionary with line_patterns, merge_multiline, summary_keywords, etc.
            shared_rules: Shared rules dictionary
            
        Returns:
            List of item dictionaries
        """
        items = []
        
        # Filter out address lines first
        try:
            from step1_extract.utils.address_filter import AddressFilter
            address_filter = AddressFilter()
            lines_list = text.split('\n')
            filtered_lines_list = address_filter.filter_address_lines(lines_list)
            text = '\n'.join(filtered_lines_list)
        except ImportError:
            pass  # Continue without filtering if module not available
        
        # Split text into lines
        lines = [line.strip() for line in text.split('\n')]
        
        # Get line patterns from layout
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
                summary_item = {
                    'vendor': 'Costco',
                    'product_name': line.strip(),
                    'line_text': line,
                    'is_summary': True,
                    'summary_type': self._extract_summary_type(line),
                }
                price_matches = list(re.finditer(r'(\d+\.\d{2})', line))
                if price_matches:
                    summary_item['total_price'] = float(price_matches[-1].group(1))
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
                        
                        product_name_clean, size, uom = self._parse_product_line(product_text)
                        if product_name_clean:
                            item = {
                                'vendor': 'Costco',
                                'item_code': item_code,
                                'item_number': item_code,
                                'product_name': product_name_clean,
                                'description': product_text,
                                'quantity': 1.0,
                                'purchase_uom': uom,
                                'unit_price': price_value,
                                'total_price': price_value,
                                'line_text': line,
                                'is_summary': False,
                            }
                            items.append(item)
                            used_skus.add(item_code)
                    
                    i += 1
                    continue
            
            # Check for product + price on same line
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
            if merge_multiline:
                price_only_info = pattern_map.get('price_only', {})
                price_only_pattern = price_only_info.get('regex') if price_only_info else None
                max_lookback = price_only_info.get('max_lookback', 5) if price_only_info else 5
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
                    product_name_clean, size, uom = self._parse_product_line(product_text)
                    
                    if product_name_clean:
                        item = {
                            'vendor': 'Costco',
                            'item_code': item_code,
                            'item_number': item_code,
                            'product_name': product_name_clean,
                            'description': product_text,
                            'quantity': 1.0,
                            'purchase_uom': uom,
                            'unit_price': price_value,
                            'total_price': price_value,
                            'line_text': f"{item_code} {product_text} {price_value}",
                            'is_summary': False,
                        }
                        items.append(item)
        
        # Add summary items
        items.extend(summary_items)
        
        return items
    
    def _parse_product_line(self, product_line: str) -> tuple:
        """
        Parse product line to extract name, size, and unit
        
        Args:
            product_line: Product name line (e.g., "LIMES 3 LB.")
            
        Returns:
            Tuple of (product_name, size, uom)
        """
        # Try to extract size/unit patterns
        size_patterns = [
            (r'(.+?)\s+(\d+(?:\.\d+)?)\s*(LB|LBS|OZ|OZS|CT|PACK|PK|QT|QTS|GAL|GALS|EA|EACH)\s*\.?$', re.IGNORECASE),
            (r'(.+?)\s+(\d+(?:\.\d+)?)(LB|LBS|OZ|OZS|CT|PACK|PK|QT|QTS|GAL|GALS|EA|EACH)\s*\.?$', re.IGNORECASE),
        ]
        
        for pattern, flags in size_patterns:
            match = re.match(pattern, product_line)
            if match:
                product_name = match.group(1).strip()
                size = match.group(2)
                uom = match.group(3).upper()
                
                # Normalize UoM
                uom_map = {
                    'LB': 'LB', 'LBS': 'LB',
                    'OZ': 'OZ', 'OZS': 'OZ',
                    'CT': 'CT',
                    'PACK': 'CT', 'PK': 'CT',
                    'QT': 'QT', 'QTS': 'QT',
                    'GAL': 'GAL', 'GALS': 'GAL',
                    'EA': 'EACH', 'EACH': 'EACH',
                }
                uom = uom_map.get(uom, uom)
                
                return product_name, size, uom
        
        # No size/unit found, return whole line as product name
        return product_line, None, 'EACH'
    
    @staticmethod
    def extract_text_from_pdf(pdf_path: Path) -> Optional[str]:
        """
        Extract text from PDF using pdfplumber (preferred) or PDFMiner (fallback)
        
        pdfplumber is preferred because it preserves layout better, which helps with
        Costco receipts where item codes and products may be on separate lines.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text or None if extraction fails
        """
        # Try pdfplumber first (better layout preservation)
        if PDFPLUMBER_AVAILABLE:
            try:
                text_lines = []
                with pdfplumber.open(str(pdf_path)) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text(layout=True)  # layout=True preserves structure
                        if page_text:
                            text_lines.append(page_text)
                if text_lines:
                    text = '\n'.join(text_lines)
                    logger.debug(f"Extracted text using pdfplumber: {len(text)} chars")
                    return text.strip() if text else None
            except Exception as e:
                logger.warning(f"pdfplumber extraction failed for {pdf_path}: {e}, falling back to PDFMiner")
        
        # Fallback to PDFMiner
        if not PDFMINER_AVAILABLE:
            logger.warning("Neither pdfplumber nor PDFMiner available. Install: pip install pdfplumber pdfminer.six")
            return None
        
        try:
            text = pdfminer_extract_text(str(pdf_path))
            logger.debug(f"Extracted text using PDFMiner: {len(text)} chars")
            return text.strip() if text else None
        except Exception as e:
            logger.error(f"PDFMiner extraction failed for {pdf_path}: {e}")
            return None
