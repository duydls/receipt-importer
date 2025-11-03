#!/usr/bin/env python3
"""
UoM Extractor - Extract raw UoM/size text from receipt items
Applies UoM extraction rules from 30_uom_extraction.yaml
Does NOT normalize to Odoo UoMs - that is Step 2's job
"""

import re
import logging
from typing import Dict, Any, List

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
            
            # Initialize raw fields
            new_item['raw_uom_text'] = None
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
        """Extract size/UoM from product name"""
        product_name_config = extraction_rules_config.get('product_name', {})
        extract_pattern = product_name_config.get('extract_pattern', r'(\d+\s*(?:LB|OZ|GAL|QT|PC|PKG|PK|CT|EA|EACH|UNIT|UNITS|KG|G))')
        field_mapping = product_name_config.get('field_mapping', 'raw_size_text')
        
        product_name = item.get('product_name', '')
        if not product_name:
            return
        
        # Try to extract size/UoM pattern from product name
        match = re.search(extract_pattern, product_name, re.IGNORECASE)
        if match:
            extracted_text = match.group(1).strip()
            if field_mapping == 'raw_size_text' and not item.get('raw_size_text'):
                item['raw_size_text'] = extracted_text
                logger.debug(f"Extracted raw_size_text from product name '{product_name}': {extracted_text}")
            elif field_mapping == 'raw_uom_text' and not item.get('raw_uom_text'):
                item['raw_uom_text'] = extracted_text
                logger.debug(f"Extracted raw_uom_text from product name '{product_name}': {extracted_text}")

