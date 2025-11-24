#!/usr/bin/env python3
"""
UoM Extractor - Extract raw UoM/size text from receipt items
Applies UoM extraction rules from 30_uom_extraction.yaml
Does NOT normalize to Odoo UoMs - that is Step 2's job
"""

import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class UoMExtractor:
    """Extract raw UoM/size text using rules from 30_uom_extraction.yaml"""
    
    def __init__(self, rule_loader):
        """
        Initialize UoM extractor
        
        Args:
            rule_loader: RuleLoader instance
        """
        self.rule_loader = rule_loader
        self.extraction_rules = rule_loader.get_uom_extraction_rules()
    
    def extract_uom_from_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract raw UoM/size text from items
        
        Args:
            items: List of item dictionaries
            
        Returns:
            List of items with raw_uom_text and raw_size_text added
        """
        extraction_rules_config = self.extraction_rules.get('extraction_rules', {})
        priority = extraction_rules_config.get('priority', {})
        post_extraction = self.extraction_rules.get('post_extraction', {})
        
        extracted_items = []
        
        for item in items:
            new_item = item.copy()
            
            # Initialize raw fields (preserve existing values if present)
            if 'raw_uom_text' not in new_item or not new_item['raw_uom_text']:
                new_item['raw_uom_text'] = None
            if 'raw_size_text' not in new_item or not new_item['raw_size_text']:
                new_item['raw_size_text'] = None
            
            # Extract in priority order
            for priority_num in sorted(priority.keys()):
                extraction_method = priority.get(priority_num)
                
                if extraction_method == 'excel_column':
                    self._extract_from_excel_column(new_item)
                elif extraction_method == 'product_name':
                    self._extract_from_product_name(new_item, extraction_rules_config)
                elif extraction_method == 'separate_size_line':
                    # For PDFs - would need receipt text context
                    # Skip for now, can be implemented if needed
                    pass
                elif extraction_method == 'qty_unit_pattern':
                    # For PDFs - would need receipt text context
                    # Skip for now, can be implemented if needed
                    pass
            
            # Post-extraction processing
            if post_extraction.get('trim_whitespace', True):
                if new_item.get('raw_uom_text'):
                    new_item['raw_uom_text'] = new_item['raw_uom_text'].strip()
                if new_item.get('raw_size_text'):
                    new_item['raw_size_text'] = new_item['raw_size_text'].strip()
            
            # Preserve original fields if keep_source_fields is True
            if self.extraction_rules.get('preserve_original_fields', {}).get('keep_source_fields', True):
                # Keep existing purchase_uom, size fields if they exist
                if 'purchase_uom' in item and not new_item.get('raw_uom_text'):
                    new_item['raw_uom_text'] = item.get('purchase_uom')
                if 'size' in item and not new_item.get('raw_size_text'):
                    new_item['raw_size_text'] = item.get('size')
            
            extracted_items.append(new_item)
        
        return extracted_items
    
    def _extract_from_excel_column(self, item: Dict[str, Any]) -> None:
        """Extract UoM from Excel column fields if available"""
        extraction_rules_config = self.extraction_rules.get('extraction_rules', {})
        excel_column_config = extraction_rules_config.get('excel_column', {})
        map_columns = excel_column_config.get('map_columns', {})
        
        # Check if item has fields that map to raw_uom_text or raw_size_text
        # These would be set during Excel parsing if columns like "Size" or "UOM" exist
        # Since we're working with already-parsed items, check for common field names
        if 'size' in item and not item.get('raw_size_text'):
            item['raw_size_text'] = str(item['size'])
        if 'uom' in item and not item.get('raw_uom_text'):
            item['raw_uom_text'] = str(item['uom'])
        if 'purchase_uom' in item and not item.get('raw_uom_text'):
            item['raw_uom_text'] = str(item['purchase_uom'])
    
    def _extract_from_product_name(self, item: Dict[str, Any], extraction_rules_config: Dict[str, Any]) -> None:
        """Extract size/UoM from product name using multiple patterns"""
        product_name = item.get('product_name', '')
        if not product_name:
            return
        
        # First, try to extract UoM directly from product name (prioritize count/sheet/pcs/pounds)
        # This handles cases where UoM is embedded in the product name
        self._extract_uom_from_product_name(item, product_name)
        
        # If we already extracted purchase_uom, skip the pattern-based extraction
        if item.get('purchase_uom'):
            return
        
        # Otherwise, use pattern-based extraction from YAML rules
        product_name_config = extraction_rules_config.get('product_name', {})
        
        # Support both extract_pattern (single) and extract_patterns (list)
        patterns = product_name_config.get('extract_patterns')
        if not patterns:
            # Fallback to single pattern for backward compatibility
            single_pattern = product_name_config.get('extract_pattern', r'(\d+\s*(?:LB|OZ|GAL|QT|PC|PKG|PK|CT|EA|EACH|UNIT|UNITS|KG|G))')
            patterns = [single_pattern]
        
        field_mapping = product_name_config.get('field_mapping', 'raw_size_text')
        
        # Try each pattern in order until one matches
        for extract_pattern in patterns:
            match = re.search(extract_pattern, product_name, re.IGNORECASE)
            if match:
                # Extract the captured group (the number/size/count)
                extracted_text = match.group(1).strip()
                
                # Convert to proper UoM format if this is a count/sheet/pcs pattern
                normalized_uom = self._normalize_extracted_uom(extracted_text, product_name)
                
                # Store in the appropriate field
                if field_mapping == 'raw_size_text' and not item.get('raw_size_text'):
                    item['raw_size_text'] = extracted_text
                    logger.debug(f"Extracted raw_size_text from '{product_name}': {extracted_text}")
                    # Also set purchase_uom if we normalized it
                    if normalized_uom and not item.get('purchase_uom'):
                        item['purchase_uom'] = normalized_uom
                        logger.debug(f"Set purchase_uom from product name: {normalized_uom}")
                    break
                elif field_mapping == 'raw_uom_text' and not item.get('raw_uom_text'):
                    item['raw_uom_text'] = extracted_text
                    logger.debug(f"Extracted raw_uom_text from '{product_name}': {extracted_text}")
                    # Also set purchase_uom if we normalized it
                    if normalized_uom and not item.get('purchase_uom'):
                        item['purchase_uom'] = normalized_uom
                        logger.debug(f"Set purchase_uom from product name: {normalized_uom}")
                    break
    
    def _normalize_extracted_uom(self, extracted_text: str, product_name: str) -> Optional[str]:
        """
        Normalize extracted UoM text to standard format.
        Examples:
        - "12 Count" → "12-pc" or "dozen" (if 12)
        - "500 Sheets" → "500-pc"
        - "2.5 Pounds" → "2.5-lb"
        """
        if not extracted_text:
            return None
        
        # Check if product name contains count/sheet/pcs patterns
        product_lower = product_name.lower()
        
        # Pattern: "X Count" or "X count" → "X-pc" or "dozen" if X=12
        count_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:count|ct)\b', product_lower)
        if count_match:
            count_num = float(count_match.group(1))
            if count_num == 12:
                return 'dozen'
            else:
                return f"{int(count_num) if count_num.is_integer() else count_num}-pc"
        
        # Pattern: "X Sheets" or "X sheets" → "X-pc"
        sheets_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:sheets?|sheet)\b', product_lower)
        if sheets_match:
            sheets_num = float(sheets_match.group(1))
            return f"{int(sheets_num) if sheets_num.is_integer() else sheets_num}-pc"
        
        # Pattern: "X Pcs" or "X pcs" → "X-pc"
        pcs_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:pcs?|pieces?|piece)\b', product_lower)
        if pcs_match:
            pcs_num = float(pcs_match.group(1))
            return f"{int(pcs_num) if pcs_num.is_integer() else pcs_num}-pc"
        
        # Pattern: "X Pounds" or "X lbs" → "X-lb"
        pounds_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:pounds?|lbs?|lb)\b', product_lower)
        if pounds_match:
            pounds_num = float(pounds_match.group(1))
            return f"{int(pounds_num) if pounds_num.is_integer() else pounds_num}-lb"
        
        # Pattern: "1 Ream" → check if it mentions sheets (e.g., "1 Ream, (500 Sheets)")
        ream_match = re.search(r'(\d+)\s*(?:ream|reams?)\b', product_lower)
        if ream_match:
            # Check if sheets are mentioned
            sheets_in_ream = re.search(r'\((\d+)\s*(?:sheets?|sheet)\)', product_lower)
            if sheets_in_ream:
                sheets_num = int(sheets_in_ream.group(1))
                return f"{sheets_num}-pc"
            # Default: 1 ream = 500 sheets
            return "500-pc"
        
        return None
    
    def _extract_uom_from_product_name(self, item: Dict[str, Any], product_name: str) -> None:
        """
        Extract UoM directly from product name patterns and set purchase_uom.
        This handles cases where UoM is embedded in the product name.
        """
        if not product_name or item.get('purchase_uom'):
            return
        
        product_lower = product_name.lower()
        
        # Default to "unit" for products that don't have explicit UoM in name
        # This handles cases like "Blow Torch" where UoM should be "unit"
        # Only set default if no other UoM patterns match
        default_to_unit = True
        
        # Pattern: "X Count" or "X count" → "X-pc" or "dozen" if X=12
        count_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:count|ct)\b', product_lower)
        if count_match:
            count_num = float(count_match.group(1))
            if count_num == 12:
                item['purchase_uom'] = 'dozen'
            else:
                item['purchase_uom'] = f"{int(count_num) if count_num.is_integer() else count_num}-pc"
            logger.debug(f"Extracted UoM from product name '{product_name}': {item['purchase_uom']}")
            return
        
        # Pattern: "X Sheets" or "X sheets" → "X-pc"
        sheets_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:sheets?|sheet)\b', product_lower)
        if sheets_match:
            sheets_num = float(sheets_match.group(1))
            item['purchase_uom'] = f"{int(sheets_num) if sheets_num.is_integer() else sheets_num}-pc"
            logger.debug(f"Extracted UoM from product name '{product_name}': {item['purchase_uom']}")
            return
        
        # Pattern: "X Pcs" or "X pcs" → "X-pc"
        pcs_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:pcs?|pieces?|piece)\b', product_lower)
        if pcs_match:
            pcs_num = float(pcs_match.group(1))
            item['purchase_uom'] = f"{int(pcs_num) if pcs_num.is_integer() else pcs_num}-pc"
            logger.debug(f"Extracted UoM from product name '{product_name}': {item['purchase_uom']}")
            return
        
        # Pattern: "X Pounds" or "X lbs" → "X-lb"
        pounds_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:pounds?|lbs?|lb)\b', product_lower)
        if pounds_match:
            pounds_num = float(pounds_match.group(1))
            item['purchase_uom'] = f"{int(pounds_num) if pounds_num.is_integer() else pounds_num}-lb"
            logger.debug(f"Extracted UoM from product name '{product_name}': {item['purchase_uom']}")
            return
        
        # Pattern: "1 Ream" → check if it mentions sheets (e.g., "1 Ream, (500 Sheets)")
        ream_match = re.search(r'(\d+)\s*(?:ream|reams?)\b', product_lower)
        if ream_match:
            # Check if sheets are mentioned
            sheets_in_ream = re.search(r'\((\d+)\s*(?:sheets?|sheet)\)', product_lower)
            if sheets_in_ream:
                sheets_num = int(sheets_in_ream.group(1))
                item['purchase_uom'] = f"{sheets_num}-pc"
            else:
                # Default: 1 ream = 500 sheets
                item['purchase_uom'] = "500-pc"
            logger.debug(f"Extracted UoM from product name '{product_name}': {item['purchase_uom']}")
            return
        
        # Default: If no UoM pattern matched, set to "unit"
        # This handles products like "Blow Torch" that don't have explicit UoM in the name
        item['purchase_uom'] = 'unit'
        logger.debug(f"Defaulted UoM to 'unit' for product name '{product_name}' (no explicit UoM found)")

