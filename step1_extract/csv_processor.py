#!/usr/bin/env python3
"""
CSV Processor - Extract product information from CSV files
Falls back to PDF processing if CSV not available
"""

import csv
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def derive_uom_from_size(size_str: str) -> Tuple[Optional[str], Dict]:
    """
    Derive UoM from size field in CSV data
    
    Detects patterns like:
    - 500 ct, 500 count, 500 pc → returns "ct" and {"count_per_package": 500}
    - 128 fl oz → returns "fl_oz"
    - 1 gal, 2 gallons → returns "gal"
    - 32 qt → returns "qt"
    - etc.
    
    Args:
        size_str: Size string from CSV (e.g., "500 ct", "128 fl oz")
        
    Returns:
        Tuple of (derived_uom, extra_fields_dict)
        where derived_uom is the unit (or None if not detected)
        and extra_fields_dict can include keys like "count_per_package"
    """
    if not size_str or not size_str.strip():
        return None, {}
    
    size_lower = size_str.strip().lower()
    extra_fields = {}
    
    # First check: if size field explicitly says "each" or "1 each", return None
    # (means unit is "each", not a measurable unit)
    each_patterns = [r'^\s*1\s+each\s*\.?$', r'^\s*each\s*\.?$']
    for pattern in each_patterns:
        if re.match(pattern, size_lower):
            return None, {}
    
    # Pattern 1: Count patterns (500 ct, 500 count, 500 pc, 500 piece, etc.)
    count_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:ct|count|pc|piece|pieces|pcs|pk|pkg|pack)',
        r'(\d+(?:\.\d+)?)\s*x\s*(?:ct|count|pc|piece)',
        r'(\d+(?:\.\d+)?)\s*(?:ct|count|pc)\b',
    ]
    for pattern in count_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            count = float(match.group(1))
            extra_fields['count_per_package'] = int(count)
            return 'ct', extra_fields
    
    # Pattern 2: Fluid ounce patterns (128 fl oz, 128 fl. oz., 128 floz)
    fl_oz_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:fl\.?\s*oz|floz|fluid\s*ounce|fluid\s*ounces)',
    ]
    for pattern in fl_oz_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            return 'fl_oz', extra_fields
    
    # Pattern 3: Gallon patterns (1 gal, 1 gallon, 2 gallons)
    gal_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:gal|gallon|gallons)',
    ]
    for pattern in gal_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            return 'gal', extra_fields
    
    # Pattern 4: Quart patterns (32 qt, 1 quart, 2 quarts)
    qt_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:qt|quart|quarts)',
    ]
    for pattern in qt_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            return 'qt', extra_fields
    
    # Pattern 5: Pint patterns (1 pt, 1 pint, 2 pints)
    pt_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:pt|pint|pints)',
    ]
    for pattern in pt_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            return 'pt', extra_fields
    
    # Pattern 6: Ounce patterns (16 oz, 1 ounce, 2 ounces) - but not fl oz (already checked)
    oz_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:oz|ounce|ounces)(?!\s*(?:fl|fluid))',
    ]
    for pattern in oz_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            # Make sure it's not part of "fl oz"
            match_text = match.group(0)
            if 'fl' not in match_text.lower():
                return 'oz', extra_fields
    
    # Pattern 7: Pound patterns (1 lb, 2 lbs, 1 pound, 2 pounds)
    lb_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:lb|lbs|pound|pounds)',
    ]
    for pattern in lb_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            return 'lb', extra_fields
    
    # Pattern 8: Kilogram patterns (1 kg, 2 kgs, 1 kilogram, 2 kilograms)
    kg_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:kg|kgs|kilogram|kilograms)',
    ]
    for pattern in kg_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            return 'kg', extra_fields
    
    # Pattern 9: Liter patterns (1 l, 2 l, 1 liter, 2 liters, 1 litre, 2 litres)
    liter_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:l|liter|liters|litre|litres)\b',
    ]
    for pattern in liter_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            return 'l', extra_fields
    
    # Pattern 10: Milliliter patterns (500 ml, 1000 ml)
    ml_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:ml|milliliter|milliliters|millilitre|millilitres)\b',
    ]
    for pattern in ml_patterns:
        match = re.search(pattern, size_lower, re.IGNORECASE)
        if match:
            return 'ml', extra_fields
    
    # No match found
    return None, {}


class CSVProcessor:
    """Process CSV files for receipt data"""
    
    def __init__(self, config=None):
        self.config = config or {}
    
    def find_csv_files(self, receipt_folder: Path) -> Dict[str, Path]:
        """
        Find CSV files in receipt folder
        
        Returns:
            Dictionary mapping CSV types to file paths
        """
        csv_files = {}
        
        # Look for order_item_summary_report.csv
        item_csv = receipt_folder / 'order_item_summary_report.csv'
        if item_csv.exists():
            csv_files['items'] = item_csv
        
        # Look for order_summary_report*.csv
        summary_csv = list(receipt_folder.glob('order_summary_report*.csv'))
        if summary_csv:
            csv_files['summary'] = summary_csv[0]
        
        return csv_files
    
    def extract_receipt_data_from_csv(self, csv_file: Path, order_id: Optional[str] = None, receipt_folder: Optional[Path] = None) -> Dict:
        """
        Extract receipt data from order_item_summary_report.csv
        
        Args:
            csv_file: Path to order_item_summary_report.csv
            order_id: Optional order ID to filter (if None, extracts first order)
            
        Returns:
            Dictionary with receipt data
        """
        receipt_data = {
            'order_id': None,
            'order_date': None,
            'delivery_date': None,
            'vendor': None,
            'store_name': None,
            'delivery_address': None,
            'currency': 'USD',
            'items': [],
            'raw_data': [],
            # Vendor information fields
            'vendor_info': {
                'name': None,
                'store_name': None,
                'store_id': None,
                'store_number': None,
                'address': None,
                'city': None,
                'state': None,
                'zip_code': None,
                'phone': None,
                'website': None,
                'member_number': None,
                'receipt_number': None,
                'other_info': {}
            },
        }
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # First pass: find matching order_id rows
            matching_rows = []
            for row in reader:
                if order_id:
                    if row['Order ID'] == order_id:
                        matching_rows.append(row)
                else:
                    matching_rows.append(row)
            
            # Use first row for metadata
            if matching_rows:
                first_row = matching_rows[0]
                receipt_data['order_id'] = first_row['Order ID']
                receipt_data['vendor_ref'] = first_row['Order ID']
                receipt_data['store_name'] = first_row['Store Name']
                # Format vendor as IC-{Store Name} for Instacart orders
                store_name = first_row['Store Name'].strip()
                receipt_data['vendor'] = f"IC-{store_name}" if store_name else None
                
                # Extract dates
                if first_row.get('Delivery Created At'):
                    receipt_data['order_date'] = self._parse_datetime(first_row['Delivery Created At'])
                if first_row.get('Delivered At'):
                    receipt_data['delivery_date'] = self._parse_datetime(first_row['Delivered At'])
                
                # Extract delivery address (customer address for Instacart)
                address_parts = [
                    first_row.get('Delivery Address', ''),
                    first_row.get('Delivery City', ''),
                    first_row.get('Delivery State', ''),
                    first_row.get('Delivery Zip Code', ''),
                ]
                receipt_data['delivery_address'] = ', '.join(filter(None, address_parts))
                
                # Extract vendor information from CSV
                receipt_data['vendor_info'] = {
                    'name': f"IC-{store_name}" if store_name else None,
                    'store_name': store_name,
                    'store_id': None,  # Not available in Instacart CSV
                    'store_number': None,
                    'address': None,  # Instacart doesn't provide store address
                    'city': None,
                    'state': None,
                    'zip_code': None,
                    'phone': None,
                    'website': None,
                    'member_number': None,
                    'receipt_number': first_row.get('Order ID'),
                    'other_info': {
                        'handoff_type': first_row.get('Handoff Type'),
                        'order_type': first_row.get('Order Type'),
                    }
                }
                
                receipt_data['currency'] = first_row.get('Currency', 'USD')
            
            # Extract items from matching rows
            for row in matching_rows:
                item = self._extract_item_from_csv_row(row)
                if item:
                    receipt_data['items'].append(item)
                    receipt_data['raw_data'].append(row)
        
        # Calculate subtotal from items only (fees come from PDF, not CSV)
        receipt_data['subtotal'] = sum(item['total_price'] for item in receipt_data['items'])
        receipt_data['total'] = receipt_data['subtotal']  # Will be updated with fees from PDF
        
        return receipt_data
    
    def validate_receipt_total(self, receipt_folder: Path, receipt_data: Dict, order_id: Optional[str] = None) -> Optional[Dict]:
        """
        Validate receipt total against order summary CSV
        
        Args:
            receipt_folder: Folder containing receipt files
            receipt_data: Receipt data dictionary with items and total
            order_id: Optional order ID to filter
            
        Returns:
            Validation dictionary with expected_total, matches, and difference
        """
        # Look for order_summary_report*.csv
        summary_csv = list(receipt_folder.glob('order_summary_report*.csv'))
        if not summary_csv:
            logger.warning("Order summary CSV not found for validation")
            return None
        
        summary_file = summary_csv[0]
        expected_total = None
        
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                has_order_id_column = 'Order ID' in fieldnames
                
                for row in reader:
                    # If order_id is provided and CSV has Order ID column, MUST match by Order ID only
                    if order_id and has_order_id_column:
                        row_order_id = row.get('Order ID', '').strip()
                        if not row_order_id or row_order_id != order_id:
                            # Order ID doesn't match, skip this row
                            continue
                        # Found matching order ID - proceed to extract total
                    else:
                        # No order_id provided OR CSV doesn't have Order ID column - match by date
                        receipt_date = receipt_data.get('order_date') or receipt_data.get('delivery_date')
                        if not receipt_date:
                            continue
                        
                        # Extract date string from receipt_date (could be ISO format)
                        from datetime import datetime
                        if isinstance(receipt_date, str):
                            try:
                                receipt_dt = datetime.fromisoformat(receipt_date.replace('Z', '+00:00'))
                                receipt_date_str = receipt_dt.strftime('%Y-%m-%d')
                            except:
                                receipt_date_str = receipt_date[:10] if len(receipt_date) >= 10 else receipt_date
                        else:
                            receipt_date_str = receipt_date.strftime('%Y-%m-%d') if hasattr(receipt_date, 'strftime') else str(receipt_date)
                        
                        csv_date = row.get('Date', '').strip()
                        if csv_date != receipt_date_str:
                            continue
                        
                        # If order_id is provided but CSV has no Order ID column, match by Store name
                        # (to distinguish multiple orders on the same date with same address)
                        if order_id and not has_order_id_column:
                            # Get store name from receipt data (vendor name)
                            receipt_vendor = receipt_data.get('vendor', '') or receipt_data.get('store_name', '')
                            csv_store = row.get('Store', '').strip()
                            
                            if receipt_vendor and csv_store:
                                # Normalize store names for comparison
                                receipt_store_normalized = receipt_vendor.lower().replace('-', ' ').replace('_', ' ').strip()
                                csv_store_normalized = csv_store.lower().replace('-', ' ').replace('_', ' ').strip()
                                
                                # Check if store names match (e.g., "IC-ALDI" should match "ALDI")
                                # Remove vendor prefixes like "IC-", "IC_" from receipt vendor
                                receipt_store_clean = receipt_store_normalized.replace('ic-', '').replace('ic_', '').strip()
                                
                                # Match if store names are similar
                                if (receipt_store_clean not in csv_store_normalized and 
                                    csv_store_normalized not in receipt_store_clean and
                                    receipt_store_normalized not in csv_store_normalized and
                                    csv_store_normalized not in receipt_store_normalized):
                                    continue
                    
                    # Try to find total amount in various column names
                    total_str = None
                    for col in ['Amount', 'Total', 'Total Amount', 'Order Total', 'Charged']:
                        if col in row:
                            total_str = row[col]
                            break
                    
                    if total_str:
                        try:
                            # Remove currency symbols and commas
                            expected_total = float(total_str.replace('$', '').replace(',', '').strip())
                            # Found matching row - break immediately (don't continue searching)
                            break
                        except:
                            continue
        except Exception as e:
            logger.warning(f"Could not read order summary CSV for validation: {e}")
            return None
        
        if expected_total is None:
            logger.warning("Could not find expected total in order summary CSV")
            return None
        
        # Get actual total from receipt data
        actual_total = receipt_data.get('total', 0.0)
        
        # Calculate difference
        difference = abs(actual_total - expected_total)
        
        # Consider it a match if difference is less than $0.01 (rounding differences)
        matches = difference < 0.01
        
        validation = {
            'expected_total': expected_total,
            'actual_total': actual_total,
            'difference': difference,
            'matches': matches,
        }
        
        return validation
    
    def _extract_item_from_csv_row(self, row: Dict) -> Optional[Dict]:
        """Extract item data from CSV row"""
        
        # Get quantity - use Picked Quantity if available, otherwise Ordered Quantity
        qty = float(row.get('Picked Quantity', row.get('Ordered Quantity', '1')))
        
        # Get unit price and total
        try:
            unit_price = float(row.get('Unit Price', '0'))
            total_price = float(row.get('Total Price', '0'))
        except:
            unit_price = 0.0
            total_price = 0.0
        
        # Get product name
        product_name = row.get('Item Name', '').strip()
        if not product_name:
            return None
        
        # Get size information
        size = row.get('Size', '').strip()
        
        # Determine UoM - prioritize Size field, then Cost Unit column
        purchase_uom = None
        size_uom_extra = {}
        
        # Step 1: Try to derive UoM from Size field
        if size:
            derived_uom, extra_fields = derive_uom_from_size(size)
            if derived_uom:
                purchase_uom = derived_uom
                size_uom_extra = extra_fields
                logger.debug(f"Derived UoM from Size field for '{product_name}': {purchase_uom} (size: {size})")
        
        # Step 2: If Size didn't yield a UoM, use Cost Unit column
        if not purchase_uom:
            cost_unit = row.get('Cost Unit', '').strip().lower()
            if cost_unit:
                purchase_uom = cost_unit
                logger.debug(f"Using UoM from Cost Unit column for '{product_name}': {purchase_uom}")
        
        # Step 3: Fallback to "each" only if both are missing
        if not purchase_uom:
            purchase_uom = 'each'
            logger.debug(f"No UoM found for '{product_name}', defaulting to 'each'")
        
        # For weight items, use picked weight if available
        if purchase_uom in ['lb', 'lbs', 'pound', 'pounds'] and row.get('Picked Weight'):
            try:
                qty = float(row['Picked Weight'])
            except:
                pass
        
        item = {
            'product_name': product_name,
            'brand_name': row.get('Brand Name', '').strip(),
            'size': size,
            'quantity': qty,
            'purchase_uom': purchase_uom,
            'unit_price': unit_price,
            'total_price': total_price,
            'ordered_quantity': row.get('Ordered Quantity', ''),
            'picked_quantity': row.get('Picked Quantity', ''),
            'ordered_weight': row.get('Ordered Weight', ''),
            'picked_weight': row.get('Picked Weight', ''),
            'product_category': row.get('Product Category Name', ''),
            'item_id': row.get('Item ID', ''),
            # Category fields from Instacart CSV for classification
            'department': row.get('Department Name', '').strip(),
            'aisle': row.get('Aisle Name', '').strip(),
            'l1_category_name': row.get('L1 Category Name', '').strip(),
            'l2_category_name': row.get('L2 Category Name', '').strip(),
            'l3_category_name': row.get('L3 Category Name', '').strip(),
            # Build category_path from hierarchy for matching
            'category_path': ' '.join(filter(None, [
                row.get('L3 Category Name', '').strip(),
                row.get('L2 Category Name', '').strip(),
                row.get('Product Category Name', '').strip(),
            ])).lower(),
        }
        
        # Merge any extra fields from size parsing (like count_per_package)
        item.update(size_uom_extra)
        
        return item
    
    def _parse_datetime(self, date_str: str) -> Optional[str]:
        """Parse datetime string from CSV (format: 2025-09-01 3:13PM CDT)"""
        from datetime import datetime
        
        if not date_str:
            return None
        
        # Try various formats
        formats = [
            '%Y-%m-%d %I:%M%p %Z',
            '%Y-%m-%d %I:%M %p %Z',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.isoformat()
            except:
                continue
        
        return date_str  # Return as-is if can't parse
    
    def process_receipt_with_csv(self, receipt_folder: Path, order_id: Optional[str] = None) -> Optional[Dict]:
        """
        Process receipt using CSV file if available
        
        Args:
            receipt_folder: Folder containing receipt PDF and CSV files
            order_id: Optional order ID to filter
            
        Returns:
            Receipt data dict if CSV found, None otherwise
        """
        csv_files = self.find_csv_files(receipt_folder)
        
        if 'items' in csv_files:
            logger.info(f"Found CSV file: {csv_files['items'].name}")
            receipt_data = self.extract_receipt_data_from_csv(csv_files['items'], order_id)
            logger.info(f"Extracted {len(receipt_data['items'])} items from CSV")
            return receipt_data
        
        return None

