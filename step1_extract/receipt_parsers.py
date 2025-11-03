#!/usr/bin/env python3
"""
Receipt Parsers - Implement parsing logic according to step1_rules
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class VendorIdentifier:
    """Identify vendor using rules from vendor_identification.md"""
    
    def __init__(self, rules: Dict):
        """Initialize with vendor identification rules"""
        self.rules = rules
        self.vendors = rules.get('vendors', {})
        self.fallback_from_filename = rules.get('fallback_from_filename', True)
        self.filename_confidence = rules.get('filename_confidence', 0.6)
    
    def identify_vendor(self, text: str, filename: str) -> Tuple[Optional[str], float, str]:
        """
        Identify vendor from receipt text with filename fallback
        
        Returns:
            Tuple of (vendor_name, confidence_score, source)
            source is "text" or "filename"
        """
        # First try text-based identification
        text_vendor, text_confidence = self._identify_from_text(text)
        if text_vendor and text_confidence >= 0.6:
            return text_vendor, text_confidence, "text"
        
        # Fallback to filename if enabled
        if self.fallback_from_filename:
            filename_vendor = self._identify_from_filename(filename)
            if filename_vendor:
                logger.warning(f"Vendor inferred from filename: {filename_vendor}")
                return filename_vendor, self.filename_confidence, "filename"
        
        # No vendor found
        return None, 0.0, "unknown"
    
    def _identify_from_text(self, text: str) -> Tuple[Optional[str], float]:
        """Identify vendor from receipt text"""
        text_lower = text.lower()
        best_match = None
        best_score = 0.0
        
        # Check each vendor's keywords
        for vendor_key, vendor_data in self.vendors.items():
            keywords = vendor_data.get('keywords', [])
            if not keywords:
                continue
            
            # Count keyword matches
            matches = sum(1 for keyword in keywords if keyword.lower() in text_lower)
            if matches > 0:
                # Calculate score based on keyword matches
                score = matches / len(keywords) if len(keywords) > 0 else 0.0
                
                # Boost score if vendor name appears explicitly
                vendor_name_lower = vendor_key.replace('_', ' ').lower()
                if vendor_name_lower in text_lower:
                    score = min(1.0, score + 0.3)
                
                if score > best_score:
                    best_score = score
                    best_match = vendor_key
        
        # Normalize vendor name
        if best_match:
            vendor_name = best_match.replace('_', ' ').title()
            logger.info(f"Vendor detected from text: {vendor_name} (confidence: {best_score:.2f})")
            return vendor_name, best_score
        
        return None, 0.0
    
    def _identify_from_filename(self, filename: str) -> Optional[str]:
        """Identify vendor from filename"""
        # Normalize filename by replacing non-letters with spaces
        base = Path(filename).stem if hasattr(Path, 'stem') else filename.rsplit('.', 1)[0]
        normalized = re.sub(r'[^a-z0-9]', ' ', base.lower())
        
        # Fuzzy match against vendor keys
        best_match = None
        best_score = 0.0
        
        for vendor_key in self.vendors.keys():
            vendor_normalized = re.sub(r'[^a-z0-9]', ' ', vendor_key.lower())
            score = SequenceMatcher(None, normalized, vendor_normalized).ratio()
            
            if score > best_score:
                best_score = score
                best_match = vendor_key
        
        if best_match and best_score >= 0.6:
            vendor_name = best_match.replace('_', ' ').title()
            return vendor_name
        
        return None


class ItemLineParser:
    """Parse item lines using rules from item_line_parsing.md"""
    
    def __init__(self, rules: Dict):
        """Initialize with item parsing rules"""
        self.rules = rules
        self.ignore_keywords = rules.get('ignore_keywords', [])
        self.require_price_at_end = rules.get('require_price_at_end', True)
        self.regex_price_end = rules.get('regex_price_end', r'^(?P<desc>[A-Za-z0-9 ,.\'%-]+?)\s+(?P<price>\d+\.\d{2})$')
        self.quantity_price_combo_regex = rules.get('quantity_price_combo_regex', r'(?P<qty>\d+(?:\.\d+)?)\s*(?:x|@)\s*\$?(?P<unit_price>\d+\.\d{2})')
        self.merge_wrapped_lines = rules.get('merge_wrapped_lines', True)
    
    def is_valid_item_line(self, line: str) -> bool:
        """Check if line is a valid item line (not a summary line)"""
        line_lower = line.lower()
        
        # Check for ignore keywords
        for keyword in self.ignore_keywords:
            if keyword.lower() in line_lower:
                return False
        
        # Check if price exists (relaxed: don't require price at end)
        if self.require_price_at_end:
            # Price should be at the end of the line
            price_match = re.search(r'\$?(\d+\.\d{2})\s*$', line)
            if not price_match:
                return False
        else:
            # Relaxed mode: just check if price exists anywhere
            price_match = re.search(r'\$?(\d+\.\d{2})', line)
            if not price_match:
                return False
        
        # Must have alphabetic characters (product name)
        if not re.search(r'[A-Za-z]', line):
            return False
        
        return True
    
    def parse_item_line(self, line: str) -> Optional[Dict]:
        """
        Parse a single item line according to rules
        
        Returns:
            Dictionary with item data or None if not an item
        """
        if not self.is_valid_item_line(line):
            return None
        
        # Use regex to extract description and price
        if self.require_price_at_end:
            match = re.match(self.regex_price_end, line.strip())
            if not match:
                # Fallback: try to find price at end (prefer rightmost if multiple)
                price_matches = list(re.finditer(r'\$?(\d+\.\d{2})\s*$', line))
                if price_matches:
                    # Use rightmost price
                    price_match = price_matches[-1]
                    desc = line[:price_match.start()].strip()
                    price = float(price_match.group(1))
                else:
                    return None
            else:
                desc = match.group('desc').strip()
                price = float(match.group('price'))
        else:
            # Fallback: find price anywhere (prefer rightmost if multiple)
            price_matches = list(re.finditer(r'\$?(\d+\.\d{2})', line))
            if not price_matches:
                return None
            
            # Prefer rightmost price when multiple prices found (thermal receipts)
            price_match = price_matches[-1]  # Last match is rightmost
            desc = line[:price_match.start()].strip()
            price = float(price_match.group(1))
        
        if not desc:
            return None
        
        # Try to extract quantity and unit price from combo pattern
        qty_combo_match = re.search(self.quantity_price_combo_regex, desc, re.IGNORECASE)
        if qty_combo_match:
            quantity = float(qty_combo_match.group('qty'))
            unit_price = float(qty_combo_match.group('unit_price'))
            # Remove quantity/price combo from description
            product_name = desc.replace(qty_combo_match.group(0), '').strip()
        else:
            # Try to extract quantity with UoM
            qty_uom_match = re.search(r'(\d+(?:\.\d+)?)\s*(lb|each|unit|oz|kg|gal|qt|pt|bag|box|pkg|roll|ct)', desc, re.IGNORECASE)
            if qty_uom_match:
                quantity = float(qty_uom_match.group(1))
                uom = qty_uom_match.group(2).lower()
                product_name = desc.replace(qty_uom_match.group(0), '').strip()
                unit_price = price / quantity if quantity > 0 else price
            else:
                # Try quantity at start of line
                qty_match = re.search(r'^(\d+(?:\.\d+)?)\s*(?:x|@)?\s*', desc)
                if qty_match:
                    quantity = float(qty_match.group(1))
                    product_name = desc[qty_match.end():].strip()
                    unit_price = price / quantity if quantity > 0 else price
                else:
                    quantity = 1.0
                    product_name = desc
                    unit_price = price
        
        return {
            'product_name': product_name,
            'quantity': quantity,
            'purchase_uom': None,  # Will be detected by unit detector
            'unit_price': unit_price,
            'total_price': price,
            'line_text': line,
        }
    
    def merge_multiline_items(self, lines: List[str], multiline_config: Optional[Dict] = None) -> List[str]:
        """
        Merge adjacent lines that represent a single item
        (when text extraction breaks item name into multiple lines)
        
        Args:
            lines: List of receipt lines
            multiline_config: Optional multiline configuration dict with:
                - enabled: bool - Whether to enable multiline merging
                - joiner: str - String to join lines with (default: " ")
                - max_lines: int - Maximum number of lines to merge (default: 2)
        
        Returns:
            List of merged lines
        """
        # Use config if provided, otherwise fall back to rules-based config
        if multiline_config:
            enabled = multiline_config.get('enabled', True)
            joiner = multiline_config.get('joiner', ' ')
            max_lines = multiline_config.get('max_lines', 2)
        else:
            # Fall back to legacy merge_wrapped_lines setting
            enabled = self.merge_wrapped_lines
            joiner = ' '
            max_lines = 2  # Legacy default
        
        if not enabled:
            return lines
        
        # Pre-normalize: collapse multiple spaces
        normalized_lines = []
        for line in lines:
            normalized = re.sub(r'\s+', ' ', line.strip())
            if normalized:
                normalized_lines.append(normalized)
        
        merged_lines = []
        current_line = ""
        current_line_count = 0
        
        for i, line in enumerate(normalized_lines):
            # Check if this line is a keyword (TAX/TOTAL) - don't merge before these
            is_keyword = any(keyword.lower() in line.lower() for keyword in self.ignore_keywords)
            
            # Check if line has a price at end (end of item)
            price_match = re.search(r'\$?\d+\.\d{2}\s*$', line)
            
            if price_match:
                # This line ends with price - append to current and finalize
                if current_line and current_line_count < max_lines:
                    merged_lines.append(current_line + joiner + line)
                else:
                    merged_lines.append(line)
                current_line = ""
                current_line_count = 0
            elif is_keyword and i > 0:
                # Don't merge before keywords - finalize current line
                if current_line:
                    merged_lines.append(current_line)
                    current_line = ""
                    current_line_count = 0
                merged_lines.append(line)
            else:
                # Continue accumulating (up to max_lines)
                if current_line_count >= max_lines:
                    # Max lines reached - finalize current line and start new one
                    merged_lines.append(current_line)
                    current_line = line
                    current_line_count = 1
                elif current_line:
                    current_line += joiner + line
                    current_line_count += 1
                else:
                    current_line = line
                    current_line_count = 1
        
        # Add remaining line if any
        if current_line:
            merged_lines.append(current_line)
        
        return merged_lines


class UnitDetector:
    """Detect units using rules from unit_detection.md"""
    
    def __init__(self, rules: Dict):
        """Initialize with unit detection rules"""
        self.rules = rules
        self.regex_map = rules.get('regex_map', {})
        self.keyword_inference = rules.get('keyword_inference', {})
        self.confidence_boost = rules.get('confidence_boost', {})
        self.price_sanity = rules.get('price_sanity', {})
        self.unknown_uom = rules.get('unknown_uom', {})
    
    def detect_unit_from_regex(self, text: str) -> Optional[Tuple[str, float]]:
        """
        Detect unit from regex patterns in text
        
        Returns:
            Tuple of (unit, confidence) or None
        """
        text_lower = text.lower()
        best_match = None
        best_score = 0.0
        
        for pattern, unit in self.regex_map.items():
            # Create regex pattern - handle optional groups and special chars
            # Patterns like "gal(lon)?s?" need to be converted to proper regex
            pattern_escaped = re.escape(pattern)
            # Restore regex special chars that should work
            pattern_escaped = pattern_escaped.replace(r'\(', '(').replace(r'\)', ')').replace(r'\?', '?')
            # Try with word boundaries
            regex_pattern = r'\b' + pattern_escaped + r'\b'
            
            try:
                matches = re.findall(regex_pattern, text_lower, re.IGNORECASE)
                if not matches:
                    # Try without word boundaries if no match
                    regex_pattern_loose = pattern_escaped
                    matches = re.findall(regex_pattern_loose, text_lower, re.IGNORECASE)
            except Exception as e:
                logger.debug(f"Regex error for pattern {pattern}: {e}")
                # Fallback: simple string search for the base pattern
                pattern_base = pattern.replace('(', '').replace(')', '').replace('?', '').replace('s', '')
                if pattern_base.lower() in text_lower:
                    matches = [pattern]
                else:
                    matches = []
            
            # Special handling for "pt" -> also match "pint" (full word)
            if unit == 'pt' and not matches:
                if 'pint' in text_lower:
                    matches = ['pint']
            
            # Special handling for "lb" -> also match "pound" (full word)
            if unit == 'lb' and not matches:
                if 'pound' in text_lower and 'pounds' not in text_lower:
                    matches = ['pound']
            
            if matches:
                # Explicit regex match has high confidence
                score = 1.0
                if score > best_score:
                    best_score = score
                    best_match = unit
        
        if best_match:
            return best_match, best_score
        
        return None
    
    def detect_unit_from_keywords(self, product_name: str, price: Optional[float] = None) -> Optional[Tuple[str, float]]:
        """
        Infer unit from product name keywords with confidence scoring
        
        Returns:
            Tuple of (unit, confidence) or None
        """
        product_lower = product_name.lower()
        best_match = None
        best_score = 0.0
        
        for keyword, unit in self.keyword_inference.items():
            keyword_lower = keyword.lower()
            # Check if keyword appears in product name (as word boundary)
            if keyword_lower in product_lower:
                # Check word boundaries for better matching
                keyword_pattern = r'\b' + re.escape(keyword_lower) + r'\b'
                if re.search(keyword_pattern, product_lower):
                    # Base confidence - more specific matches get higher scores
                    if keyword_lower == product_lower.strip():
                        score = 1.0  # Exact match
                    elif product_lower.startswith(keyword_lower) or product_lower.endswith(keyword_lower):
                        score = 0.85  # At start or end
                    else:
                        score = 0.7  # Partial match
                    
                    # Apply confidence boost if available
                    boost = self.confidence_boost.get(keyword, 0.0)
                    score = min(1.0, score + boost)
                    
                    # Price sanity check: if unit is "each" and price is high, re-evaluate
                    if unit == "each" and price and self.price_sanity.get('high_price_each_threshold'):
                        threshold = self.price_sanity['high_price_each_threshold']
                        if price > threshold:
                            # High price for "each" - might be weight-based
                            score = score * 0.5  # Reduce confidence
                    
                    if score > best_score:
                        best_score = score
                        best_match = unit
        
        if best_match:
            return best_match, best_score
        
        return None
    
    def detect_unit(self, product_name: str, line_text: str, price: Optional[float] = None) -> Tuple[Optional[str], float]:
        """
        Detect unit for a product with confidence scoring
        
        Returns:
            Tuple of (unit_name, confidence) or (None, 0.0) if unknown
        """
        # Try regex first (more explicit, higher confidence)
        regex_result = self.detect_unit_from_regex(line_text)
        if regex_result:
            unit, confidence = regex_result
            logger.debug(f"Detected unit from regex: {unit} (confidence: {confidence:.2f}) for {product_name}")
            return unit, confidence
        
        # Fall back to keyword inference
        keyword_result = self.detect_unit_from_keywords(product_name, price)
        if keyword_result:
            unit, confidence = keyword_result
            # Check confidence threshold (minimum 0.5)
            if confidence >= 0.5:
                logger.debug(f"Detected unit from keywords: {unit} (confidence: {confidence:.2f}) for {product_name}")
                return unit, confidence
        
        # Return unknown with low confidence
        unknown_label = self.unknown_uom.get('label', 'unknown')
        unknown_confidence = self.unknown_uom.get('confidence', 0.0)
        logger.debug(f"Could not detect unit for {product_name}, marking as {unknown_label} (confidence: {unknown_confidence:.2f})")
        return unknown_label, unknown_confidence


class TotalValidator:
    """Validate totals using rules from validation.md"""
    
    def __init__(self, rules: Dict):
        """Initialize with validation rules"""
        self.rules = rules
        validation_config = rules.get('validation', {})
        self.tolerance = validation_config.get('tolerance', 0.05)
        self.components = validation_config.get('components', ['subtotal', 'tax', 'fees', 'total'])
        self.log_on_mismatch = validation_config.get('log_on_mismatch', True)
        self.flag_on_mismatch = validation_config.get('flag_on_mismatch', True)
    
    def validate_totals(self, receipt: Dict) -> Tuple[bool, Optional[str]]:
        """
        Validate receipt totals with tolerance check
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Get totals from receipt
        subtotal = receipt.get('subtotal', 0.0)
        tax = receipt.get('tax', 0.0)
        
        # Calculate fees from items marked as fees
        fees = sum(item.get('total_price', 0.0) for item in receipt.get('items', []) if item.get('is_fee', False))
        total = receipt.get('total', 0.0)
        
        # Calculate computed total
        computed_total = subtotal + tax + fees
        
        # Check tolerance
        difference = abs(computed_total - total)
        
        if difference > self.tolerance:
            error_msg = (
                f"Total mismatch: computed ${computed_total:.2f} "
                f"(subtotal ${subtotal:.2f} + tax ${tax:.2f} + fees ${fees:.2f}) "
                f"vs detected ${total:.2f} (difference: ${difference:.2f})"
            )
            
            if self.log_on_mismatch:
                logger.warning(error_msg)
            
            return False, error_msg
        
        logger.debug(f"Total validated: ${computed_total:.2f} matches detected ${total:.2f}")
        return True, None
    
    def extract_totals(self, text: str) -> Dict[str, float]:
        """
        Extract subtotal, tax, fees, and total from receipt text
        For thermal receipts: prefer rightmost price when multiple prices found
        
        Returns:
            Dictionary with extracted totals
        """
        totals = {
            'subtotal': 0.0,
            'tax': 0.0,
            'fees': 0.0,
            'total': 0.0,
        }
        
        lines = text.split('\n')
        
        for line in lines:
            line_lower = line.lower()
            
            # Find all prices in line (for rightmost preference)
            price_matches = list(re.finditer(r'\$?(\d+\.\d{2})', line))
            
            if not price_matches:
                continue
            
            # Prefer rightmost price when multiple prices found
            rightmost_match = price_matches[-1]  # Last match is rightmost
            price_value = float(rightmost_match.group(1))
            
            # Extract subtotal (keep even if parsing fails)
            if 'subtotal' in line_lower and 'total' not in line_lower.replace('subtotal', ''):
                totals['subtotal'] = price_value
            
            # Extract tax (keep even if parsing fails)
            elif 'tax' in line_lower and 'total' not in line_lower:
                totals['tax'] = price_value
            
            # Extract total (keep even if parsing fails)
            elif 'total' in line_lower and 'subtotal' not in line_lower:
                totals['total'] = price_value
        
        return totals
