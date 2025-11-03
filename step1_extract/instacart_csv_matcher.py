#!/usr/bin/env python3
"""
Instacart CSV Matcher - Link CSV baseline to fix UoM/size/quantity/brand
For files prefixed with receipt_instacart* or matching Uni_Uni_Uptown pattern
"""

import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class InstacartCSVMatcher:
    """Match receipt items to Instacart CSV data"""
    
    def __init__(self, rules: Optional[Dict] = None, receipt_folder: Optional[Path] = None, rule_loader=None):
        """
        Initialize with Instacart CSV matching rules
        
        Args:
            rules: Optional rules dict (legacy, for backward compatibility)
            receipt_folder: Optional folder containing CSV files
            rule_loader: Optional RuleLoader instance to load rules from YAML
        """
        # Store rule_loader for rule lookup
        self.rule_loader = rule_loader
        self.receipt_folder = receipt_folder
        
        # Load Instacart CSV rules from YAML (25_instacart_csv.yaml)
        instacart_csv_rules = {}
        if rule_loader:
            instacart_csv_rules = rule_loader.get_instacart_csv_rules()
        
        # Load CSV matching config from shared.yaml (instacart_csv_match section)
        if rule_loader:
            csv_match_config = rule_loader.get_instacart_csv_match_rules()
            # Merge rules dict over rule_loader rules (rules dict takes precedence)
            if rules:
                csv_match_config = {**csv_match_config, **rules.get('instacart_csv_match', {})}
            self.rules = {'instacart_csv_match': csv_match_config}
        elif rules:
            csv_match_config = rules.get('instacart_csv_match', {})
            self.rules = {'instacart_csv_match': csv_match_config}
        else:
            csv_match_config = {}
            self.rules = {}
        
        # Load CSV file names from 25_instacart_csv.yaml (or fall back to shared.yaml or hardcoded)
        self.csv_file_names = instacart_csv_rules.get('files', [])
        if not self.csv_file_names:
            # Fall back to shared.yaml config
            csv_sources = csv_match_config.get('csv_sources', [])
            if csv_sources:
                self.csv_file_names = csv_sources
            else:
                # Final fallback to hardcoded defaults
                self.csv_file_names = [
                    'order_item_summary_report.csv',
                    'order_summary_report 3.csv'
                ]
        
        # Load column name mappings from 25_instacart_csv.yaml
        id_fields_config = instacart_csv_rules.get('id_fields', {})
        self.id_field_mappings = {
            'order_id': id_fields_config.get('order_id', ['Order ID', 'order_id']),
            'item_name': id_fields_config.get('item_name', ['Item Name', 'Item']),
            'size': id_fields_config.get('size', ['Size', 'Variant']),
            'qty': id_fields_config.get('qty', ['Quantity', 'Qty', 'Picked Quantity']),
            'uom': id_fields_config.get('uom', ['Cost Unit', 'Unit', 'UoM']),
            'brand_name': id_fields_config.get('brand_name', ['Brand Name', 'Brand']),
        }
        
        # Load match threshold from 25_instacart_csv.yaml (or fall back to shared.yaml)
        self.match_threshold = instacart_csv_rules.get('match_threshold', csv_match_config.get('match', {}).get('threshold', 0.85))
        
        # Load other config from shared.yaml (instacart_csv_match section)
        self.enabled = csv_match_config.get('enabled', True)
        self.detect_by_prefix = csv_match_config.get('detect_by_prefix', 'receipt_instacart')
        self.alt_pattern = csv_match_config.get('alt_pattern', r'Uni_Uni_Uptown_\d{4}-\d{2}-\d{2}_\d+\.pdf')
        self.order_id_regex = csv_match_config.get('order_id_regex', r'_(\d{17,})\.pdf$')
        self.override_fields = csv_match_config.get('override_fields', ['size', 'uom', 'quantity', 'brand_name'])
        output_flags = csv_match_config.get('output_flags', {})
        self.csv_linked_field = output_flags.get('csv_linked_field', 'csv_linked')
        self.csv_linked_value = output_flags.get('csv_linked_value', True)
        log_messages = csv_match_config.get('log_messages', {})
        self.log_linked = log_messages.get('linked', '[INFO] CSV baseline matched for {desc} in order {order_id}')
        self.log_missing = log_messages.get('missing', '[WARN] No CSV entry for {desc} in {order_id}')
        
        # Load vendor list from rules (for should_match check)
        self.vendors_for_csv_match = csv_match_config.get('vendors', ['Instacart'])
        
        self.csv_data_cache = None
        self.csv_available = False  # Track if CSV files are available
        # Cache for SequenceMatcher objects to improve performance
        self._matcher_cache = {}
        self._load_csv_data()
    
    def should_match(self, filename: str, vendor: Optional[str] = None) -> bool:
        """
        Check if file should be matched against CSV
        
        Args:
            filename: PDF filename
            vendor: Vendor name (checked against vendors list from rules)
        
        Returns:
            True if CSV matching should be attempted
        """
        if not self.enabled:
            return False
        
        # Check if vendor matches any vendor in the vendors list (from rules)
        if vendor:
            vendor_lower = vendor.lower()
            for allowed_vendor in self.vendors_for_csv_match:
                # Handle wildcard pattern (e.g., "IC-*")
                if allowed_vendor.endswith('*'):
                    prefix = allowed_vendor[:-1].lower()
                    if vendor_lower.startswith(prefix):
                        return True
                elif vendor_lower == allowed_vendor.lower():
                    return True
        
        # Check prefix
        if filename.startswith(self.detect_by_prefix):
            return True
        
        # Check alternate pattern
        if re.match(self.alt_pattern, filename):
            return True
        
        return False
    
    @staticmethod
    def _normalize_string(text: str) -> str:
        """
        Normalize string for fuzzy matching
        Strips special characters (®, ™, commas) and converts to lowercase
        
        Args:
            text: Input string
        
        Returns:
            Normalized string
        """
        if not text:
            return ''
        
        # Remove trademark symbols, copyright, registered marks
        normalized = re.sub(r'[®™©]', '', text)
        
        # Remove commas
        normalized = normalized.replace(',', '')
        
        # Convert to lowercase and strip whitespace
        normalized = normalized.lower().strip()
        
        return normalized
    
    def extract_order_id(self, filename: str) -> Optional[str]:
        """Extract order ID from filename"""
        match = re.search(self.order_id_regex, filename)
        if match:
            return match.group(1)
        return None
    
    def _load_csv_data(self):
        """Load CSV data into memory cache"""
        if not self.receipt_folder:
            self.csv_available = False
            self.csv_data_cache = []
            return
        
        # Find CSV files using configurable file names from rules
        csv_files = []
        for csv_file_name in self.csv_file_names:
            csv_path = self.receipt_folder / csv_file_name
            if csv_path.exists():
                csv_files.append(csv_path)
        
        if not csv_files:
            logger.warning(f"Instacart CSV files not found in: {self.receipt_folder}. Looking for: {self.csv_file_names}")
            self.csv_available = False
            self.csv_data_cache = []
            return
        
        # Load CSV data
        self.csv_data_cache = []
        total_rows = 0
        for csv_file in csv_files:
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    file_rows = list(reader)
                    self.csv_data_cache.extend(file_rows)
                    total_rows += len(file_rows)
                logger.info(f"Loaded {len(file_rows)} rows from {csv_file.name}")
            except Exception as e:
                logger.error(f"Error loading CSV file {csv_file}: {e}")
        
        self.csv_available = len(self.csv_data_cache) > 0
        if self.csv_available:
            logger.info(f"Loaded {total_rows} total rows from {len(csv_files)} CSV file(s)")
    
    def match_items(self, receipt_items: List[Dict], order_id: Optional[str] = None, vendor: Optional[str] = None) -> List[Dict]:
        """
        Match receipt items to CSV data
        
        Args:
            receipt_items: List of receipt items
            order_id: Order ID to filter CSV data
            vendor: Vendor name (if vendor == 'Instacart', always attempt CSV matching)
            
        Returns:
            Updated receipt items with CSV data (or items with csv_linked=false if CSV missing)
        """
        # Check if CSV files are available
        if not self.csv_available:
            # CSV files not found - mark all items as not linked
            logger.warning(f"Instacart CSV files not available. Marking items as csv_linked=false")
            result_items = []
            for item in receipt_items:
                updated_item = item.copy()
                updated_item['csv_linked'] = False
                updated_item['csv_reason'] = "no baseline csv found near pdf"
                result_items.append(updated_item)
            return result_items
        
        # Check if we should match (vendor check)
        if vendor and vendor.lower() == 'instacart':
            # Always attempt CSV matching for Instacart
            pass
        elif not self.csv_data_cache:
            return receipt_items
        
        # Final check: if no CSV cache, return items unchanged
        if not self.csv_data_cache:
            return receipt_items
        
        # Filter CSV data by order_id if provided (using configurable column names)
        if order_id:
            order_id_columns = self.id_field_mappings['order_id']
            csv_rows = []
            for row in self.csv_data_cache:
                # Try each possible order_id column name
                for col_name in order_id_columns:
                    if row.get(col_name) == order_id:
                        csv_rows.append(row)
                        break
        else:
            csv_rows = self.csv_data_cache
        
        if not csv_rows:
            logger.warning(f"No CSV rows found for order_id: {order_id}")
            return receipt_items
        
        # Match each receipt item to CSV row
        matched_items = []
        for item in receipt_items:
            matched_item = self._match_item(item, csv_rows, order_id)
            matched_items.append(matched_item)
        
        return matched_items
    
    def _match_item(self, item: Dict, csv_rows: List[Dict], order_id: Optional[str]) -> Dict:
        """Match a single item to CSV data using normalized strings and cached matchers"""
        product_name = item.get('product_name', '')
        normalized_product_name = self._normalize_string(product_name)
        
        # Find best matching CSV row
        best_match = None
        best_score = 0.0
        
        # Get configurable item_name column names
        item_name_columns = self.id_field_mappings['item_name']
        
        for csv_row in csv_rows:
            # Try each possible item_name column name
            csv_item_name = None
            for col_name in item_name_columns:
                csv_item_name = csv_row.get(col_name, '').strip()
                if csv_item_name:
                    break
            
            if not csv_item_name:
                continue
            
            # Normalize CSV item name
            normalized_csv_name = self._normalize_string(csv_item_name)
            
            # Use cached SequenceMatcher if available
            cache_key = (normalized_product_name, normalized_csv_name)
            if cache_key not in self._matcher_cache:
                self._matcher_cache[cache_key] = SequenceMatcher(None, normalized_product_name, normalized_csv_name)
            
            # Get ratio from cached matcher
            score = self._matcher_cache[cache_key].ratio()
            
            if score > best_score and score >= self.match_threshold:
                best_score = score
                best_match = csv_row
        
        if best_match:
            # Override fields from CSV
            updated_item = item.copy()
            updated_item[self.csv_linked_field] = self.csv_linked_value
            
            for field in self.override_fields:
                # Get CSV value using configurable column name mappings
                csv_value = self._get_csv_value(best_match, field)
                
                if csv_value and field in ['size', 'uom', 'quantity', 'brand_name']:
                    # Map to receipt item field names
                    if field == 'uom':
                        updated_item['purchase_uom'] = str(csv_value).lower()
                    elif field == 'quantity':
                        try:
                            updated_item['quantity'] = float(csv_value)
                        except:
                            pass
                    elif field == 'size':
                        updated_item['size'] = str(csv_value)
                    elif field == 'brand_name':
                        # Normalize brand name before storing
                        updated_item['brand_name'] = self._normalize_string(str(csv_value))
            
            logger.info(self.log_linked.format(desc=product_name, order_id=order_id or 'unknown'))
            return updated_item
        else:
            logger.warning(self.log_missing.format(desc=product_name, order_id=order_id or 'unknown'))
            return item
    
    def _get_csv_value(self, csv_row: Dict, field: str) -> Optional[str]:
        """
        Get CSV value for a field using configurable column name mappings
        
        Args:
            csv_row: CSV row dictionary
            field: Internal field name (size, uom, quantity, brand_name)
            
        Returns:
            CSV value or None if not found
        """
        # Map field to id_fields key
        field_to_id_key = {
            'size': 'size',
            'uom': 'uom',
            'quantity': 'qty',
            'brand_name': 'brand_name',
        }
        
        id_key = field_to_id_key.get(field)
        if not id_key or id_key not in self.id_field_mappings:
            return None
        
        # Try each possible column name for this field
        column_names = self.id_field_mappings[id_key]
        for col_name in column_names:
            value = csv_row.get(col_name, '')
            if value:
                return str(value).strip()
        
        return None

